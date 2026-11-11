"""
HTTP layer under the Unleash client: sends one request and returns the
response.

Pass a transport to the client to choose how requests are sent:
``RequestsTransport`` with your own ``requests.Session``,
``AiohttpTransport`` with your own ``aiohttp.ClientSession`` for the async
client, or any object with an ``execute(Request) -> Response`` method.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Optional, Protocol, runtime_checkable


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
