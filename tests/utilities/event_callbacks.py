"""
Callables and event builders for the EventDispatcher tests.

Every callback here records what it received, so a test can assert on delivery whichever
behavior it picked.  ``RecorderCallback.wait_for`` is how tests wait for the worker thread
"""

import threading
import time
import uuid
from typing import Callable, List, Optional

from UnleashClient.events import (
    BaseEvent,
    EventDispatcher,
    UnleashEvent,
    UnleashEventType,
    UnleashFetchedEvent,
    UnleashReadyEvent,
)

WAIT_TIMEOUT = 5
DISPATCHER_THREAD_NAME = "UnleashEventDispatcher"


class RecorderCallback:
    """
    Records every event it is handed, along with the thread it ran on.
    """

    def __init__(self) -> None:
        self._arrivals = threading.Condition()
        self._events: List[BaseEvent] = []
        self._threads: List[str] = []

    def __call__(self, event: BaseEvent) -> None:
        self.record(event)

    def record(self, event: BaseEvent) -> None:
        """Subclasses call this instead of ``super().__call__`` when they add behavior."""
        with self._arrivals:
            self._events.append(event)
            self._threads.append(threading.current_thread().name)
            self._arrivals.notify_all()

    @property
    def events(self) -> List[BaseEvent]:
        with self._arrivals:
            return list(self._events)

    @property
    def threads(self) -> List[str]:
        """Names of the threads the callback ran on, in arrival order."""
        with self._arrivals:
            return list(self._threads)

    @property
    def feature_names(self) -> List[str]:
        """Feature names in arrival order.  Events without one are skipped."""
        return [
            event.feature_name
            for event in self.events
            if isinstance(event, UnleashEvent)
        ]

    @property
    def call_count(self) -> int:
        with self._arrivals:
            return len(self._events)

    def wait_for(self, count: int, timeout: float = WAIT_TIMEOUT) -> bool:
        """Blocks until ``count`` events have arrived.  Returns False if they never do."""
        with self._arrivals:
            return self._arrivals.wait_for(
                lambda: len(self._events) >= count, timeout=timeout
            )


class RaisingCallback(RecorderCallback):
    """
    Records the event, then raises.  ``times`` caps how many of the first events blow up;
    by default every one does.
    """

    def __init__(
        self, error: Optional[Exception] = None, times: Optional[int] = None
    ) -> None:
        super().__init__()
        self.error = error if error is not None else RuntimeError("callback exploded")
        self._times = times

    def __call__(self, event: BaseEvent) -> None:
        self.record(event)
        if self._times is None or self.call_count <= self._times:
            raise self.error


class BlockingCallback(RecorderCallback):
    """
    Parks the worker inside the callback until ``release()``, then records.

    ``entered`` is set as soon as the worker reaches the callback, which is how a test knows the
    worker is pinned and the queue can be filled to a known depth.  Release is sticky: once
    released, later events pass straight through.
    """

    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self._released = threading.Event()

    def __call__(self, event: BaseEvent) -> None:
        self.entered.set()
        _ = self._released.wait(timeout=WAIT_TIMEOUT)
        self.record(event)

    def release(self) -> None:
        self._released.set()


class SlowCallback(RecorderCallback):
    """Spends ``delay`` seconds on every event."""

    def __init__(self, delay: float) -> None:
        super().__init__()
        self._delay = delay

    def __call__(self, event: BaseEvent) -> None:
        time.sleep(self._delay)
        self.record(event)


class ReentrantCallback(RecorderCallback):
    """
    Emits a follow-up event back into the dispatcher from inside the callback.

    ``build_event`` returns the follow-up, or None to stop.  Without a stopping condition the
    dispatcher would feed itself forever.

    With ``gated``, the follow-up is held back until ``release()``, which lets a test line the
    re-entrant emit up against work happening on another thread.  ``entered`` is set as soon as
    the worker reaches the callback; ``emitted`` is set once the follow-up emit returns.
    """

    def __init__(
        self,
        build_event: Callable[[BaseEvent], Optional[BaseEvent]],
        gated: bool = False,
    ) -> None:
        super().__init__()
        self._build_event = build_event
        self._dispatcher: Optional[EventDispatcher] = None
        self.entered = threading.Event()
        self.emitted = threading.Event()
        self._released = threading.Event()
        if not gated:
            self._released.set()

    def bind(self, dispatcher: EventDispatcher) -> None:
        self._dispatcher = dispatcher

    def release(self) -> None:
        self._released.set()

    def __call__(self, event: BaseEvent) -> None:
        self.record(event)
        self.entered.set()
        _ = self._released.wait(timeout=WAIT_TIMEOUT)

        follow_up = self._build_event(event)
        if follow_up is not None and self._dispatcher is not None:
            self._dispatcher.emit_event(follow_up)
            self.emitted.set()


class ClosingCallback(RecorderCallback):
    """
    Closes the dispatcher from inside the callback, i.e. from the worker thread itself.

    ``returned`` is set once close() is done, and ``error`` holds whatever it raised.
    """

    def __init__(self, timeout: float = 0.2) -> None:
        super().__init__()
        self._timeout = timeout
        self._dispatcher: Optional[EventDispatcher] = None
        self.returned = threading.Event()
        self.error: Optional[BaseException] = None

    def bind(self, dispatcher: EventDispatcher) -> None:
        self._dispatcher = dispatcher

    def __call__(self, event: BaseEvent) -> None:
        self.record(event)
        try:
            if self._dispatcher is not None:
                self._dispatcher.close(timeout=self._timeout)
        except BaseException as exc:
            self.error = exc
            raise
        finally:
            self.returned.set()


def flag_event(feature_name: str = "testFlag", enabled: bool = True) -> UnleashEvent:
    return UnleashEvent(
        event_type=UnleashEventType.FEATURE_FLAG,
        event_id=uuid.uuid4(),
        context={},
        enabled=enabled,
        feature_name=feature_name,
    )


def variant_event(
    feature_name: str = "testFlag", variant: str = "testVariant"
) -> UnleashEvent:
    return UnleashEvent(
        event_type=UnleashEventType.VARIANT,
        event_id=uuid.uuid4(),
        context={},
        enabled=True,
        feature_name=feature_name,
        variant=variant,
    )


def ready_event() -> UnleashReadyEvent:
    """The READY event the client actually emits."""
    return UnleashReadyEvent(
        event_type=UnleashEventType.READY,
        event_id=uuid.uuid4(),
    )


def ready_event_as_unleash_event() -> UnleashEvent:
    """READY carried on an UnleashEvent, the shape the dispatcher's dedupe guard matches."""
    return UnleashEvent(
        event_type=UnleashEventType.READY,
        event_id=uuid.uuid4(),
        context={},
        enabled=True,
        feature_name="",
    )


def fetched_event(raw_features: str = '{"features": []}') -> UnleashFetchedEvent:
    return UnleashFetchedEvent(
        event_type=UnleashEventType.FETCHED,
        event_id=uuid.uuid4(),
        raw_features=raw_features,
    )


def worker_threads() -> List[threading.Thread]:
    """Live dispatcher workers, found by the name the dispatcher gives its thread."""
    return [
        thread
        for thread in threading.enumerate()
        if thread.name == DISPATCHER_THREAD_NAME
    ]
