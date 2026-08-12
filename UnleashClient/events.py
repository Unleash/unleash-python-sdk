import queue
import threading
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


DEFAULT_MAX_QUEUE_SIZE = 100
DEFAULT_TIMEOUT = 2.0


class _ShutdownMarker:
    pass


_SHUTDOWN_WAKER: _ShutdownMarker = _ShutdownMarker()


class EventDispatcher:
    def __init__(
        self,
        callback: Callable[[BaseEvent], None],
        max_size: int = DEFAULT_MAX_QUEUE_SIZE,
    ) -> None:
        self._callback: Callable[[BaseEvent], None] = callback
        self._queue: queue.Queue[Union[_ShutdownMarker, BaseEvent]] = queue.Queue(
            maxsize=max_size
        )
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._closed = threading.Event()
        self._dropped = 0
        self._ready_delivered = False

    def emit_event(self, event: BaseEvent) -> None:
        with self._lock:
            if self._closed.is_set():
                return

            self._start_worker()

            is_ready_event = event.event_type == UnleashEventType.READY

            if is_ready_event and self._ready_delivered:
                return

            try:
                self._queue.put_nowait(event)
                if is_ready_event:
                    self._ready_delivered = True
            except queue.Full:
                self._dropped += 1
                should_warn = self._dropped == 1
            else:
                return

        if should_warn:
            LOGGER.warning("Unleash event queue is full; events are being dropped.")

    @property
    def dropped_events(self) -> int:
        with self._lock:
            return self._dropped

    def close(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        with self._lock:
            if self._closed.is_set():
                return

            self._closed.set()
            thread = self._thread

            if thread is None:
                return

            try:
                self._queue.put_nowait(_SHUTDOWN_WAKER)
            except queue.Full:
                pass

        if threading.current_thread() is not thread:
            thread.join(timeout)

    def _start_worker(self) -> None:
        if self._thread is not None:
            return

        self._thread = threading.Thread(
            target=self._run,
            name="UnleashEventDispatcher",
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        try:
            while True:
                item: Union[_ShutdownMarker, BaseEvent] = self._queue.get()

                if isinstance(item, _ShutdownMarker):
                    return

                try:
                    self._callback(item)
                except Exception:
                    LOGGER.exception("Error in event callback")

                if self._closed.is_set():
                    return
        finally:
            with self._lock:
                self._thread = None
