"""
HTTP transport for the sync client, on ``requests``: sends one request and
returns the response.
"""

from typing import Any, Mapping, Optional

import requests
from requests.structures import CaseInsensitiveDict

from UnleashClient.constants import REQUEST_TIMEOUT
from UnleashClient.transport import Request, Response, _reject_authorization
from UnleashClient.utils import LOGGER


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
