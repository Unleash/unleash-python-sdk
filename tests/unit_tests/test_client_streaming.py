"""
Unit tests for streaming connector using urllib3 mocking for low-level HTTP interception.
"""

import json
import threading
import time
from io import BytesIO

import pytest
import urllib3

from UnleashClient import INSTANCES, UnleashClient


def cleanup_threads():
    """Wait for all background threads to finish."""
    for thread in threading.enumerate():
        if thread != threading.current_thread() and thread.is_alive():
            if (
                hasattr(thread, "_stop")
                or "unleash" in thread.name.lower()
                or "scheduler" in thread.name.lower()
            ):
                try:
                    thread.join(timeout=2.0)
                except Exception:
                    pass


@pytest.fixture(autouse=True)
def reset_instances():
    """Reset instances before each test."""
    INSTANCES._reset()
    yield
    cleanup_threads()


def create_sse_stream() -> bytes:
    """Generate SSE stream with feature data."""
    initial_data = {
        "version": 1,
        "features": [
            {
                "name": "test-feature",
                "enabled": True,
                "strategies": [{"name": "default", "parameters": {}}],
            },
            {
                "name": "another-feature",
                "enabled": False,
                "strategies": [{"name": "default", "parameters": {}}],
            },
        ],
    }

    stream_data = f"event: unleash-connected\ndata: {json.dumps(initial_data)}\n\n"

    update_data = {
        "type": "feature-updated",
        "feature": {
            "name": "test-feature",
            "enabled": False,
            "strategies": [{"name": "default", "parameters": {}}],
        },
    }

    stream_data += f"event: feature-updated\ndata: {json.dumps(update_data)}\n\n"

    return stream_data.encode("utf-8")


class MockHTTPResponse:
    """Mock urllib3 for SSE streaming."""

    def __init__(self, data: bytes, status: int = 200, headers=None):
        self.data = BytesIO(data)
        self.status = status
        self.headers = headers or {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
        self._closed = False

    def read(self, amt=None):
        """Read data from the stream."""
        if self._closed:
            return b""
        return self.data.read(amt)

    def readline(self):
        """Read a line from the stream."""
        if self._closed:
            return b""
        return self.data.readline()

    def readlines(self):
        """Read all lines from the stream."""
        if self._closed:
            return []
        return self.data.readlines()

    def stream(self, amt=1024, decode_content=None):
        """Stream data in chunks."""
        if self._closed:
            return
        while True:
            chunk = self.data.read(amt)
            if not chunk:
                break
            yield chunk

    def close(self):
        """Close the response."""
        self._closed = True
        self.data.close()

    def isclosed(self):
        """Check if response is closed."""
        return self._closed

    def get_redirect_location(self):
        """Get redirect location."""
        return None


def test_client_streaming_hydration(monkeypatch):
    """Test streaming connector using urllib3 mocking."""

    mock_calls = []

    def mock_urlopen(self, method, url, body=None, headers=None, **kwargs):
        """Mock urllib3.PoolManager.urlopen method."""
        mock_calls.append(
            {"method": method, "url": url, "headers": headers, "body": body}
        )

        if "/streaming" in url:
            sse_data = create_sse_stream()
            return MockHTTPResponse(sse_data, status=200)
        elif "/register" in url:
            response_data = json.dumps({"status": "ok"}).encode("utf-8")
            return MockHTTPResponse(
                response_data, status=200, headers={"Content-Type": "application/json"}
            )
        elif "/metrics" in url:
            response_data = json.dumps({"status": "ok"}).encode("utf-8")
            return MockHTTPResponse(
                response_data, status=200, headers={"Content-Type": "application/json"}
            )
        else:
            return MockHTTPResponse(b'{"status": "ok"}', status=200)

    monkeypatch.setattr(urllib3.PoolManager, "urlopen", mock_urlopen)

    client = UnleashClient(
        url="http://localhost:4242",
        app_name="test-app",
        instance_id="test-instance",
        disable_metrics=True,
        disable_registration=True,
        experimental_mode="streaming",
    )

    try:
        client.initialize_client()

        streaming_calls = [call for call in mock_calls if "/streaming" in call["url"]]
        assert (
            len(streaming_calls) >= 1
        ), f"Should have called streaming endpoint. All calls: {[call['url'] for call in mock_calls]}"

        result = client.is_enabled("test-feature")

        assert result is True, "Feature should be enabled based on mock data"

    finally:
        client.destroy()


def test_client_streaming_retry(monkeypatch):
    """Test streaming connector retry behavior using urllib3 mocking."""

    mock_calls = []
    call_count = 0

    def mock_urlopen_with_retry(self, method, url, body=None, headers=None, **kwargs):
        """Mock urllib3 that fails first few times then succeeds."""
        nonlocal call_count
        call_count += 1

        mock_calls.append(
            {"method": method, "url": url, "headers": headers, "attempt": call_count}
        )

        if "/streaming" in url:
            if call_count <= 2:
                # Fail first 2 attempts, succeed on 3rd attempt
                raise urllib3.exceptions.ConnectTimeoutError(
                    pool=None, url=url, message="Connection timeout"
                )
            else:
                sse_data = create_sse_stream()
                return MockHTTPResponse(sse_data, status=200)
        else:
            response_data = json.dumps({"status": "ok"}).encode("utf-8")
            return MockHTTPResponse(response_data, status=200)

    monkeypatch.setattr(urllib3.PoolManager, "urlopen", mock_urlopen_with_retry)

    client = UnleashClient(
        url="http://localhost:4242",
        app_name="test-app",
        instance_id="test-instance",
        disable_metrics=True,
        disable_registration=True,
        experimental_mode="streaming",
    )

    try:
        client.initialize_client()
        time.sleep(3.0)

        streaming_calls = [call for call in mock_calls if "/streaming" in call["url"]]

        assert (
            len(streaming_calls) >= 2
        ), f"Should have retried streaming connection. Calls: {streaming_calls}"

    finally:
        client.destroy()


def test_client_streaming_error_handling(monkeypatch):
    """Test streaming connector error handling using urllib3 mocking."""

    mock_calls = []

    def mock_urlopen_with_errors(self, method, url, body=None, headers=None, **kwargs):
        """Mock urllib3 that returns various error conditions."""
        mock_calls.append({"method": method, "url": url, "headers": headers})

        if "/streaming" in url:
            return MockHTTPResponse(b"Internal Server Error", status=500)
        else:
            response_data = json.dumps({"status": "ok"}).encode("utf-8")
            return MockHTTPResponse(response_data, status=200)

    monkeypatch.setattr(urllib3.PoolManager, "urlopen", mock_urlopen_with_errors)

    client = UnleashClient(
        url="http://localhost:4242",
        app_name="test-app",
        instance_id="test-instance",
        disable_metrics=True,
        disable_registration=True,
        experimental_mode="streaming",
    )

    try:
        client.initialize_client()

        streaming_calls = [call for call in mock_calls if "/streaming" in call["url"]]
        assert len(streaming_calls) >= 1, "Should have attempted streaming connection"

        result = client.is_enabled("test-feature")
        assert isinstance(
            result, bool
        ), "Should return a boolean value even when streaming fails"

    finally:
        client.destroy()
