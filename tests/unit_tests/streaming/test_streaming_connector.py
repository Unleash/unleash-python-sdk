from __future__ import annotations

import threading
import time
from typing import Iterable

from UnleashClient.streaming import StreamingConnector
from UnleashClient.streaming.event_processor import StreamingEventProcessor


class FakeEngine:
    def __init__(self):
        self.states = []

    def take_state(self, state):
        self.states.append(state)


class FakeEvent:
    def __init__(self, event: str, data):
        self.event = event
        self.data = data


class FiniteSSEClient:
    """SSE client that yields given events then stops."""

    def __init__(self, events: Iterable[FakeEvent]):
        self._events = list(events)
        self.closed = False

    @property
    def events(self):
        for e in self._events:
            if self.closed:
                break
            yield e

    def close(self):
        self.closed = True

    def interrupt(self):
        self.close()


class FailingSSEClient:
    """SSE client that fails immediately when iterating events."""

    def __init__(self):
        self.closed = False

    @property
    def events(self):
        raise ConnectionError("Simulated connection failure")

    def close(self):
        self.closed = True

    def interrupt(self):
        self.close()


def test_successful_connection_calls_ready():
    engine = FakeEngine()
    processor = StreamingEventProcessor(engine)

    ready_calls = {"n": 0}

    def on_ready():
        ready_calls["n"] += 1

    events = [
        FakeEvent("unleash-connected", {"version": 1, "features": [], "segments": []}),
        FakeEvent("unleash-updated", {"version": 2, "features": [], "segments": []}),
    ]

    controller = StreamingConnector(
        url="http://unleash.example",
        headers={},
        request_timeout=5,
        event_processor=processor,
        on_ready=on_ready,
        sse_client_factory=lambda url, headers, timeout: FiniteSSEClient(events),
    )

    th = threading.Thread(target=controller._run, daemon=True)
    th.start()
    time.sleep(0.05)
    controller.stop()
    th.join(timeout=1)

    assert engine.states  # at least one state applied
    assert ready_calls["n"] == 1


def test_connection_failures_trigger_retries():
    engine = FakeEngine()
    processor = StreamingEventProcessor(engine)

    attempts = []

    def factory(url, headers, timeout):
        attempts.append(time.time())
        return FailingSSEClient()

    controller = StreamingConnector(
        url="http://unleash.example",
        headers={},
        request_timeout=5,
        event_processor=processor,
        sse_client_factory=factory,
    )

    th = threading.Thread(target=controller._run, daemon=True)
    th.start()
    time.sleep(1.5)
    controller.stop()
    th.join(timeout=1)

    assert len(attempts) >= 1
