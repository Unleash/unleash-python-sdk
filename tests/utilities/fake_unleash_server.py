import logging
from collections import deque
from typing import Any, Deque, Dict, List, NamedTuple, Optional, Tuple

from aiohttp import web
from aiohttp.test_utils import TestServer
from multidict import CIMultiDictProxy

#: Answered for a request no reply was scripted for.
UNEXPECTED_REQUEST_STATUS = 599

_Route = Tuple[str, str]


class RecordedRequest(NamedTuple):
    """One request as the server parsed it off the wire."""

    method: str
    path: str
    query: Dict[str, str]
    headers: CIMultiDictProxy
    body: str


class _Reply(NamedTuple):
    status: int
    payload: Optional[Any]
    headers: Dict[str, str]
    disconnect: bool


class FakeUnleash:
    """
    A programmable Unleash server that tests can make real requests against.

    Replies are scripted per method and path with :meth:`on`, and every request
    that arrives is recorded for :meth:`calls`. Assertions therefore run against
    what the client put on the wire rather than against the arguments it handed
    aiohttp, which is what makes this usable in place of a library that patches
    ``ClientSession``.

    A request that no reply was scripted for is recorded and answered
    :data:`UNEXPECTED_REQUEST_STATUS`, so a mistargeted URL fails its test
    instead of quietly matching something else.
    """

    def __init__(self) -> None:
        self.base_url: str = ""
        self.requests: List[RecordedRequest] = []
        self._queued: Dict[_Route, Deque[_Reply]] = {}
        self._repeated: Dict[_Route, _Reply] = {}
        self._server: Optional[TestServer] = None
        self._server_log_level: Optional[int] = None

    def on(
        self,
        method: str,
        path: str,
        *,
        status: int = 200,
        payload: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        repeat: bool = False,
        disconnect: bool = False,
    ) -> None:
        """
        Script one reply.

        Queued replies are served in the order they were scripted, which is how
        a test drives a retry through a failure and into a success.

        :param method: HTTP method to match.
        :param path: request path to match, including any API prefix.
        :param status: status code to answer with.
        :param payload: JSON body to answer with, or None for an empty body.
        :param headers: response headers, such as an etag.
        :param repeat: serve this reply for every matching request rather than
                       once.
        :param disconnect: close the connection without answering, which the
                           client sees as a ``ClientConnectionError``.
        """
        reply = _Reply(status, payload, headers or {}, disconnect)
        route = (method.upper(), path)

        if repeat:
            self._repeated[route] = reply
        else:
            self._queued.setdefault(route, deque()).append(reply)

    def calls(self, method: str, path: str) -> List[RecordedRequest]:
        """
        Every request that reached this server for a method and path, in order.

        :param method: HTTP method to match.
        :param path: request path to match, excluding the query string.
        """
        method = method.upper()
        return [
            request
            for request in self.requests
            if request.method == method and request.path == path
        ]

    async def start(self, path_prefix: str = "") -> str:
        """
        Listen on an ephemeral port and return the base URL to configure a
        client with.

        :param path_prefix: mounted ahead of the Unleash endpoints, so a test
                            exercises the same URL shape as a real deployment.
        """
        app = web.Application()
        app.router.add_route("*", "/{path:.*}", self._handle)

        self._server = TestServer(app)
        await self._server.start_server()

        # A deliberate disconnect leaves the handler with nothing to answer on,
        # which aiohttp reports as an unhandled server error. Unexpected
        # requests are surfaced through UNEXPECTED_REQUEST_STATUS instead.
        server_log = logging.getLogger("aiohttp.server")
        self._server_log_level = server_log.level
        server_log.setLevel(logging.CRITICAL)

        self.base_url = str(self._server.make_url(path_prefix)).rstrip("/")
        return self.base_url

    async def close(self) -> None:
        """Stop listening and restore the aiohttp server log level."""
        if self._server_log_level is not None:
            logging.getLogger("aiohttp.server").setLevel(self._server_log_level)
            self._server_log_level = None

        if self._server is not None:
            await self._server.close()
            self._server = None

    async def _handle(self, request: web.Request) -> web.Response:
        self.requests.append(
            RecordedRequest(
                method=request.method,
                path=request.path,
                query=dict(request.query),
                headers=request.headers.copy(),
                body=await request.text(),
            )
        )

        reply = self._next_reply((request.method, request.path))

        if reply is None:
            return web.Response(
                status=UNEXPECTED_REQUEST_STATUS, text=f"unscripted {request.rel_url}"
            )

        if reply.disconnect:
            request.transport.abort()
            raise ConnectionResetError("disconnected by FakeUnleash")

        if reply.payload is None:
            return web.Response(status=reply.status, headers=reply.headers)

        return web.json_response(
            reply.payload, status=reply.status, headers=reply.headers
        )

    def _next_reply(self, route: _Route) -> Optional[_Reply]:
        queued = self._queued.get(route)

        if queued:
            return queued.popleft()

        return self._repeated.get(route)
