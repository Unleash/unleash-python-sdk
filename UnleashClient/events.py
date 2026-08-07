import queue
import threading
import time
from dataclasses import dataclass
from enum import Enum
from json import loads
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

    __slots__ = ()

    def __repr__(self) -> str:
        return "<_SHUTDOWN>"


_SHUTDOWN = _Shutdown()


class _FlushMarker:
    """
    Sentinel that lets a caller wait until everything queued ahead of it has been delivered.
    """

    __slots__ = ("done",)

    def __init__(self) -> None:
        self.done = threading.Event()


_QueueItem = Union[BaseEvent, _Shutdown, _FlushMarker]

DEFAULT_MAX_QUEUE_SIZE = 100
DEFAULT_TIMEOUT = 2.0


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

    def emit_event(self, event: BaseEvent) -> None:
        """
        Queues an event for delivery.  Never blocks the caller.  READY events after
        the first one are ignored.

        The closed check and the enqueue happen under one lock, so an event that gets
        past the check is always queued ahead of a concurrent ``close``, never behind
        its shutdown sentinel where the worker would never see it.
        """
        with self._lock:
            if self._closed:
                return

            if event.event_type is UnleashEventType.READY:
                if self._ready_fired:
                    return
                self._ready_fired = True

            self._start_worker()

            try:
                self._queue.put_nowait(event)
                return
            except queue.Full:
                self._dropped += 1
                should_warn = not self._warned_about_full_queue
                self._warned_about_full_queue = True

        if should_warn:
            LOGGER.warning(
                "Unleash event queue is full, events are being dropped. This usually means the event callback is too slow."
            )
        else:
            LOGGER.debug("Event was dropped because queue is full.")

    def flush(self, timeout: float = DEFAULT_TIMEOUT) -> bool:
        """
        Blocks until every event queued so far has been handed to the callback.

        :return: True if the queue drained in time, False otherwise.
        """
        thread = self._thread
        if thread is None or not thread.is_alive():
            return True

        deadline = time.monotonic() + timeout
        marker = _FlushMarker()
        try:
            self._queue.put(marker, timeout=timeout)
        except queue.Full:
            return False

        return marker.done.wait(max(0.0, deadline - time.monotonic()))

    def close(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        """
        Stops the dispatcher.  Events already queued are delivered first, but only
        for as long as the timeout allows.  Calling this more than once is a no-op.
        """
        with self._lock:
            if self._closed:
                return
            self._closed = True
            thread = self._thread

        if thread is None:
            return

        deadline = time.monotonic() + timeout
        try:
            self._queue.put(_SHUTDOWN, timeout=timeout)
        except queue.Full:
            LOGGER.debug("Timed out signalling shutdown to the event dispatcher.")
            return

        thread.join(max(0.0, deadline - time.monotonic()))

    def _start_worker(self) -> None:
        """Starts a worker if one is not running.  Caller must hold ``self._lock``."""
        if self._thread is not None:
            return

        self._thread = threading.Thread(
            target=self._run, name="UnleashEventDispatcher", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        """_run is the inifinite loop that drains the queue of events.

        It blocks until an element is available."""
        while True:
            item = self._queue.get()

            if isinstance(item, _FlushMarker):
                item.done.set()
                continue

            if isinstance(item, _Shutdown):
                self._release_flush_markers()
                return

            try:
                self._callback(item)
            except Exception as exc:
                LOGGER.warning("Error in event callback: %s", exc)

    def _release_flush_markers(self) -> None:
        """
        Wakes anything that raced close() and landed behind the shutdown sentinel,
        rather than leaving it blocked for its full timeout.  Events found back there
        are discarded: close() only promises to deliver what was queued before it.
        """
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                return

            if isinstance(item, _FlushMarker):
                item.done.set()
