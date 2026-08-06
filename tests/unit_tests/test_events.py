import json
import threading
import time
import uuid
from typing import Callable, Iterator

import pytest

from UnleashClient.events import (
    EventDispatcher,
    UnleashEvent,
    UnleashEventType,
    UnleashFetchedEvent,
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


def variant_event(feature_name: str = "testVariations") -> UnleashEvent:
    return UnleashEvent(
        event_type=UnleashEventType.VARIANT,
        event_id=uuid.uuid4(),
        context={},
        enabled=True,
        feature_name=feature_name,
        variant="VarA",
    )


def ready_event() -> UnleashReadyEvent:
    return UnleashReadyEvent(
        event_type=UnleashEventType.READY,
        event_id=uuid.uuid4(),
    )


def fetched_event() -> UnleashFetchedEvent:
    return UnleashFetchedEvent(
        event_type=UnleashEventType.FETCHED,
        event_id=uuid.uuid4(),
        raw_features=json.dumps({"features": [{"name": "testFlag"}]}),
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


def test_emit_event_does_not_block_the_caller(
    dispatcher_factory: Callable[..., EventDispatcher],
):
    entered = threading.Event()
    release = threading.Event()
    received: list[UnleashEvent] = []

    def callback(event: UnleashEvent):
        entered.set()
        _ = release.wait(timeout=WAIT_TIMEOUT)
        received.append(event)

    dispatcher = dispatcher_factory(callback)

    # Wedge the worker inside the callback, then keep emitting.
    dispatcher.emit_event(flag_event())
    assert entered.wait(timeout=WAIT_TIMEOUT)

    start = time.monotonic()
    for index in range(100):
        dispatcher.emit_event(flag_event(str(index)))
    elapsed = time.monotonic() - start

    assert elapsed < 1

    release.set()
    assert dispatcher.flush(timeout=WAIT_TIMEOUT)
    assert len(received) == 101


def test_events_are_delivered_in_order(
    dispatcher_factory: Callable[..., EventDispatcher],
):
    received: list[UnleashEvent] = []
    dispatcher = dispatcher_factory(received.append)

    dispatcher.emit_event(flag_event("one"))
    dispatcher.emit_event(flag_event("two"))
    dispatcher.emit_event(flag_event("three"))

    assert dispatcher.flush(timeout=WAIT_TIMEOUT)
    assert [event.feature_name for event in received] == ["one", "two", "three"]


def test_every_event_type_reaches_the_callback(
    dispatcher_factory: Callable[..., EventDispatcher],
):
    received: list[UnleashEvent] = []
    dispatcher = dispatcher_factory(received.append)

    dispatcher.emit_event(ready_event())
    dispatcher.emit_event(fetched_event())
    dispatcher.emit_event(flag_event())
    dispatcher.emit_event(variant_event())

    assert dispatcher.flush(timeout=WAIT_TIMEOUT)
    assert [event.event_type for event in received] == [
        UnleashEventType.READY,
        UnleashEventType.FETCHED,
        UnleashEventType.FEATURE_FLAG,
        UnleashEventType.VARIANT,
    ]


def test_ready_event_is_emitted_at_most_once(
    dispatcher_factory: Callable[..., EventDispatcher],
):
    received: list[UnleashEvent] = []
    dispatcher = dispatcher_factory(received.append)

    thread_count = 8
    start_line = threading.Barrier(thread_count)

    def hammer():
        _ = start_line.wait(timeout=WAIT_TIMEOUT)
        for _ in range(50):
            dispatcher.emit_event(ready_event())

    threads = [threading.Thread(target=hammer) for _ in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=WAIT_TIMEOUT)

    assert dispatcher.flush(timeout=WAIT_TIMEOUT)
    assert len(received) == 1
    assert received[0].event_type is UnleashEventType.READY


def test_callback_exception_does_not_kill_the_worker(
    dispatcher_factory: Callable[..., EventDispatcher],
):
    received: list[UnleashEvent] = []

    def callback(event: UnleashEvent):
        if event.feature_name == "boom":
            raise ValueError("callback blew up")
        received.append(event)

    dispatcher = dispatcher_factory(callback)

    dispatcher.emit_event(flag_event("boom"))
    dispatcher.emit_event(flag_event("survivor"))

    assert dispatcher.flush(timeout=WAIT_TIMEOUT)
    assert [event.feature_name for event in received] == ["survivor"]


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


def test_flush_times_out_when_the_callback_hangs(
    dispatcher_factory: Callable[..., EventDispatcher],
):
    entered = threading.Event()
    release = threading.Event()

    def callback(event: UnleashEvent):
        entered.set()
        _ = release.wait(timeout=WAIT_TIMEOUT)

    dispatcher = dispatcher_factory(callback)

    dispatcher.emit_event(flag_event())
    assert entered.wait(timeout=WAIT_TIMEOUT)

    assert dispatcher.flush(timeout=0.2) is False

    release.set()


def test_flush_is_a_no_op_before_the_first_event(
    dispatcher_factory: Callable[..., EventDispatcher],
):
    dispatcher = dispatcher_factory(lambda event: None)

    assert dispatcher._thread is None
    assert dispatcher.flush(timeout=WAIT_TIMEOUT)

    dispatcher.emit_event(flag_event())

    assert dispatcher._thread is not None


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


def test_event_accepted_while_closing_is_still_delivered(
    dispatcher_factory: Callable[..., EventDispatcher],
):
    """
    This test is dense. What the test does is to manufacture the
    race condition between emit_event() and close(). In other words, the window between
    emit_event accepting an event and queueing it is nanoseconds
    wide, too narrow to hit by chance. The gate below widens it by freezing the
    emitter between those two steps.

    close() then runs on another thread while the emitter is frozen.  If it can take
    the lock, it queues its shutdown sentinel ahead of the event, the worker exits on
    the sentinel, and the event is never delivered.  Holding the lock across the whole
    enqueue blocks close() until the event is queued.
    """
    received: list[UnleashEvent] = []
    dispatcher = dispatcher_factory(received.append)

    dispatcher.emit_event(
        flag_event("warmup")
    )  # First emission lazily creates worked thread.
    assert dispatcher.flush(timeout=WAIT_TIMEOUT)

    inside_put = threading.Event()
    release = threading.Event()
    real_put_nowait = dispatcher._queue.put_nowait

    def gated_put_nowait(item):
        # emit_event has accepted the event but not queued it yet.
        inside_put.set()
        _ = release.wait(timeout=WAIT_TIMEOUT)
        real_put_nowait(item)

    dispatcher._queue.put_nowait = gated_put_nowait  # "manufacture" a slow "put_nowait"

    emitter = threading.Thread(target=lambda: dispatcher.emit_event(flag_event("racy")))
    emitter.start()
    assert inside_put.wait(timeout=WAIT_TIMEOUT)

    closer = threading.Thread(target=lambda: dispatcher.close(timeout=WAIT_TIMEOUT))
    closer.start()
    time.sleep(0.1)  # ample time for an unsynchronized close() to queue the sentinel

    release.set()
    emitter.join(timeout=WAIT_TIMEOUT)
    closer.join(timeout=WAIT_TIMEOUT)

    # assert that "racy" was not queued after _Shutdown
    assert [event.feature_name for event in received] == ["warmup", "racy"]


def test_flush_queued_behind_shutdown_is_released(
    dispatcher_factory: Callable[..., EventDispatcher],
):
    """
    [_SHUTDOWN, marker] is a genuinely reachable queue state during a concurrent close() + flush().

    This test exercises that case, ensuring that anyone waiting for marker to be released
    is not left hanging.

    A flush that raced close() and landed behind the sentinel must be woken when the
    worker exits, instead of blocking for its whole timeout.
    """
    entered = threading.Event()
    release = threading.Event()

    def callback(_event: UnleashEvent):
        entered.set()
        _ = release.wait(timeout=WAIT_TIMEOUT)

    dispatcher = dispatcher_factory(callback)

    dispatcher.emit_event(flag_event())
    assert entered.wait(timeout=WAIT_TIMEOUT)

    closer = threading.Thread(target=lambda: dispatcher.close(timeout=WAIT_TIMEOUT))
    closer.start()
    time.sleep(0.1)  # let the sentinel land behind the wedged event

    flushed: list[bool] = []
    flusher = threading.Thread(
        target=lambda: flushed.append(dispatcher.flush(timeout=WAIT_TIMEOUT))
    )
    flusher.start()
    time.sleep(0.1)  # ...and the flush marker land behind the sentinel

    release.set()
    flusher.join(timeout=WAIT_TIMEOUT)
    closer.join(timeout=WAIT_TIMEOUT)

    assert flushed == [True]
