import queue
import threading
import time
from dataclasses import dataclass
from enum import Enum
from json import loads
from threading import Event
from typing import Callable, Optional, Union
from uuid import UUID

from UnleashClient.utils import LOGGER


class UnleashEventType(Enum):
    """
    Indicates what kind of event was triggered.
    """

    FEATURE_FLAG = "feature_flag"
    VARIANT = "variant"
    FETCHED = "fetched"
    READY = "ready"


@dataclass
class BaseEvent:
    """
    Base event type for all events in the Unleash client.
    """

    event_type: UnleashEventType
    event_id: UUID


@dataclass
class UnleashEvent(BaseEvent):
    """
    Dataclass capturing information from an Unleash feature flag or variant check.
    """

    context: dict
    enabled: bool
    feature_name: str
    variant: Optional[str] = ""


@dataclass
class UnleashReadyEvent(BaseEvent):
    """
    Event indicating that the Unleash client is ready.
    """

    pass


@dataclass
class UnleashFetchedEvent(BaseEvent):
    """
    Event indicating that the Unleash client has fetched feature flags.
    """

    raw_features: str

    @property
    def features(self) -> dict:
        if not hasattr(self, "_parsed_payload"):
            self._parsed_payload = loads(self.raw_features)["features"]
        return self._parsed_payload


class _Shutdown:
    """
    Sentinel that tells the worker to stop draining and exit.
    """

    def __init__(self):
        self.done: Event = threading.Event()

    def __repr__(self) -> str:
        return "<_SHUTDOWN>"


_QueueItem = Union[BaseEvent, _Shutdown]

DEFAULT_MAX_QUEUE_SIZE = 100
DEFAULT_TIMEOUT = 2.0
DEFAULT_PUT_TIMEOUT = 0.1


class EventDispatcher:
    """
    Delivers events to a user supplied callback on a dedicated background thread.

    ``emit_event`` only ever enqueues, so whoever emits an event is never blocked by
    a slow callback, and callback exceptions stay contained to the worker thread.
    Events are dropped, and counted, when the queue is saturated.

    Every event, READY included, is handed to the same callback.  READY is only ever
    delivered once, no matter how many connectors emit it or from which thread.

    :param callback: Function to hand events to.
    :param max_size: Maximum number of events to hold before dropping.
    """

    def __init__(
        self,
        callback: Callable[[BaseEvent], None],
        max_size: int = DEFAULT_MAX_QUEUE_SIZE,
    ) -> None:
        self._callback = callback
        self._queue: queue.Queue[_QueueItem] = queue.Queue(maxsize=max_size)
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._dropped = 0
        self._warned_about_full_queue = False
        self._ready_fired = False
        self._closed = False

    @property
    def dropped_events(self) -> int:
        """
        Number of events that were never handed to the callback because the queue
        was full.
        """
        with self._lock:
            return self._dropped

    def emit_event(
        self, event: BaseEvent, timeout: float = DEFAULT_PUT_TIMEOUT
    ) -> None:
        """
        Enqueues an event to be delivered to the callback.  If the queue is full, the
        event is dropped and counted.  If the dispatcher has been closed, the event is
        ignored.  This method is thread safe.

        The caller will wait for at most ``DEFAULT_PUT_TIMEOUT`` seconds to enqueue the event.
        """
        with self._lock:
            if self._closed:
                return

            try:
                self._start_worker()
                self._enqueue_event(event, timeout=timeout)
            except queue.Full:
                self._count_dropped_event()
                self._maybe_warn_about_full_queue()

    def close(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        """
        close() signals the dispatcher to stop. It enqueues a Shutdown sentinel to the queue, and waits
        for its signal to be set. The worker thread will eventually get to the sentinal, set its ``done``
        signal, which will wake this thread and allow it to join the worker thread.

        Even if the Shutdown sentinel cannot be enqueued, the worker thread will still be stopped and the dispatcher marked as closed.
        """
        with self._lock:
            if self._closed:
                return

            self._closed = True

            start_time = time.monotonic()
            try:
                if self._thread:
                    shutdown_signal = self._signal_shutdown(
                        timeout=_remaining(start_time, timeout)
                    )
                    _ = shutdown_signal.done.wait(
                        timeout=_remaining(start_time, timeout)
                    )
            except queue.Full:
                # Even if Shutdown could not be queued, we'll still stop the worker thread and mark as ``_closed``.
                # Not much we can do about it, but at least we won't leave the thread running.
                pass
            finally:
                self._stop_worker(timeout=_remaining(start_time, timeout))

    def _signal_shutdown(self, timeout: float) -> _Shutdown:
        """Signals the worker to stop draining and exit.  Caller must hold ``self._lock``."""
        signal = _Shutdown()
        self._enqueue_event(signal, timeout=timeout)
        return signal

    def _stop_worker(self, timeout: float) -> None:
        """Stops the worker thread.  Caller must hold ``self._lock``."""
        if self._thread is None:
            return

        if not self._thread.is_alive():
            self._thread = None
            return

        return self._thread.join(timeout=timeout)

    def _start_worker(self) -> None:
        """Starts a worker if one is not running.  Caller must hold ``self._lock``."""
        if self._thread is not None:
            return

        self._thread = threading.Thread(
            target=self._run, name="UnleashEventDispatcher", daemon=True
        )
        self._thread.start()

    def _enqueue_event(
        self, event: Union[BaseEvent, _Shutdown], timeout: float
    ) -> None:
        """Enqueues an event to be delivered to the callback.  If the queue is full, the
        event is dropped and counted.  If the dispatcher has been closed, the event is
        ignored.

        The caller will wait for at most ``timeout`` seconds to enqueue the event.
        Caller must hold ``self._lock``.
        """
        if (
            isinstance(event, UnleashEvent)
            and event.event_type is UnleashEventType.READY
        ):
            if self._ready_fired:
                return
            self._ready_fired = True

        self._queue.put(item=event, timeout=timeout)

    def _count_dropped_event(self) -> None:
        self._dropped += 1

    def _maybe_warn_about_full_queue(self) -> None:
        if not self._warned_about_full_queue:
            LOGGER.warning(
                "Unleash event queue is full, events are being dropped. This usually means the event callback is too slow."
            )
            self._warned_about_full_queue = True

    def _run(self) -> None:
        """_run is the inifinite loop that drains the queue of events.

        It blocks until an element is available."""
        while True:
            item: _QueueItem = self._queue.get()

            if isinstance(item, _Shutdown):
                item.done.set()
                return

            try:
                self._callback(item)
            except Exception as exc:
                LOGGER.warning("Error in event callback: %s", exc)


def _remaining(start_time: float, timeout: float) -> float:
    """Returns the remaining time until the timeout expires."""
    return max(0.0, timeout - (time.monotonic() - start_time))
