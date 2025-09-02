#!/usr/bin/env python3
"""
Test script to verify that the StreamingConnector properly implements exponential backoff
using the ld-eventsource library's retry strategy, similar to other Unleash SDKs.
"""

import json
import time
from unittest.mock import patch, MagicMock

from UnleashClient.streaming import StreamingConnector
from UnleashClient.streaming.event_processor import StreamingEventProcessor


class FakeEngine:
    def __init__(self):
        self.states = []

    def take_state(self, state_json: str):
        self.states.append(state_json)


class FakeEvent:
    def __init__(self, event: str, data):
        self.event = event
        self.data = data


def test_sse_client_created_with_backoff():
    """Test that SSEClient is created with proper exponential backoff configuration"""
    print("🔧 Testing SSEClient configuration...")

    engine = FakeEngine()
    processor = StreamingEventProcessor(engine)

    # Mock RetryDelayStrategy.default to capture parameters
    with patch(
        "UnleashClient.streaming.connector.RetryDelayStrategy"
    ) as mock_retry_strategy:
        with patch("UnleashClient.streaming.connector.SSEClient") as mock_sse_client:
            mock_client = MagicMock()
            mock_sse_client.return_value = mock_client
            mock_client.events = iter([])  # Empty iterator so _run() exits quickly

            mock_strategy_instance = MagicMock()
            mock_retry_strategy.default.return_value = mock_strategy_instance

            controller = StreamingConnector(
                url="http://unleash.example",
                headers={"Authorization": "secret123"},
                request_timeout=10,
                event_processor=processor,
                backoff_initial=2.5,  # Use non-default values to verify they're passed
                backoff_max=25.0,
                backoff_multiplier=1.8,
                backoff_jitter=0.3,
            )

            # Start and let it run briefly
            controller.start()
            time.sleep(0.1)
            controller.stop()

            # Verify RetryDelayStrategy.default was called with our custom parameters
            mock_retry_strategy.default.assert_called_once_with(
                max_delay=25.0,
                backoff_multiplier=1.8,
                jitter_multiplier=0.3,
            )

            # Verify SSEClient was created with the strategy and initial delay
            assert mock_sse_client.called, "SSEClient should have been created"
            call_args = mock_sse_client.call_args

            assert (
                call_args.kwargs["initial_retry_delay"] == 2.5
            ), "initial_retry_delay should match backoff_initial"
            assert (
                call_args.kwargs["retry_delay_strategy"] == mock_strategy_instance
            ), "retry_delay_strategy should be our mock"
            assert (
                call_args.kwargs["retry_delay_reset_threshold"] == 60.0
            ), "retry_delay_reset_threshold should be 60.0"

            print(
                "   ✅ SSEClient created with proper exponential backoff configuration"
            )
            print(
                f"   📊 Backoff config: initial={2.5}s, max={25.0}s, multiplier={1.8}, jitter={0.3}"
            )


def test_successful_connection():
    """Test that successful connections work without retries"""
    print("📶 Testing successful connection (no retries needed)...")

    engine = FakeEngine()
    processor = StreamingEventProcessor(engine)

    # Create events that simulate successful connection
    events = [
        FakeEvent(
            "unleash-connected",
            json.dumps({"version": 1, "features": [], "segments": []}),
        )
    ]

    controller = StreamingConnector(
        url="http://unleash.example",
        headers={"Authorization": "secret123"},
        request_timeout=10,
        event_processor=processor,
        sse_client_factory=lambda url, headers, timeout: FakeSuccessfulSSEClient(
            events
        ),
    )

    # Run for a short time
    import threading

    thread = threading.Thread(target=controller._run, daemon=True)
    thread.start()
    time.sleep(0.1)
    controller.stop()
    thread.join(timeout=1)

    # Verify it processed the connection event
    assert len(engine.states) == 1, "Should have processed one hydration event"
    print("   ✅ Successful connection handled without retries")


def test_connection_retry_behavior():
    """Test that connection failures trigger proper retry behavior"""
    print("🔄 Testing connection retry behavior...")

    engine = FakeEngine()
    processor = StreamingEventProcessor(engine)

    retry_attempts = []

    def mock_sse_client_factory(url, headers, timeout):
        retry_attempts.append(time.time())
        # Simulate a failing client that immediately fails
        return FailingSSEClient()

    controller = StreamingConnector(
        url="http://unleash.example",
        headers={"Authorization": "secret123"},
        request_timeout=10,
        event_processor=processor,
        sse_client_factory=mock_sse_client_factory,
    )

    # Run for a short time to capture retry attempts
    start_time = time.time()
    import threading

    thread = threading.Thread(target=controller._run, daemon=True)
    thread.start()
    time.sleep(2.5)  # Let it try a few times
    controller.stop()
    thread.join(timeout=1)

    print(f"   Retry attempts: {len(retry_attempts)}")

    # Should have made multiple retry attempts
    assert (
        len(retry_attempts) >= 2
    ), f"Expected multiple retry attempts, got {len(retry_attempts)}"

    # Verify there's some delay between attempts (at least 1 second due to our fallback delay)
    if len(retry_attempts) >= 2:
        time_between_retries = retry_attempts[1] - retry_attempts[0]
        assert (
            time_between_retries >= 0.9
        ), f"Expected at least 1s between retries, got {time_between_retries:.2f}s"
        print(f"   ✅ Proper delay between retries: {time_between_retries:.2f}s")


class FakeSuccessfulSSEClient:
    """SSE client that successfully delivers events"""

    def __init__(self, events):
        self._events = events
        self.closed = False

    @property
    def events(self):
        for event in self._events:
            if self.closed:
                break
            yield event

    def close(self):
        self.closed = True

    def interrupt(self):
        self.close()


class FailingSSEClient:
    """SSE client that immediately fails"""

    def __init__(self):
        self.closed = False

    @property
    def events(self):
        # Immediately raise an exception to simulate connection failure
        raise ConnectionError("Simulated connection failure")

    def close(self):
        self.closed = True

    def interrupt(self):
        self.close()


if __name__ == "__main__":
    print("🚀 Testing StreamingConnector exponential backoff implementation...")
    print()

    test_sse_client_created_with_backoff()
    print()

    test_successful_connection()
    print()

    test_connection_retry_behavior()
    print()

    print("🎉 All tests passed!")
    print(
        "✨ StreamingConnector now uses proper exponential backoff via ld-eventsource"
    )
    print("📝 This matches the behavior of Node.js, Java, and Ruby SDKs")

import json
import time
from unittest.mock import patch

from UnleashClient.streaming import StreamingConnector
from UnleashClient.streaming.event_processor import StreamingEventProcessor


class FakeEngine:
    def __init__(self):
        self.states = []

    def take_state(self, state_json: str):
        self.states.append(state_json)


class FakeEvent:
    def __init__(self, event: str, data):
        self.event = event
        self.data = data


class FiniteSSEClient:
    """SSE client that sends events then stops (doesn't loop infinitely)"""

    def __init__(self, events):
        self._events = events
        self.closed = False

    @property
    def events(self):
        for e in self._events:
            yield e
        # After events are done, we stop (this simulates connection ending)

    def close(self):
        self.closed = True

    def interrupt(self):
        self.close()


def test_successful_connection():
    print("🧪 Testing successful connection (should have no sleep delays)...")

    ready_called = {"v": 0}

    def on_ready():
        ready_called["v"] += 1

    processor = StreamingEventProcessor(FakeEngine())

    def success_factory(url, headers, timeout):
        return FiniteSSEClient(
            [
                FakeEvent("unleash-connected", json.dumps({"toggles": []})),
                FakeEvent("unleash-updated", json.dumps({"toggles": []})),
            ]
        )

    controller = StreamingConnector(
        url="http://unleash.example",
        headers={},
        request_timeout=5,
        event_processor=processor,
        on_ready=on_ready,
        sse_client_factory=success_factory,
    )

    sleep_calls = []

    def mock_sleep(duration):
        sleep_calls.append(duration)
        # Stop after first sleep to prevent infinite loop in test
        if len(sleep_calls) >= 1:
            controller.stop()

    with patch("time.sleep", side_effect=mock_sleep):
        controller._run()

    print(f"   Sleep calls: {sleep_calls}")
    print(f"   Ready called: {ready_called['v']} times")

    # Should have exactly one sleep call (the 1s retry delay after events finish)
    assert len(sleep_calls) == 1, f"Expected 1 sleep call, got {len(sleep_calls)}"
    assert sleep_calls[0] == 1.0, f"Expected 1.0s delay, got {sleep_calls[0]}s"
    assert (
        ready_called["v"] == 1
    ), f"Expected ready callback once, got {ready_called['v']}"

    print("   ✅ Success: Uses simple 1s delay, not exponential backoff")


def test_failed_connection():
    print("🧪 Testing failed connection (should use simple 1s delays)...")

    class FailingSSEClient:
        def __init__(self, *args, **kwargs):
            self.closed = False

        @property
        def events(self):
            raise ConnectionError("Simulated connection failure")
            yield  # unreachable

        def close(self):
            self.closed = True

        def interrupt(self):
            self.close()

    processor = StreamingEventProcessor(FakeEngine())

    def failing_factory(url, headers, timeout):
        return FailingSSEClient()

    controller = StreamingConnector(
        url="http://unleash.example",
        headers={},
        request_timeout=5,
        event_processor=processor,
        sse_client_factory=failing_factory,
    )

    sleep_calls = []

    def mock_sleep(duration):
        sleep_calls.append(duration)
        # Stop after a few attempts
        if len(sleep_calls) >= 3:
            controller.stop()

    with patch("time.sleep", side_effect=mock_sleep):
        controller._run()

    print(f"   Sleep calls: {sleep_calls}")

    assert len(sleep_calls) >= 2, f"Expected multiple retries, got {len(sleep_calls)}"
    for i, sleep_duration in enumerate(sleep_calls):
        assert sleep_duration == 1.0, f"Sleep {i}: expected 1.0s, got {sleep_duration}s"

    print("   ✅ Success: All retries use 1.0s delay (no exponential backoff)")


if __name__ == "__main__":
    print("🚀 Testing StreamingConnector simplified backoff...")
    print()

    test_successful_connection()
    print()

    test_failed_connection()
    print()

    print("🎉 All tests passed!")
    print(
        "✨ StreamingConnector now uses simplified 1s retry delays instead of exponential backoff"
    )
    print(
        "📝 This aligns with other Unleash SDKs that rely on LaunchDarkly EventSource internal backoff"
    )
