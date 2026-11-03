"""
HTTP layer under the Unleash API client: sends one request and returns the
response.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional, Protocol, runtime_checkable

import requests
from requests.adapters import HTTPAdapter
from urllib3 import Retry

from UnleashClient.constants import REQUEST_TIMEOUT


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
    :param headers: Response headers, looked up case-insensitively.
    :param body: Raw response body.
    """

    status: int
    headers: Mapping[str, str]
    body: bytes


@runtime_checkable
class Transport(Protocol):
    """Sends requests for the sync client."""

    def execute(self, request: Request) -> Response:
        """
        Implementations must send ``request`` once and return the response,
        regardless of its status code.

        Implementations must not raise when a response was received, even for
        an error status. They raise only if no response was received, for
        example due to a connection error or timeout.
        """


@runtime_checkable
class AsyncTransport(Protocol):
    """Sends requests for the async client."""

    async def execute(self, request: Request) -> Response:
        """
        Send ``request`` once and return the response, whatever its status.

        :raises Exception: only when no response arrived, e.g. a connection
                           error or a timeout.
        """


class RequestsTransport:
    """
    Sends requests with ``requests``, on a fresh session for every request.

    :param timeout: Seconds to wait for the connection and for each read.
    :param _retries: GET requests are retried this many times on a connection
                     error or a 500, 502 or 504, by urllib3.
    :param _request_kwargs: extra keyword arguments for every ``requests`` call.
    """

    def __init__(
        self,
        *,
        timeout: float = REQUEST_TIMEOUT,
        # these two are are going away too
        _retries: Optional[int] = None,
        _request_kwargs: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self._timeout = timeout
        self._retries = _retries
        self._request_kwargs = dict(_request_kwargs or {})

    def execute(self, request: Request) -> Response:
        kwargs: dict = {"headers": dict(request.headers), "timeout": self._timeout}
        if request.params:
            kwargs["params"] = dict(request.params)
        if request.body is not None:
            kwargs["data"] = request.body

        with requests.Session() as session:
            if request.method == Method.GET and self._retries is not None:
                adapter = HTTPAdapter(
                    max_retries=Retry(
                        total=self._retries, status_forcelist=[500, 502, 504]
                    )
                )
                session.mount("https://", adapter)
                session.mount("http://", adapter)

            resp = session.request(
                request.method, request.url, **kwargs, **self._request_kwargs
            )
            return Response(
                status=resp.status_code, headers=resp.headers, body=resp.content
            )
