"""
Unleash Python SDK - Streaming with Connection Events

This example demonstrates how to use the Python SDK with streaming mode
and monitor connection events (connected/disconnected/reconnecting/error).

Usage:
    # Using Edge
    USING_EDGE=true python streaming_with_events.py

    # Using direct upstream
    USING_EDGE=false python streaming_with_events.py
"""

import os
import time
import time as _time
import uuid
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Callable
import logging

from UnleashClient import UnleashClient
from UnleashClient.events import UnleashEventType, BaseEvent


class StreamingEventType(Enum):
    """Event types for streaming connections."""

    CONNECTED = "streaming_connected"
    DISCONNECTED = "streaming_disconnected"
    RECONNECTING = "streaming_reconnecting"
    ERROR = "streaming_error"


@dataclass
class StreamingConnectionEvent(BaseEvent):
    """Event for streaming connection state changes."""

    connection_url: Optional[str] = None
    error_message: Optional[str] = None


class StreamingLogHandler(logging.Handler):
    """Custom log handler to capture streaming-related events."""

    def __init__(self, monitor: "StreamingEventMonitor"):
        super().__init__()
        self.monitor = monitor

    def emit(self, record):
        """Process log record for streaming events."""
        try:
            message = self.format(record)
            self.monitor.handle_log_message(message)
        except Exception:
            pass  # Don't let logging errors break the application


class StreamingEventMonitor:
    """Monitor streaming connection events via log interception."""

    def __init__(self, event_callback: Callable):
        self.event_callback = event_callback
        self.connection_url = None
        self.is_connected = False
        self._setup_log_monitoring()

    def _setup_log_monitoring(self):
        """Set up log monitoring to detect connection events."""
        from UnleashClient.utils import LOGGER

        # Add our custom handler to monitor streaming logs
        handler = StreamingLogHandler(self)
        handler.setLevel(logging.INFO)
        # Prefer DEBUG to capture reconnect internals
        LOGGER.setLevel(logging.DEBUG)
        LOGGER.addHandler(handler)

    def _emit_event(self, event_type, **kwargs):
        """Emit a streaming connection event."""
        if self.event_callback:
            try:
                event = StreamingConnectionEvent(
                    event_type=event_type,
                    event_id=uuid.uuid4(),
                    connection_url=self.connection_url,
                    **kwargs,
                )
                self.event_callback(event)
            except Exception as e:
                print(f"Event callback error: {e}")

    def handle_log_message(self, message: str):
        """Process log messages to detect streaming connection events."""
        msg = message or ""
        lower = msg.lower()
        if "Connecting to Unleash streaming endpoint:" in msg or (
            "connect" in lower and "stream" in lower and "endpoint" in lower
        ):
            # Extract URL from log message
            self.connection_url = (
                msg.split(": ", 1)[1] if ": " in msg else self.connection_url
            )
            if not self.is_connected:
                self._emit_event(StreamingEventType.RECONNECTING)

        elif "heartbeat timeout" in lower and "reconnect" in lower:
            if self.is_connected:
                self.is_connected = False
                self._emit_event(
                    StreamingEventType.DISCONNECTED, error_message="Heartbeat timeout"
                )

        elif ("streaming error:" in msg) or ("error" in lower and "stream" in lower):
            error_msg = (
                msg.split("Streaming error: ", 1)[1]
                if "Streaming error: " in msg
                else msg
            )
            # If we were connected, mark as disconnected first
            if self.is_connected:
                self.is_connected = False
                self._emit_event(
                    StreamingEventType.DISCONNECTED, error_message=error_msg
                )
            # Emit error event too
            self._emit_event(StreamingEventType.ERROR, error_message=error_msg)

        elif ("successfully connected" in lower and "stream" in lower) or (
            "connected" in lower and "stream" in lower
        ):
            self.is_connected = True
            self._emit_event(StreamingEventType.CONNECTED)


# Configuration
using_edge = os.getenv("USING_EDGE", "false").lower() == "true"
URL = (
    "http://localhost:3063/api"
    if using_edge
    else "https://sandbox.getunleash.io/enterprise/api"
)
TOKEN = "hammer-1:development.4819f784fbe351f8a74982d43a68f53dcdbf74cdde554a5d0a81d997"
FLAG = "flag-page-hh"

# Optional: run for a fixed duration (seconds); 0 means run until Ctrl+C
RUN_SECONDS = int(os.getenv("RUN_SECONDS", "0") or "0")

headers = {"Authorization": TOKEN}
ready = False


event_counts = {"connected": 0, "disconnected": 0, "reconnecting": 0, "error": 0}
monitor_ref: "StreamingEventMonitor" | None = None


def event_callback(event):
    """Handle both regular Unleash events and streaming connection events."""
    global ready

    if hasattr(event, "event_type"):
        if event.event_type == UnleashEventType.READY:
            ready = True
            print("✅ Unleash client is ready and hydrated!")
            # Consider READY as initial connection established
            global monitor_ref
            if monitor_ref and not monitor_ref.is_connected:
                monitor_ref.is_connected = True
                event_counts["connected"] += 1
                monitor_ref._emit_event(StreamingEventType.CONNECTED)

        elif event.event_type == StreamingEventType.CONNECTED:
            event_counts["connected"] += 1
            print(f"🔗 Streaming CONNECTED to: {event.connection_url}")

        elif event.event_type == StreamingEventType.DISCONNECTED:
            event_counts["disconnected"] += 1
            print(f"❌ Streaming DISCONNECTED from: {event.connection_url}")
            if event.error_message:
                print(f"   Reason: {event.error_message}")

        elif event.event_type == StreamingEventType.RECONNECTING:
            event_counts["reconnecting"] += 1
            print(f"🔄 Streaming RECONNECTING to: {event.connection_url}")

        elif event.event_type == StreamingEventType.ERROR:
            event_counts["error"] += 1
            print(f"⚠️  Streaming ERROR: {event.error_message}")


def main():
    print(f"🚀 Starting Unleash client with streaming...")
    print(f"   URL: {URL}")
    print(f"   Using Edge: {using_edge}")
    print(f"   Test Flag: {FLAG}")
    print()

    # Set up streaming event monitoring
    global monitor_ref
    monitor = StreamingEventMonitor(event_callback)
    monitor_ref = monitor

    # Create Unleash client with streaming
    client = UnleashClient(
        url=URL,
        app_name="python-streaming-events",
        instance_id="events-example",
        custom_headers=headers,
        experimental_mode={"type": "streaming"},
        event_callback=event_callback,
    )

    client.initialize_client()

    if RUN_SECONDS > 0:
        print(f"Waiting for connection events... (auto-exit after {RUN_SECONDS}s)")
    else:
        print("Waiting for connection events... (Ctrl+C to exit)")
    print("Watch for: 🔗 CONNECTED, ❌ DISCONNECTED, 🔄 RECONNECTING, ⚠️ ERROR")
    print()

    try:
        start = _time.time()
        while True:
            if not client.is_initialized or not ready:
                print("⏳ Waiting for client initialization...")
                time.sleep(0.5)
                continue

            # Test the flag
            enabled = client.is_enabled(FLAG, {"userId": "test-user"})
            print(f"🏁 Flag '{FLAG}' is {'enabled' if enabled else 'disabled'}")
            time.sleep(2)
            if RUN_SECONDS and (_time.time() - start) >= RUN_SECONDS:
                break

    except KeyboardInterrupt:
        print("\n🛑 Shutting down client...")
    finally:
        client.destroy()
        print("✨ Done! Event counts:")
        print(
            f"   connected={event_counts['connected']}, disconnected={event_counts['disconnected']}, reconnecting={event_counts['reconnecting']}, error={event_counts['error']}"
        )


if __name__ == "__main__":
    main()
