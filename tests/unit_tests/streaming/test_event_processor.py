from __future__ import annotations

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


def test_processor_hydrates_on_connected():
    engine = FakeEngine()
    processor = StreamingEventProcessor(engine)

    assert processor.hydrated is False

    payload = {"version": 1, "features": [], "segments": []}
    processor.process(FakeEvent("unleash-connected", payload))

    assert processor.hydrated is True
    assert engine.states == [payload]


def test_processor_applies_updates():
    engine = FakeEngine()
    processor = StreamingEventProcessor(engine)

    connected_payload = {"version": 1, "features": ["f1"], "segments": []}
    update_payload = {"version": 2, "features": ["f1", "f2"], "segments": []}

    processor.process(FakeEvent("unleash-connected", connected_payload))
    processor.process(FakeEvent("unleash-updated", update_payload))

    assert processor.hydrated is True
    assert engine.states == [connected_payload, update_payload]


def test_processor_ignores_unknown_event_types():
    engine = FakeEngine()
    processor = StreamingEventProcessor(engine)

    processor.process(FakeEvent("heartbeat", {}))
    processor.process(FakeEvent("message", {}))

    # No states should be applied
    assert engine.states == []
