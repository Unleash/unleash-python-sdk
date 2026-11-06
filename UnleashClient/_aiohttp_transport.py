"""
HTTP layer under the async Unleash API client: sends one request with aiohttp
and returns the response.
"""

from typing import Optional

from UnleashClient.constants import REQUEST_TIMEOUT
from UnleashClient.errors import AlreadyClosedError
from UnleashClient.transport import Request, Response

try:
    import aiohttp
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "AsyncUnleashClient requires aiohttp, which is not installed. "
        "Install it with: pip install UnleashClient[async]"
    ) from exc


class AiohttpTransport:
    """
    Sends requests with ``aiohttp``, on one session reused across requests.

    The session is opened on the first request, since aiohttp needs a running
    event loop to create one, and closed by :meth:`aclose`. A closed transport
    stays closed.

    :param timeout: Seconds to wait for the connection and for each read.
    """

    def __init__(self, *, timeout: float = REQUEST_TIMEOUT) -> None:
        self._timeout = timeout
        self._session: Optional["aiohttp.ClientSession"] = None
        self._is_closed: bool = False

    def _get_session(self) -> "aiohttp.ClientSession":
        if self._is_closed:
            raise AlreadyClosedError()
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    def _client_timeout(self) -> "aiohttp.ClientTimeout":
        # sock_connect/sock_read rather than total: the sync client's scalar
        # timeout bounds each socket operation, not the whole request.
        return aiohttp.ClientTimeout(
            total=None, sock_connect=self._timeout, sock_read=self._timeout
        )

    async def execute(self, request: Request) -> Response:
        async with self._get_session().request(
            request.method,
            request.url,
            headers=dict(request.headers),
            params=dict(request.params) or None,
            data=request.body,
            timeout=self._client_timeout(),
        ) as resp:
            body = await resp.read()
            return Response(status=resp.status, headers=resp.headers, body=body)

    async def aclose(self) -> None:
        """
        Close the session. Every later request raises
        :class:`AlreadyClosedError`. Closing a closed transport does nothing.
        """
        self._is_closed = True
        session, self._session = self._session, None
        if session is not None:
            await session.close()
