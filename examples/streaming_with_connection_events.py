import os
import time
import uuid
from enum import Enum
from dataclasses import dataclass
from typing import Optional

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


class StreamingConnectorWithEvents:
    """Enhanced streaming connector that emits connection events."""

    def __init__(self, original_connector, event_callback):
        self.original_connector = original_connector
        self.event_callback = event_callback
        self._connection_state = "disconnected"
        self._retry_count = 0

        # Wrap the original _run method to add event notifications
        self._original_run = original_connector._run
        original_connector._run = self._enhanced_run

    def _emit_event(self, event_type, **kwargs):
        """Emit a streaming connection event."""
        if self.event_callback:
            try:
                event = StreamingConnectionEvent(
                    event_type=event_type, event_id=uuid.uuid4(), **kwargs
                )
                self.event_callback(event)
            except Exception as e:
                print(f"Event callback error: {e}")

    def _enhanced_run(self):
        """Enhanced run method with connection event notifications."""
        from ld_eventsource import SSEClient
        from ld_eventsource.config import ConnectStrategy
        from UnleashClient.utils import LOGGER

        client = None
        try:
            self._emit_event(
                StreamingEventType.RECONNECTING,
                connection_url=self.original_connector._base_url,
                retry_count=self._retry_count,
            )

            LOGGER.info(
                "Connecting to Unleash streaming endpoint: %s",
                self.original_connector._base_url,
            )

            if self.original_connector._sse_factory:
                client = self.original_connector._sse_factory(
                    self.original_connector._base_url,
                    self.original_connector._headers,
                    self.original_connector._timeout,
                )
            else:
                connect_strategy = ConnectStrategy.http(
                    self.original_connector._base_url,
                    headers=self.original_connector._headers,
                    urllib3_request_options=self.original_connector._custom_options,
                )
                client = SSEClient(
                    connect=connect_strategy,
                    initial_retry_delay=self.original_connector._backoff_initial,
                    logger=LOGGER,
                )

            # Emit connected event
            self._emit_event(
                StreamingEventType.CONNECTED,
                connection_url=self.original_connector._base_url,
            )
            self._connection_state = "connected"
            self._retry_count = 0

            last_event_time = time.time()

            # Iterate over events
            for event in client.events:
                if self.original_connector._stop.is_set():
                    client.close()
                    break
                if not event.event:
                    continue

                last_event_time = time.time()

                # Delegate event processing
                self.original_connector._processor.process(event)
                if (
                    event.event == "unleash-connected"
                    and self.original_connector._processor.hydrated
                ):
                    if self.original_connector._on_ready:
                        try:
                            self.original_connector._on_ready()
                        except Exception as cb_exc:
                            LOGGER.debug("Ready callback error: %s", cb_exc)

                # Heartbeat timeout check
                if self.original_connector._hb_timeout and (
                    time.time() - last_event_time > self.original_connector._hb_timeout
                ):
                    LOGGER.warning("Heartbeat timeout exceeded; reconnecting")
                    self._emit_event(
                        StreamingEventType.DISCONNECTED,
                        connection_url=self.original_connector._base_url,
                        error_message="Heartbeat timeout",
                    )
                    try:
                        client.interrupt()
                    except Exception:
                        client.close()
                        break

        except Exception as exc:
            LOGGER.warning("Streaming error: %s", exc)
            self._emit_event(
                StreamingEventType.ERROR,
                connection_url=self.original_connector._base_url,
                error_message=str(exc),
            )
            self._retry_count += 1
        finally:
            if self._connection_state == "connected":
                self._emit_event(
                    StreamingEventType.DISCONNECTED,
                    connection_url=self.original_connector._base_url,
                )
                self._connection_state = "disconnected"

            try:
                if client is not None:
                    client.close()
            except Exception:
                pass


# Configuration
using_edge = os.getenv("USING_EDGE", "true").lower() == "true"
URL = (
    "http://localhost:3063/api"
    if using_edge
    else "https://sandbox.getunleash.io/enterprise/api"
)
TOKEN = "hammer-1:development.4819f784fbe351f8a74982d43a68f53dcdbf74cdde554a5d0a81d997"
FLAG = "flag-page-hh"

headers = {"Authorization": TOKEN}
ready = False


def enhanced_event_callback(event):
    """Enhanced event callback that handles both regular and streaming events."""
    global ready

    if hasattr(event, "event_type"):
        if event.event_type == UnleashEventType.READY:
            ready = True
            print("🟢 Unleash client is ready!")

        elif event.event_type == StreamingEventType.CONNECTED:
            print(f"🔗 Streaming connected to: {event.connection_url}")

        elif event.event_type == StreamingEventType.DISCONNECTED:
            print(f"❌ Streaming disconnected from: {event.connection_url}")
            if event.error_message:
                print(f"   Reason: {event.error_message}")

        elif event.event_type == StreamingEventType.RECONNECTING:
            print(
                f"🔄 Streaming reconnecting to: {event.connection_url} (attempt #{event.retry_count + 1})"
            )

        elif event.event_type == StreamingEventType.ERROR:
            print(f"⚠️  Streaming error: {event.error_message}")


# Create client
client = UnleashClient(
    url=URL,
    app_name="python-streaming-example",
    instance_id="example-instance",
    custom_headers=headers,
    experimental_mode={"type": "streaming"},
    event_callback=enhanced_event_callback,
)

# Enhance the streaming connector with connection events after initialization
if hasattr(client, "_streaming_connector") and client._streaming_connector:
    enhanced_connector = StreamingConnectorWithEvents(
        client._streaming_connector, enhanced_event_callback
    )

client.initialize_client()

print("Waiting for streaming connection and hydration (Ctrl+C to exit)")

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
        enabled = client.is_enabled(FLAG, {"userId": "example"})
        print(f"{FLAG} enabled? {enabled}")
        time.sleep(1)
except KeyboardInterrupt:
    print("\n🛑 Shutting down...")
finally:
    client.destroy()
