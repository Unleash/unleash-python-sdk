import logging
import threading
import time
from typing import Callable, Iterator, List, Tuple

import pytest

from tests.utilities.event_callbacks import (
    DISPATCHER_THREAD_NAME,
    WAIT_TIMEOUT,
    BlockingCallback,
    ClosingCallback,
    RaisingCallback,
    RecorderCallback,
    SlowCallback,
    fetched_event,
    flag_event,
    ready_event,
    ready_event_as_unleash_event,
    variant_event,
    worker_threads,
)
from UnleashClient.events import (
    BaseEvent,
    EventDispatcher,
    UnleashEventType,
)

# close() waits on Thread.join, whose granularity is a few milliseconds.  Slack on top of the
# timeout close() was given, so "returned when it said it would" can't be read as "waited longer".
CLOSE_SLACK = 0.05

# Timeout handed to close() when a test needs to tell "returned as soon as the worker let go"
# apart from "waited out the whole timeout".
CLOSE_TIMEOUT = 2.0


def sdk_logs(caplog: pytest.LogCaptureFixture, level: int) -> List[str]:
    """Messages the SDK logged at ``level``, traceback included, in the order it logged them."""
    formatter = logging.Formatter("%(message)s")
    return [
        formatter.format(record)
        for record in caplog.records
        if record.name == "UnleashClient" and record.levelno == level
    ]


def sdk_warnings(caplog: pytest.LogCaptureFixture) -> List[str]:
    """Messages the SDK logged at WARNING, in the order it logged them."""
    return sdk_logs(caplog, logging.WARNING)


def ready_deliveries(callback: RecorderCallback) -> List[BaseEvent]:
    """READY events that reached the callback, in arrival order."""
    return [
        event for event in callback.events if event.event_type is UnleashEventType.READY
    ]


@pytest.fixture()
def dispatcher_factory() -> Iterator[Callable[..., EventDispatcher]]:
    """
    Builds dispatchers and guarantees they're torn down, so a wedged worker thread
    can't leak into the next test.

    Blocking callbacks are released before the close: a test that fails before its own
    release() would otherwise leave the worker parked inside the callback.
    """
    created: List[Tuple[object, EventDispatcher]] = []

    def _build(callback, *args, **kwargs) -> EventDispatcher:
        dispatcher = EventDispatcher(callback, *args, **kwargs)
        created.append((callback, dispatcher))
        return dispatcher

    yield _build

    for callback, dispatcher in created:
        release = getattr(callback, "release", None)
        if callable(release):
            release()
        dispatcher.close(timeout=1)


class TestDelivery:
    def test_an_emitted_event_reaches_the_callback(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        callback = RecorderCallback()
        dispatcher = dispatcher_factory(callback)

        dispatcher.emit_event(flag_event("testFlag"))

        assert callback.wait_for(1)
        assert callback.feature_names == ["testFlag"]

    def test_the_callback_is_handed_the_event_that_was_emitted(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        callback = RecorderCallback()
        dispatcher = dispatcher_factory(callback)
        event = flag_event()

        dispatcher.emit_event(event)

        assert callback.wait_for(1)
        assert callback.events[0] is event

    def test_events_arrive_in_the_order_they_were_emitted(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        callback = RecorderCallback()
        dispatcher = dispatcher_factory(callback)

        for index in range(20):
            dispatcher.emit_event(flag_event(str(index)))

        assert callback.wait_for(20)
        assert callback.feature_names == [str(index) for index in range(20)]

    def test_every_kind_of_event_goes_to_the_same_callback(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        callback = RecorderCallback()
        dispatcher = dispatcher_factory(callback)
        emitted = [flag_event(), variant_event(), ready_event(), fetched_event()]

        for event in emitted:
            dispatcher.emit_event(event)

        assert callback.wait_for(len(emitted))
        assert callback.events == emitted

    def test_emitting_does_not_wait_for_the_callback(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        callback = BlockingCallback()
        dispatcher = dispatcher_factory(callback)

        dispatcher.emit_event(flag_event("pins the worker"))
        assert callback.entered.wait(timeout=WAIT_TIMEOUT)

        dispatcher.emit_event(flag_event("queued behind it"))

        # Control is back here, so the emit did not wait on the callback.
        assert callback.call_count == 0  # still parked inside the first event
        assert dispatcher.dropped_events == 0  # in the queue, not on the floor

    def test_the_emitter_does_not_wait_for_the_whole_callback_duration(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        callback: SlowCallback = SlowCallback(delay=0.05)
        dispatcher: EventDispatcher = dispatcher_factory(callback)

        for _ in range(20):
            dispatcher.emit_event(flag_event())

        assert (
            callback.call_count < 20
        )  # If emitter had waited for the callback, this would be exactly 20.

    def test_emitter_does_not_drop_events_despite_slow_callback(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        callback: SlowCallback = SlowCallback(delay=0.05)
        dispatcher: EventDispatcher = dispatcher_factory(callback)

        for _ in range(20):
            dispatcher.emit_event(flag_event())

        assert dispatcher.dropped_events == 0

    def test_emitter_eventually_processes_all_events_despite_slow_callback(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        callback: SlowCallback = SlowCallback(delay=0.05)
        dispatcher: EventDispatcher = dispatcher_factory(callback)

        for _ in range(20):
            dispatcher.emit_event(flag_event())

        assert callback.wait_for(20)


class TestWorkerLifecycle:
    def test_no_worker_runs_until_the_first_event(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        before = len(worker_threads())
        dispatcher = dispatcher_factory(RecorderCallback())

        assert len(worker_threads()) == before

        dispatcher.emit_event(flag_event())

        assert len(worker_threads()) == before + 1

    def test_one_worker_serves_every_event(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        callback = RecorderCallback()
        dispatcher = dispatcher_factory(callback)
        before = len(worker_threads())

        for _ in range(10):
            dispatcher.emit_event(flag_event())

        assert callback.wait_for(10)
        assert len(worker_threads()) == before + 1

    def test_the_callback_never_runs_on_the_emitting_thread(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        callback = RecorderCallback()
        dispatcher = dispatcher_factory(callback)

        dispatcher.emit_event(flag_event())

        assert callback.wait_for(1)
        assert callback.threads == [DISPATCHER_THREAD_NAME]
        assert threading.current_thread().name != DISPATCHER_THREAD_NAME

    def test_the_worker_is_a_daemon_thread(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        dispatcher = dispatcher_factory(RecorderCallback())
        before = set(worker_threads())

        dispatcher.emit_event(flag_event())

        (worker,) = set(worker_threads()) - before
        assert worker.daemon is True

    def test_close_leaves_no_worker_behind(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        dispatcher = dispatcher_factory(RecorderCallback())
        before = set(worker_threads())
        dispatcher.emit_event(flag_event())
        (worker,) = set(worker_threads()) - before

        dispatcher.close(timeout=WAIT_TIMEOUT)

        assert not worker.is_alive()

    def test_a_raising_callback_does_not_kill_the_worker(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        callback = RaisingCallback(times=1)
        dispatcher = dispatcher_factory(callback)

        dispatcher.emit_event(flag_event("explodes"))
        dispatcher.emit_event(flag_event("survives"))

        assert callback.wait_for(2)
        assert callback.feature_names == ["explodes", "survives"]

    def test_the_worker_outlives_a_callback_that_always_raises(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        callback = RaisingCallback()
        dispatcher = dispatcher_factory(callback)

        for index in range(50):
            dispatcher.emit_event(flag_event(str(index)))

        assert callback.wait_for(50)
        assert callback.feature_names == [str(index) for index in range(50)]

    def test_a_callback_exception_never_reaches_the_emitter(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        callback = RaisingCallback()
        dispatcher = dispatcher_factory(callback)

        dispatcher.emit_event(flag_event())

        assert callback.wait_for(1)
        dispatcher.close(timeout=WAIT_TIMEOUT)


class TestBackpressure:
    """
    Every test here pins the worker inside a BlockingCallback first.  Once ``entered`` is set the
    worker has taken its event off the queue and gone to sleep, so the queue is empty and its
    depth from then on is exactly what the test put there.

    An emit never waits for room: it either finds a free slot or drops the event and counts it.
    """

    def test_no_events_are_dropped_before_anything_is_emitted(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        dispatcher = dispatcher_factory(RecorderCallback())

        assert dispatcher.dropped_events == 0

    def test_nothing_is_dropped_when_the_callback_keeps_up(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        callback = RecorderCallback()
        dispatcher = dispatcher_factory(callback, max_size=100)

        for index in range(50):
            dispatcher.emit_event(flag_event(str(index)))

        assert callback.wait_for(50)
        assert dispatcher.dropped_events == 0

    def test_events_beyond_capacity_are_dropped(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        callback = BlockingCallback()
        dispatcher = dispatcher_factory(callback, max_size=3)

        dispatcher.emit_event(flag_event("pins the worker"))
        assert callback.entered.wait(timeout=WAIT_TIMEOUT)

        for index in range(10):
            dispatcher.emit_event(flag_event(str(index)))

        # Three fit in the queue; the other seven have nowhere to go.
        assert dispatcher.dropped_events == 7

    def test_dropped_events_are_never_delivered(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        callback = BlockingCallback()
        dispatcher = dispatcher_factory(callback, max_size=2)

        dispatcher.emit_event(flag_event("pins the worker"))
        assert callback.entered.wait(timeout=WAIT_TIMEOUT)
        for index in range(10):
            dispatcher.emit_event(flag_event(str(index)))

        callback.release()
        assert callback.wait_for(3)

        assert dispatcher.dropped_events == 8
        assert callback.feature_names == ["pins the worker", "0", "1"]

        dispatcher.close(timeout=WAIT_TIMEOUT)

    def test_the_queue_takes_events_again_once_the_callback_drains(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        callback = BlockingCallback()
        dispatcher = dispatcher_factory(callback, max_size=2)

        dispatcher.emit_event(flag_event("pins the worker"))
        assert callback.entered.wait(timeout=WAIT_TIMEOUT)
        for index in range(5):
            dispatcher.emit_event(flag_event(str(index)))

        assert dispatcher.dropped_events == 3

        callback.release()
        assert callback.wait_for(3)

        # The queue is empty again, so it can take another max_size events.
        for index in range(2):
            dispatcher.emit_event(flag_event("after"))

        assert callback.wait_for(5)
        assert dispatcher.dropped_events == 3

    def test_a_max_size_of_zero_means_an_unbounded_queue(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        callback = BlockingCallback()
        dispatcher = dispatcher_factory(callback, max_size=0)

        dispatcher.emit_event(flag_event("pins the worker"))
        assert callback.entered.wait(timeout=WAIT_TIMEOUT)

        # Nothing is draining and no emit will wait, so any bounded queue would drop.
        for index in range(200):
            dispatcher.emit_event(flag_event(str(index)))

        assert dispatcher.dropped_events == 0

    def test_the_drop_count_survives_close(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        callback = BlockingCallback()
        dispatcher = dispatcher_factory(callback, max_size=1)

        dispatcher.emit_event(flag_event("pins the worker"))
        assert callback.entered.wait(timeout=WAIT_TIMEOUT)
        dispatcher.emit_event(flag_event("fills the queue"))
        dispatcher.emit_event(flag_event("dropped"))
        assert dispatcher.dropped_events == 1

        callback.release()
        dispatcher.close(timeout=WAIT_TIMEOUT)

        assert dispatcher.dropped_events == 1


class TestReadyDeduplication:
    """
    The dispatcher promises READY is delivered once, however many connectors emit it.

    A second READY arriving is what these tests wait for: it either shows up, and the dedup guard
    is missing, or the wait times out because there was only ever one.  close() cannot be the
    synchronization point any more, because it no longer drains what is still queued.
    """

    def test_ready_is_delivered_once_however_many_connectors_emit_it(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        callback = RecorderCallback()
        dispatcher = dispatcher_factory(callback)

        # The shape build_ready_callback emits, which is what connectors actually hand over.
        for _ in range(3):
            dispatcher.emit_event(ready_event())

        assert callback.wait_for(1)
        assert not callback.wait_for(2, timeout=0.2)
        assert len(ready_deliveries(callback)) == 1

    def test_ready_carried_on_an_unleash_event_is_deduplicated(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        callback = RecorderCallback()
        dispatcher = dispatcher_factory(callback)

        for _ in range(3):
            dispatcher.emit_event(ready_event_as_unleash_event())

        assert callback.wait_for(1)
        assert not callback.wait_for(2, timeout=0.2)
        assert len(ready_deliveries(callback)) == 1

    def test_a_ready_event_dropped_by_a_full_queue_is_still_delivered_later(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        callback = BlockingCallback()
        dispatcher = dispatcher_factory(callback, max_size=1)

        dispatcher.emit_event(flag_event("pins the worker"))
        assert callback.entered.wait(timeout=WAIT_TIMEOUT)
        dispatcher.emit_event(flag_event("fills the queue"))

        # Nowhere to put it, so this READY never reaches the callback.
        dispatcher.emit_event(ready_event_as_unleash_event())
        assert dispatcher.dropped_events == 1

        callback.release()
        assert callback.wait_for(2)

        # The queue has drained, and this emit can be retried normally.
        dispatcher.emit_event(ready_event_as_unleash_event())
        assert callback.wait_for(3)

        assert ready_deliveries(callback), (
            "READY was dropped while the queue was full, and every later attempt was "
            "suppressed, so it was never delivered at all"
        )


class TestFullQueueWarning:
    def _drop_events(
        self, dispatcher_factory: Callable[..., EventDispatcher], count: int
    ) -> EventDispatcher:
        """Pins the worker, fills a one-slot queue, then drops ``count`` events on the floor."""
        callback = BlockingCallback()
        dispatcher = dispatcher_factory(callback, max_size=1)

        dispatcher.emit_event(flag_event("pins the worker"))
        assert callback.entered.wait(timeout=WAIT_TIMEOUT)
        dispatcher.emit_event(flag_event("fills the queue"))
        for index in range(count):
            dispatcher.emit_event(
                flag_event(str(index)),
            )

        assert dispatcher.dropped_events == count
        return dispatcher

    def test_a_full_queue_is_warned_about(
        self,
        dispatcher_factory: Callable[..., EventDispatcher],
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.WARNING, logger="UnleashClient")

        self._drop_events(dispatcher_factory, count=1)

        assert [
            message for message in sdk_warnings(caplog) if "queue is full" in message
        ]

    def test_a_full_queue_is_warned_about_only_once(  # line 443
        self,
        dispatcher_factory: Callable[..., EventDispatcher],
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.WARNING, logger="UnleashClient")

        self._drop_events(dispatcher_factory, count=5)

        # One warning about a saturated queue, not one per dropped event.
        warnings = [
            message for message in sdk_warnings(caplog) if "queue is full" in message
        ]
        assert len(warnings) == 1


class TestCallbackErrorLogging:
    def test_a_callback_exception_is_logged_with_its_message(
        self,
        dispatcher_factory: Callable[..., EventDispatcher],
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.ERROR, logger="UnleashClient")
        callback = RaisingCallback(error=RuntimeError("kaboom"))
        dispatcher = dispatcher_factory(callback)

        dispatcher.emit_event(flag_event())

        assert callback.wait_for(1)
        dispatcher.close(
            timeout=WAIT_TIMEOUT
        )  # the log lands after the callback returns
        assert any(
            "Error in event callback" in message and "kaboom" in message
            for message in sdk_logs(caplog, logging.ERROR)
        )

    def test_every_failing_event_is_logged(
        self,
        dispatcher_factory: Callable[..., EventDispatcher],
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.ERROR, logger="UnleashClient")
        callback = RaisingCallback()
        dispatcher = dispatcher_factory(callback)

        for index in range(3):
            dispatcher.emit_event(flag_event(str(index)))

        assert callback.wait_for(3)
        dispatcher.close(timeout=WAIT_TIMEOUT)
        failures = [
            message
            for message in sdk_logs(caplog, logging.ERROR)
            if "Error in event callback" in message
        ]
        assert len(failures) == 3

    def test_a_clean_run_logs_nothing(
        self,
        dispatcher_factory: Callable[..., EventDispatcher],
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.WARNING, logger="UnleashClient")
        callback = RecorderCallback()
        dispatcher = dispatcher_factory(callback)

        for index in range(10):
            dispatcher.emit_event(flag_event(str(index)))

        assert callback.wait_for(10)
        dispatcher.close(timeout=WAIT_TIMEOUT)
        assert sdk_warnings(caplog) == []
        assert sdk_logs(caplog, logging.ERROR) == []


class TestClose:
    def test_close_drops_events_that_are_still_queued(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        callback = BlockingCallback()
        dispatcher = dispatcher_factory(callback)

        dispatcher.emit_event(flag_event("in flight"))
        assert callback.entered.wait(timeout=WAIT_TIMEOUT)
        for index in range(10):
            dispatcher.emit_event(flag_event(str(index)))

        # The worker is only let go once close() has run, so it finishes the event it is on and
        # stops there rather than working through the ten behind it.
        unblock = threading.Timer(0.1, callback.release)
        unblock.start()
        dispatcher.close(timeout=WAIT_TIMEOUT)
        unblock.join()

        assert callback.feature_names == ["in flight"]

    def test_close_is_idempotent(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        callback = RecorderCallback()
        dispatcher = dispatcher_factory(callback)

        dispatcher.emit_event(flag_event())
        dispatcher.close(timeout=WAIT_TIMEOUT)
        dispatcher.close(timeout=WAIT_TIMEOUT)
        dispatcher.close(timeout=WAIT_TIMEOUT)

        assert callback.call_count == 1

    def test_a_second_close_returns_immediately(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        dispatcher = dispatcher_factory(RecorderCallback())
        dispatcher.emit_event(flag_event())
        dispatcher.close(timeout=WAIT_TIMEOUT)

        start = time.monotonic()
        dispatcher.close(timeout=WAIT_TIMEOUT)
        elapsed = time.monotonic() - start

        # Already closed: there is nothing left to wait for, so no timeout is paid.
        assert elapsed < CLOSE_SLACK

    def test_close_honors_a_zero_timeout(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        callback = BlockingCallback()
        dispatcher = dispatcher_factory(callback)

        dispatcher.emit_event(flag_event("pins the worker"))
        assert callback.entered.wait(timeout=WAIT_TIMEOUT)

        start = time.monotonic()
        dispatcher.close(timeout=0)
        elapsed = time.monotonic() - start

        assert elapsed < CLOSE_SLACK

    def test_close_returns_promptly_when_nothing_was_ever_emitted(  # line 594
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        dispatcher = dispatcher_factory(RecorderCallback())

        start = time.monotonic()
        dispatcher.close()  # the default timeout, which is what callers get
        elapsed = time.monotonic() - start

        # No event was ever emitted, so no worker was ever started and there is nothing
        # for close() to wait on.
        assert elapsed < CLOSE_SLACK

    def test_emit_after_close_is_a_no_op(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        callback = RecorderCallback()
        dispatcher = dispatcher_factory(callback)

        dispatcher.emit_event(flag_event("before"))
        dispatcher.close(timeout=WAIT_TIMEOUT)
        for event in (
            flag_event("after"),
            variant_event(),
            ready_event(),
            fetched_event(),
        ):
            dispatcher.emit_event(event)

        assert not callback.wait_for(2, timeout=0.2)
        assert callback.feature_names == ["before"]

    def test_emit_after_close_starts_no_worker(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        dispatcher = dispatcher_factory(RecorderCallback())
        dispatcher.close(timeout=0)
        before = len(worker_threads())

        dispatcher.emit_event(flag_event())

        assert len(worker_threads()) == before

    def test_closing_from_inside_the_callback_does_not_blow_up(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        callback = ClosingCallback(timeout=CLOSE_TIMEOUT)
        dispatcher = dispatcher_factory(callback)
        callback.bind(dispatcher)

        dispatcher.emit_event(flag_event())

        # The worker closing the dispatcher would be joining itself, which raises.
        assert callback.returned.wait(timeout=WAIT_TIMEOUT)
        assert callback.error is None

    def test_two_threads_closing_at_once_both_return(
        self, dispatcher_factory: Callable[..., EventDispatcher]
    ):
        callback = RecorderCallback()
        dispatcher = dispatcher_factory(callback)
        dispatcher.emit_event(flag_event())
        returned: List[str] = []

        def close_it() -> None:
            dispatcher.close(timeout=WAIT_TIMEOUT)
            returned.append(threading.current_thread().name)

        closers = [
            threading.Thread(target=close_it, name="closer-{}".format(index))
            for index in range(2)
        ]
        for closer in closers:
            closer.start()
        for closer in closers:
            closer.join(timeout=WAIT_TIMEOUT)

        assert [closer.is_alive() for closer in closers] == [False, False]
        assert sorted(returned) == ["closer-0", "closer-1"]
        assert callback.call_count == 1
