import os
import time
import uuid
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Callable
import logging

from UnleashClient import UnleashClient
from UnleashClient.events import UnleashEventType, BaseEvent


# Extended event types for streaming connections
class StreamingEventType(Enum):
    """Extended event types for streaming connections."""

    CONNECTED = "streaming_connected"
    DISCONNECTED = "streaming_disconnected"
    RECONNECTING = "streaming_reconnecting"
    ERROR = "streaming_error"


@dataclass
class StreamingConnectionEvent(BaseEvent):
    """Event for streaming connection state changes."""

    connection_url: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: Optional[int] = None


class StreamingEventMonitor:
    """Monitor streaming events by intercepting log messages."""

    def __init__(self, event_callback: Callable):
        self.event_callback = event_callback
        self.connection_url = None
        self._setup_log_monitoring()

    def _setup_log_monitoring(self):
        """Set up log monitoring to detect connection events."""
        from UnleashClient.utils import LOGGER

        # Store original handlers
        self.original_handlers = LOGGER.handlers.copy()

        # Add our custom handler
        handler = StreamingLogHandler(self)
        handler.setLevel(logging.INFO)
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

    def handle_log_message(self, message: str, level: int):
        """Handle log messages to detect connection events."""
        if "Connecting to Unleash streaming endpoint:" in message:
            self.connection_url = message.split(": ", 1)[1] if ": " in message else None
            self._emit_event(StreamingEventType.RECONNECTING)

        elif "Heartbeat timeout exceeded; reconnecting" in message:
            self._emit_event(
                StreamingEventType.DISCONNECTED, error_message="Heartbeat timeout"
            )

        elif "Streaming error:" in message:
            error_msg = (
                message.split("Streaming error: ", 1)[1]
                if "Streaming error: " in message
                else message
            )
            self._emit_event(StreamingEventType.ERROR, error_message=error_msg)


class StreamingLogHandler(logging.Handler):
    """Custom log handler to intercept streaming-related log messages."""

    def __init__(self, monitor: StreamingEventMonitor):
        super().__init__()
        self.monitor = monitor

    def emit(self, record):
        """Emit log record and check for streaming events."""
        try:
            message = self.format(record)
            self.monitor.handle_log_message(message, record.levelno)
        except Exception:
            pass  # Don't let logging errors break the application


# Configuration
using_edge = os.getenv("USING_EDGE", "false").lower() == "true"
URL = (
    "http://localhost:3063/api"
    if using_edge
    else "https://sandbox.getunleash.io/enterprise/api"
)
TOKEN = "hammer-1:development.4819f784fbe351f8a74982d43a68f53dcdbf74cdde554a5d0a81d997"
FLAG = "flag-page-hh"

headers = {"Authorization": TOKEN}
ready = False
streaming_connected = False


def enhanced_event_callback(event):
    """Enhanced event callback that handles both regular and streaming events."""
    global ready, streaming_connected

    if hasattr(event, "event_type"):
        if event.event_type == UnleashEventType.READY:
            ready = True
            streaming_connected = True  # Ready implies streaming is connected
            print("🟢 Unleash client is ready!")

        elif event.event_type == StreamingEventType.CONNECTED:
            streaming_connected = True
            print(f"🔗 Streaming connected to: {event.connection_url}")

        elif event.event_type == StreamingEventType.DISCONNECTED:
            streaming_connected = False
            print(f"❌ Streaming disconnected from: {event.connection_url}")
            if event.error_message:
                print(f"   Reason: {event.error_message}")

        elif event.event_type == StreamingEventType.RECONNECTING:
            streaming_connected = False
            print(f"🔄 Streaming reconnecting to: {event.connection_url}")

        elif event.event_type == StreamingEventType.ERROR:
            print(f"⚠️  Streaming error: {event.error_message}")


# Set up streaming event monitoring
monitor = StreamingEventMonitor(enhanced_event_callback)

# Create client
client = UnleashClient(
    url=URL,
    app_name="python-streaming-example",
    instance_id="example-instance",
    custom_headers=headers,
    experimental_mode={"type": "streaming"},
    event_callback=enhanced_event_callback,
)

client.initialize_client()

print("Waiting for streaming connection and hydration (Ctrl+C to exit)")
print("Watch for connection events marked with 🔗❌🔄⚠️")

try:
    while True:
        if not client.is_initialized:
            print("Client not initialized yet, waiting...")
            time.sleep(0.2)
            continue
        if not ready:
            print("Waiting for hydration via streaming... (Ctrl+C to exit)")
            time.sleep(0.2)
            continue

        # Show connection status
        status_icon = "🟢" if streaming_connected else "🔴"
        enabled = client.is_enabled(FLAG, {"userId": "example"})
        print(f"{status_icon} {FLAG} enabled? {enabled}")
        time.sleep(1)
except KeyboardInterrupt:
    print("\n🛑 Shutting down...")
finally:
    client.destroy()
