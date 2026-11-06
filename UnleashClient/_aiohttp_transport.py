"""
HTTP layer under the async Unleash API client: sends one request with aiohttp
and returns the response.
"""

from typing import Mapping, Optional

from UnleashClient.constants import REQUEST_TIMEOUT
from UnleashClient.errors import AlreadyClosedError
from UnleashClient.transport import Request, Response, _reject_authorization

try:
    import aiohttp
    from multidict import CIMultiDict
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "AsyncUnleashClient requires aiohttp, which is not installed. "
        "Install it with: pip install UnleashClient[async]"
    ) from exc


class AiohttpTransport:
    """
    Sends requests with ``aiohttp``, on one session reused across requests.


    Example::

        async with aiohttp.ClientSession(trust_env=True) as session:
            async with AsyncUnleashClient(
                url, app_name, transport=AiohttpTransport(session)
            ) as client:
                ...

    :param session: Session to send every request on. It is never closed: its
                    creator closes it, after the client. Without one, the
                    transport opens its own on the first request, and
                    :meth:`aclose` closes it.
    :param headers: Extra headers sent with every request. The SDK's own headers
                    take precedence over them.
    :param timeout: Seconds to wait for the connection and for each read. Applies
                    to every request, in place of the session's own timeout.
    :raises ValueError: If ``headers`` contains an ``Authorization`` header: pass
                        the API key as ``api_key`` to the client.
    """

    def __init__(
        self,
        session: Optional["aiohttp.ClientSession"] = None,
        *,
        headers: Optional[Mapping[str, str]] = None,
        timeout: float = REQUEST_TIMEOUT,
    ) -> None:
        self._user_session = session
        self._headers = dict(headers or {})
        self._timeout = timeout
        self._session: Optional["aiohttp.ClientSession"] = None
        self._is_closed: bool = False

        _reject_authorization(self._headers, "AiohttpTransport")

    def _get_session(self) -> "aiohttp.ClientSession":
        if self._is_closed:
            raise AlreadyClosedError()
        if self._user_session is not None:
            return self._user_session
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
        headers = CIMultiDict(self._headers)
        headers.update(request.headers)
        async with self._get_session().request(
            request.method,
            request.url,
            headers=headers,
            params=dict(request.params) or None,
            data=request.body,
            timeout=self._client_timeout(),
            raise_for_status=False,
        ) as resp:
            body = await resp.read()
            return Response(status=resp.status, headers=resp.headers, body=body)

    async def aclose(self) -> None:
        """
        Put the transport out of service, and close its session if the transport
        opened it. Every later request raises :class:`AlreadyClosedError`.
        Closing a closed transport does nothing.
        """
        self._is_closed = True
        session, self._session = self._session, None
        if session is not None:
            await session.close()
