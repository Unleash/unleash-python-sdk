"""
What both API clients share: the fetch result, how a fetch outcome is
classified and reported, and reading a response. Names no HTTP library.
"""

import uuid
from typing import NamedTuple, Optional

from UnleashClient._event_dispatcher import _EventDispatcher
from UnleashClient.events import (
    FetchStatus,
    UnleashEventType,
    UnleashFetchCompletedEvent,
)
from UnleashClient.transport import Response
from UnleashClient.utils import LOGGER


class FetchResult(NamedTuple):
    """
    The outcome of one feature fetch.

    :param raw_state: Feature state body, or None on a 304 and on failure.
    :param etag: ETag returned by the server, or "" when the response had none.
    :param not_modified: True when the server answered 304.
    """

    raw_state: Optional[str]
    etag: str
    not_modified: bool = False


def _failure_status(http_status_code: Optional[int]) -> FetchStatus:
    """Classifies a failed fetch by the response it got, if any."""
    if http_status_code is None:
        return FetchStatus.UNAVAILABLE
    if http_status_code in (401, 403):
        return FetchStatus.UNAUTHORIZED
    if http_status_code == 429:
        return FetchStatus.RATE_LIMITED
    if http_status_code >= 500:
        return FetchStatus.UNAVAILABLE
    return FetchStatus.INVALID_RESPONSE


def _fetched_status(raw_state: str) -> FetchStatus:
    """An empty 200 is not usable: there is no state to apply."""
    return FetchStatus.CHANGED if raw_state else FetchStatus.INVALID_RESPONSE


def _emit_fetch_completed(
    events: Optional[_EventDispatcher], status: FetchStatus
) -> None:
    """
    Reports how a fetch ended. Never raises: a broken listener must not break
    the fetch.
    """
    if events is None:
        return

    try:
        events.emit_event(
            UnleashFetchCompletedEvent(
                event_type=UnleashEventType.FETCH_COMPLETED,
                event_id=uuid.uuid4(),
                status=status,
            )
        )
    except Exception:  # pylint: disable=broad-except
        LOGGER.debug("Failed to emit the fetch completed event", exc_info=True)


def _normalized_url(url: str, path: str) -> str:
    return f"{url}{path}"


def _header(resp: Response, name: str) -> str:
    name = name.lower()
    for key, value in resp.headers.items():
        if key.lower() == name:
            return value
    return ""


def _text(resp: Response) -> str:
    return resp.body.decode("utf-8", errors="replace")


def _log_resp_info(resp: Response) -> None:
    LOGGER.debug("HTTP status code: %s", resp.status)
    LOGGER.debug("HTTP headers: %s", resp.headers)
    LOGGER.debug("HTTP content: %s", _text(resp))
