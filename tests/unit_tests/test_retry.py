import asyncio

import pytest
from pytest import mark, param

from UnleashClient import _retry
from UnleashClient._retry import (
    BACKOFF_BASE,
    _send_with_retries,
    _send_with_retries_async,
)
from UnleashClient._transport import Method, Request, Response
from UnleashClient.errors import AlreadyClosedError

# Imported before the autouse no_retry_backoff fixture replaces it.
_real_backoff_delay = _retry._backoff_delay

REQUEST = Request(
    method=Method.GET, url="http://localhost/api/client/features", headers={}
)


def reply(status: int) -> Response:
    return Response(status=status, headers={}, body=b"")


class SequenceTransport:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def _next(self) -> Response:
        outcome = self.outcomes[min(self.calls, len(self.outcomes) - 1)]
        self.calls += 1
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class SyncSequenceTransport(SequenceTransport):
    def execute(self, request: Request) -> Response:
        return self._next()


class AsyncSequenceTransport(SequenceTransport):
    async def execute(self, request: Request) -> Response:
        return self._next()


def send(flavor: str, outcomes, retries: int):
    """Runs the sync or the async policy over ``outcomes``; returns (outcome, calls)."""
    if flavor == "sync":
        transport = SyncSequenceTransport(*outcomes)
        outcome = _send_with_retries(transport, REQUEST, retries)
    else:
        transport = AsyncSequenceTransport(*outcomes)
        outcome = asyncio.run(_send_with_retries_async(transport, REQUEST, retries))
    return outcome, transport.calls


both_flavors = mark.parametrize("flavor", ["sync", "async"])


@both_flavors
@mark.parametrize(
    "outcomes,retries,expected_status,expected_calls",
    (
        param([reply(200)], 3, 200, 1, id="success-first-time"),
        param([reply(500), reply(200)], 3, 200, 2, id="500-then-success"),
        param([reply(502), reply(200)], 3, 200, 2, id="502-then-success"),
        param([reply(504), reply(200)], 3, 200, 2, id="504-then-success"),
        param([OSError("refused"), reply(200)], 3, 200, 2, id="error-then-success"),
        param([reply(500)], 3, 500, 4, id="500-every-time-returns-the-last"),
        param([reply(500)], 0, 500, 1, id="no-retries"),
        param([reply(304)], 3, 304, 1, id="304-not-retried"),
        param([reply(401)], 3, 401, 1, id="401-not-retried"),
        param([reply(429)], 3, 429, 1, id="429-not-retried"),
        param([reply(503)], 3, 503, 1, id="503-not-retried"),
    ),
)
def test_retry_policy(flavor, outcomes, retries, expected_status, expected_calls):
    response, calls = send(flavor, outcomes, retries)

    assert response.status == expected_status
    assert calls == expected_calls


class ForeignTransportError(Exception):
    """Stands for an error of any HTTP library the policy knows nothing about."""


@both_flavors
@mark.parametrize(
    "error",
    (ForeignTransportError("boom"), OSError("refused"), TimeoutError()),
    ids=("foreign", "os-error", "timeout"),
)
def test_any_exception_is_retried_and_the_last_one_raised(flavor, error):
    with pytest.raises(type(error)):
        send(flavor, [error], 3)


def test_an_exception_on_every_attempt_is_tried_retries_plus_one_times():
    transport = SyncSequenceTransport(OSError("refused"))

    with pytest.raises(OSError):
        _send_with_retries(transport, REQUEST, 3)

    assert transport.calls == 4


@mark.asyncio
async def test_an_exception_on_every_attempt_is_tried_retries_plus_one_times_async():
    transport = AsyncSequenceTransport(OSError("refused"))

    with pytest.raises(OSError):
        await _send_with_retries_async(transport, REQUEST, 3)

    assert transport.calls == 4


@both_flavors
def test_a_closed_transport_is_not_retried(flavor):
    with pytest.raises(AlreadyClosedError):
        send(flavor, [AlreadyClosedError()], 3)


def test_a_cancelled_fetch_is_not_retried():
    transport = AsyncSequenceTransport(asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_send_with_retries_async(transport, REQUEST, 3))

    assert transport.calls == 1


# backoff


@both_flavors
def test_the_backoff_waits_between_attempts_but_not_after_the_last(flavor, monkeypatch):
    slept = []

    async def async_sleep(delay):
        slept.append(delay)

    monkeypatch.setattr(_retry, "_backoff_delay", lambda retry: retry + 1)
    monkeypatch.setattr(_retry, "_sleep", slept.append)
    monkeypatch.setattr(_retry, "_async_sleep", async_sleep)

    send(flavor, [reply(500)], 3)

    assert slept == [1, 2, 3]


@both_flavors
def test_no_backoff_without_a_retry(flavor, monkeypatch):
    slept = []

    async def async_sleep(delay):
        slept.append(delay)

    monkeypatch.setattr(_retry, "_sleep", slept.append)
    monkeypatch.setattr(_retry, "_async_sleep", async_sleep)

    send(flavor, [reply(200)], 3)

    assert slept == []


@mark.parametrize("retry", [0, 1, 2])
def test_the_backoff_doubles_with_jitter_in_its_upper_half(retry):
    ceiling = BACKOFF_BASE * 2**retry

    delays = [_real_backoff_delay(retry) for _ in range(200)]

    assert all(ceiling / 2 <= delay <= ceiling for delay in delays)
    assert len(set(delays)) > 1


def test_the_default_backoff_adds_at_most_3_5_seconds():
    assert sum(BACKOFF_BASE * 2**retry for retry in range(3)) == 3.5
