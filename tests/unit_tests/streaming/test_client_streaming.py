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


def _state_with_feature(name: str) -> str:
    payload = {
        "version": 1,
        "features": [
            {"name": name, "enabled": True, "strategies": [{"name": "default"}]}
        ],
        "segments": [],
    }
    return json.dumps(payload)


def test_streaming_processes_unleash_connected_event(monkeypatch):
    captured = {}

    def fake_http(url, headers=None, urllib3_request_options=None):
        captured["url"] = url
        captured["headers"] = headers or {}
        return {"url": url, "headers": headers}

    monkeypatch.setattr(
        "UnleashClient.connectors.streaming_connector.ConnectStrategy.http",
        staticmethod(fake_http),
    )

    class FakeSSEClient:
        def __init__(self, **kwargs):
            self._events = [
                FakeEvent("unleash-connected", _state_with_feature("test-feature"))
            ]
            self.closed = False

        @property
        def events(self):
            for e in self._events:
                if self.closed:
                    break
                yield e

        def close(self):
            self.closed = True

    monkeypatch.setattr(
        "UnleashClient.connectors.streaming_connector.SSEClient", FakeSSEClient
    )

    client = UnleashClient(
        url="http://unleash.example",
        app_name="my-test-app",
        instance_id="rspec/test",
        disable_metrics=True,
        disable_registration=True,
        custom_headers={"X-API-KEY": "123"},
        experimental_mode="streaming",
    )

    try:
        client.initialize_client()
        time.sleep(0.05)

        assert captured["url"].endswith("/client/streaming")
        assert captured["headers"]["X-API-KEY"] == "123"

        assert client.is_enabled("test-feature") is True
    finally:
        client.destroy()


def test_streaming_processes_unleash_updated_event(monkeypatch):
    captured = {}

    def fake_http(url, headers=None, urllib3_request_options=None):
        captured["url"] = url
        captured["headers"] = headers or {}
        return {"url": url, "headers": headers}

    monkeypatch.setattr(
        "UnleashClient.connectors.streaming_connector.ConnectStrategy.http",
        staticmethod(fake_http),
    )

    empty_state = json.dumps({"version": 1, "features": [], "segments": []})
    update_state = _state_with_feature("test-feature")

    class FakeSSEClient:
        def __init__(self, **kwargs):
            self._events = [
                FakeEvent("unleash-connected", empty_state),
                FakeEvent("unleash-updated", update_state),
            ]
            self.closed = False

        @property
        def events(self):
            for e in self._events:
                if self.closed:
                    break
                yield e

        def close(self):
            self.closed = True

    monkeypatch.setattr(
        "UnleashClient.connectors.streaming_connector.SSEClient", FakeSSEClient
    )

    client = UnleashClient(
        url="http://unleash.example",
        app_name="my-test-app",
        instance_id="rspec/test",
        disable_metrics=True,
        disable_registration=True,
        custom_headers={"X-API-KEY": "123"},
        experimental_mode="streaming",
    )

    try:
        client.initialize_client()
        time.sleep(0.05)

        assert captured["url"].endswith("/client/streaming")
        assert captured["headers"]["X-API-KEY"] == "123"

        assert client.is_enabled("test-feature") is True
    finally:
        client.destroy()
