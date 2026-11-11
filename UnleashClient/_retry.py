"""
The retry policy for feature fetches, shared by the sync and async clients.

Transports send each request once; retrying is decided here. Register and
metrics are never retried.
"""

import asyncio
import random
import time
from typing import Union

from UnleashClient.errors import AlreadyClosedError
from UnleashClient.transport import AsyncTransport, Request, Response, Transport
from UnleashClient.utils import LOGGER

RETRY_STATUSES = frozenset({500, 502, 504})
BACKOFF_BASE = 0.5

_sleep = time.sleep
_async_sleep = asyncio.sleep


def _backoff_delay(retry: int) -> float:
    """
    Seconds to wait before retry number ``retry`` (0 for the first).

    Exponential with jitter: a random point in the upper half of
    ``BACKOFF_BASE * 2 ** retry``, so 0.25-0.5s, 0.5-1s, 1-2s, and clients that
    failed together don't retry together.
    """
    ceiling = BACKOFF_BASE * 2**retry
    return random.uniform(ceiling / 2, ceiling)


_Outcome = Union[Response, Exception]


def _attempts(retries: int) -> range:
    """The attempt numbers: the first attempt and ``retries`` retries."""
    return range(1 + max(retries, 0))


def _should_retry(attempt: int, retries: int, outcome: _Outcome) -> bool:
    if attempt >= max(retries, 0):
        return False
    if isinstance(outcome, Response):
        return outcome.status in RETRY_STATUSES
    return not isinstance(outcome, AlreadyClosedError)


def _next_step(attempt: int, retries: int, outcome: _Outcome) -> Union[Response, float]:
    if not _should_retry(attempt, retries, outcome):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    delay = _backoff_delay(attempt)
    reason = (
        f"HTTP status {outcome.status}"
        if isinstance(outcome, Response)
        else repr(outcome)
    )
    LOGGER.debug("Retrying feature fetch in %.2fs after %s", delay, reason)
    return delay


def _send_with_retries(
    transport: Transport, request: Request, retries: int
) -> Response:
    """
    Send ``request``, retrying on a status in :data:`RETRY_STATUSES` and on any
    exception, with a backoff between attempts

    :param retries: Retries after the first attempt; negative counts as 0.
    :return: The last response, which can still have a retry status.
    :raises Exception: The last attempt's exception, if it raised.
    """
    for attempt in _attempts(retries):
        try:
            outcome: _Outcome = transport.execute(request)
        except Exception as exc:  # pylint: disable=broad-except
            outcome = exc
        step = _next_step(attempt, retries, outcome)
        if isinstance(step, Response):
            return step
        _sleep(step)

    raise AssertionError("unreachable: the last attempt returns or raises")


async def _send_with_retries_async(
    transport: AsyncTransport, request: Request, retries: int
) -> Response:
    """The asyncio twin of :func:`_send_with_retries`: only the awaits differ."""
    for attempt in _attempts(retries):
        try:
            outcome: _Outcome = await transport.execute(request)
        except Exception as exc:  # pylint: disable=broad-except
            outcome = exc
        step = _next_step(attempt, retries, outcome)
        if isinstance(step, Response):
            return step
        await _async_sleep(step)

    raise AssertionError("unreachable: the last attempt returns or raises")
