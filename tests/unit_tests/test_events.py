import threading
import time
import uuid
from typing import Callable, Iterator

import pytest

from UnleashClient.events import (
    EventDispatcher,
    UnleashEvent,
    UnleashEventType,
    UnleashReadyEvent,
)

WAIT_TIMEOUT = 5


def flag_event(feature_name: str = "testFlag") -> UnleashEvent:
    return UnleashEvent(
        event_type=UnleashEventType.FEATURE_FLAG,
        event_id=uuid.uuid4(),
        context={},
        enabled=True,
        feature_name=feature_name,
    )


def ready_event() -> UnleashReadyEvent:
    return UnleashReadyEvent(
        event_type=UnleashEventType.READY,
        event_id=uuid.uuid4(),
    )


@pytest.fixture()
def dispatcher_factory() -> Iterator[Callable[..., EventDispatcher]]:
    """
    Builds dispatchers and guarantees they're torn down, so a wedged worker thread
    can't leak into the next test.
    """
    created: list[EventDispatcher] = []

    def _build(*args, **kwargs) -> EventDispatcher:
        dispatcher = EventDispatcher(*args, **kwargs)
        created.append(dispatcher)
        return dispatcher

    yield _build

    for dispatcher in created:
        dispatcher.close(timeout=1)


def test_events_are_dropped_when_the_queue_is_full(
    dispatcher_factory: Callable[..., EventDispatcher],
):
    entered = threading.Event()
    release = threading.Event()

    def callback(_event: UnleashEvent):
        entered.set()
        _ = release.wait(timeout=WAIT_TIMEOUT)

    dispatcher = dispatcher_factory(callback, max_size=2)

    # The worker parks inside the callback, so the queue can only ever hold two.
    dispatcher.emit_event(flag_event())
    assert entered.wait(timeout=WAIT_TIMEOUT)

    for _ in range(10):
        dispatcher.emit_event(flag_event())

    assert dispatcher.dropped_events == 8

    release.set()


def test_close_drains_pending_events(
    dispatcher_factory: Callable[..., EventDispatcher],
):
    received = []
    gate = threading.Event()

    def callback(event: UnleashEvent):
        _ = gate.wait(timeout=WAIT_TIMEOUT)
        received.append(event)

    dispatcher = dispatcher_factory(callback)

    for index in range(5):
        dispatcher.emit_event(flag_event(str(index)))

    gate.set()
    dispatcher.close(timeout=WAIT_TIMEOUT)

    assert [event.feature_name for event in received] == ["0", "1", "2", "3", "4"]


def test_close_is_idempotent(dispatcher_factory: Callable[..., EventDispatcher]):
    received: list[UnleashEvent] = []
    dispatcher = dispatcher_factory(received.append)

    dispatcher.emit_event(flag_event())
    dispatcher.close(timeout=WAIT_TIMEOUT)
    dispatcher.close(timeout=WAIT_TIMEOUT)

    assert len(received) == 1


def test_close_returns_even_when_the_callback_hangs(
    dispatcher_factory: Callable[..., EventDispatcher],
):
    entered = threading.Event()
    release = threading.Event()

    def callback(_event: UnleashEvent):
        entered.set()
        _ = release.wait(timeout=WAIT_TIMEOUT)

    dispatcher = dispatcher_factory(callback, max_size=1)

    dispatcher.emit_event(flag_event())
    assert entered.wait(timeout=WAIT_TIMEOUT)
    dispatcher.emit_event(flag_event())  # fills the queue, so the sentinel can't fit

    start = time.monotonic()
    dispatcher.close(timeout=0.2)
    elapsed = time.monotonic() - start

    assert elapsed < 2

    release.set()


def test_emit_event_after_close_is_a_no_op(
    dispatcher_factory: Callable[..., EventDispatcher],
):
    received: list[UnleashEvent] = []
    dispatcher = dispatcher_factory(received.append)

    dispatcher.emit_event(flag_event("before"))
    dispatcher.close(timeout=WAIT_TIMEOUT)
    dispatcher.emit_event(flag_event("after"))
    dispatcher.emit_event(ready_event())

    assert [event.feature_name for event in received] == ["before"]
