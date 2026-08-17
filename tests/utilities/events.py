import threading
import time
from threading import Condition, Event
from typing import List, Optional

from UnleashClient.events import BaseEvent, UnleashEventType

WAIT_TIMEOUT = 5


class EventRecorder:
    """
    An event callback that records everything the dispatcher delivers.

    Events now arrive on a background thread, so tests need something to wait on
    rather than asserting straight after the call that produced the event.
    """

    def __init__(self) -> None:
        self.events: List[BaseEvent] = []
        self.ready: Event = threading.Event()
        self.fetched: Event = threading.Event()
        self._condition: Condition = threading.Condition()

    def __call__(self, event: BaseEvent) -> None:
        with self._condition:
            self.events.append(event)
            self._condition.notify_all()

        if event.event_type == UnleashEventType.READY:
            self.ready.set()
        if event.event_type == UnleashEventType.FETCHED:
            self.fetched.set()

    def of_type(self, event_type: UnleashEventType) -> List[BaseEvent]:
        with self._condition:
            return [event for event in self.events if event.event_type == event_type]

    def wait_for(
        self,
        event_type: UnleashEventType,
        count: int = 1,
        timeout: float = WAIT_TIMEOUT,
    ) -> Optional[List[BaseEvent]]:
        """
        Blocks until ``count`` events of ``event_type`` have been delivered.

        :return: The matching events, or None if they didn't arrive in time.
        """
        deadline = time.monotonic() + timeout

        with self._condition:
            while len(self._matching(event_type)) < count:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self._condition.wait(remaining):
                    return None
            return self._matching(event_type)[:count]

    def _matching(self, event_type: UnleashEventType) -> List[BaseEvent]:
        return [event for event in self.events if event.event_type == event_type]


def wait_until(
    predicate, timeout: float = WAIT_TIMEOUT, interval: float = 0.05
) -> bool:
    """
    Polls ``predicate`` until it's true, for cases where there's no event to wait on.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())
