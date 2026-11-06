"""
HTTP layer under the Unleash client: sends one request and returns the
response.

Pass a transport to the client to choose how requests are sent:
:class:`RequestsTransport` with your own ``requests.Session``,
``AiohttpTransport`` with your own ``aiohttp.ClientSession`` for the async
client, or any object with an ``execute(Request) -> Response`` method.
"""

import inspect
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional, Protocol, runtime_checkable

import requests
from requests.structures import CaseInsensitiveDict

from UnleashClient.constants import REQUEST_TIMEOUT
from UnleashClient.utils import LOGGER


class Method(str, Enum):
    GET = "GET"
    POST = "POST"

    __str__ = str.__str__


@dataclass(frozen=True, kw_only=True)
class Request:
    """
    HTTP request.

    :param method: HTTP method.
    :param url: Absolute url, without the query string.
    :param headers: Headers to send.
    :param params: Query string parameters.
    :param body: Request body, or None to send none.
    """

    method: Method
    url: str
    headers: Mapping[str, str]
    params: Mapping[str, str] = field(default_factory=dict)
    body: Optional[bytes] = None


@dataclass(frozen=True, kw_only=True)
class Response:
    """
    HTTP response. Every status is a response, not an error: deciding what
    a status means is the API client's job.

    :param status: HTTP status code.
    :param headers: Response headers. A plain ``dict`` is fine: the SDK looks
                    names up case-insensitively.
    :param body: Raw response body.
    """

    status: int
    headers: Mapping[str, str]
    body: bytes


@runtime_checkable
class Transport(Protocol):
    """
    Sends requests for the sync client.

    ``request.headers`` include the API key: don't log them.
    """

    def execute(self, request: Request) -> Response:
        """
        Implementations must send ``request`` once and return the response,
        regardless of its status code. They must not retry: the SDK retries
        feature fetches itself.

        Implementations must not raise when a response was received, even for
        an error status. They raise only if no response was received, for
        example due to a connection error or timeout.
        """


@runtime_checkable
class AsyncTransport(Protocol):
    """
    Sends requests for the async client.

    ``request.headers`` include the API key: don't log them.
    """

    async def execute(self, request: Request) -> Response:
        """
        Implementations must send ``request`` once and return the response,
        regardless of its status code. They must not retry: the SDK retries
        feature fetches itself.

        Implementations must not raise when a response was received, even for
        an error status. They raise only if no response was received, for
        example due to a connection error or timeout.
        """


def _reject_authorization(headers: Mapping[str, str], transport_name: str) -> None:
    if any(name.lower() == "authorization" for name in headers):
        raise ValueError(
            "Pass the API key as api_key to the client, "
            f"not as an Authorization header to {transport_name}."
        )


def _check_transport(
    transport: object,
    *,
    http_given: bool,
    is_async: bool,
    session_name: str,
    wrapper_name: str,
) -> None:
    """
    Raises for a transport the client can't use, so the mistake shows up in the
    constructor instead of as a failed request on every poll.
    """
    # temp check until HttpOptions is gone
    if http_given:
        raise ValueError(
            "Pass either http or transport, not both. Set headers and the "
            f"timeout on the transport: {wrapper_name}(headers=..., timeout=...)."
        )
    execute = getattr(transport, "execute", None)
    if not callable(execute):
        raise TypeError(
            "transport must have an execute(request) method, see "
            f"UnleashClient.transport. To use your own {session_name}, pass "
            f"transport={wrapper_name}(session)."
        )
    is_coroutine = inspect.iscoroutinefunction(execute)
    if is_async and not is_coroutine:
        is_coroutine = inspect.iscoroutinefunction(inspect.unwrap(execute))
    if is_coroutine != is_async:
        raise TypeError(
            "transport.execute is not async: AsyncUnleashClient needs an async "
            "transport."
            if is_async
            else "transport.execute is async: UnleashClient needs a sync transport."
        )


def _session_retries(session: requests.Session) -> bool:
    """True if a mounted adapter retries; a plain Session's adapters don't."""
    for adapter in session.adapters.values():
        retry = getattr(adapter, "max_retries", None)
        if retry is not None and (
            retry.total or retry.connect or retry.read or retry.status
        ):
            return True
    return False


class RequestsTransport:
    """
    Sends requests with ``requests``.

    Sends each request once: retrying is the SDK's job, so don't mount a
    retrying adapter on the session.

    Example::

        session = requests.Session()
        session.proxies = {"https": "http://proxy.internal:3128"}
        UnleashClient(url, app_name, transport=RequestsTransport(session))

    :param session: Session to send every request on. It is never closed: its
                    creator closes it. Without one, every request gets a fresh
                    session, closed after the response.
    :param headers: Extra headers sent with every request. The SDK's own headers
                    take precedence over them.
    :param timeout: Seconds to wait for the connection and for each read.
    :raises ValueError: If ``headers`` contains an ``Authorization`` header: pass
                        the API key as ``api_key`` to the client.
    """

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        *,
        headers: Optional[Mapping[str, str]] = None,
        timeout: float = REQUEST_TIMEOUT,
        # going away with HttpOptions
        _request_kwargs: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self._session = session
        self._headers = dict(headers or {})
        self._timeout = timeout
        self._request_kwargs = dict(_request_kwargs or {})

        _reject_authorization(self._headers, "RequestsTransport")
        if session is not None and _session_retries(session):
            LOGGER.warning(
                "The session passed to RequestsTransport retries requests itself. "
                "The SDK also retries feature fetches, so failed fetches are "
                "retried twice over."
            )

    def execute(self, request: Request) -> Response:
        headers = CaseInsensitiveDict(self._headers)
        headers.update(request.headers)
        kwargs: dict = {"headers": headers, "timeout": self._timeout}
        if request.params:
            kwargs["params"] = dict(request.params)
        if request.body is not None:
            kwargs["data"] = request.body

        if self._session is not None:
            return self._send(self._session, request, kwargs)
        with requests.Session() as session:
            return self._send(session, request, kwargs)

    def _send(
        self, session: requests.Session, request: Request, kwargs: dict
    ) -> Response:
        resp = session.request(
            request.method, request.url, **kwargs, **self._request_kwargs
        )
        return Response(
            status=resp.status_code, headers=resp.headers, body=resp.content
        )
