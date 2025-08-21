from __future__ import annotations

import json
import time

import pytest

from UnleashClient import INSTANCES, UnleashClient


@pytest.fixture(autouse=True)
def reset_instances():
    INSTANCES._reset()


class FakeEvent:
    def __init__(self, event: str, data):
        self.event = event
        self.data = data


class FiniteSSEClient:
    """SSE client that yields given events then stops."""

    def __init__(self, events):
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


def _state_with_feature(name: str) -> str:
    payload = {
        "version": 1,
        "features": [
            {"name": name, "enabled": True, "strategies": [{"name": "default"}]}
        ],
        "segments": [],
    }
    return json.dumps(payload)


def test_streaming_processes_unleash_connected_event():
    captured = {}

    def factory(url, headers, timeout):
        captured["url"] = url
        captured["headers"] = headers
        return FiniteSSEClient(
            [FakeEvent("unleash-connected", _state_with_feature("test-feature"))]
        )

    client = UnleashClient(
        url="http://unleash.example",
        app_name="my-test-app",
        instance_id="rspec/test",
        disable_metrics=True,
        disable_registration=True,
        custom_headers={"X-API-KEY": "123"},
        experimental_mode={"type": "streaming"},
        sse_client_factory=factory,
    )

    try:
        client.initialize_client()
        time.sleep(0.05)

        assert captured["url"].endswith("/client/streaming")
        assert captured["headers"]["X-API-KEY"] == "123"

        assert client.is_enabled("test-feature") is True
    finally:
        client.destroy()


def test_streaming_processes_unleash_updated_event():
    captured = {}

    def factory(url, headers, timeout):
        captured["url"] = url
        captured["headers"] = headers
        empty_state = json.dumps({"version": 1, "features": [], "segments": []})
        update_state = _state_with_feature("test-feature")
        return FiniteSSEClient(
            [
                FakeEvent("unleash-connected", empty_state),
                FakeEvent("unleash-updated", update_state),
            ]
        )

    client = UnleashClient(
        url="http://unleash.example",
        app_name="my-test-app",
        instance_id="rspec/test",
        disable_metrics=True,
        disable_registration=True,
        custom_headers={"X-API-KEY": "123"},
        experimental_mode={"type": "streaming"},
        sse_client_factory=factory,
    )

    try:
        client.initialize_client()
        time.sleep(0.05)

        assert captured["url"].endswith("/client/streaming")
        assert captured["headers"]["X-API-KEY"] == "123"

        assert client.is_enabled("test-feature") is True
    finally:
        client.destroy()
