import threading
import time
from typing import Callable, Optional

from ld_eventsource import SSEClient
from ld_eventsource.config import ConnectStrategy
from yggdrasil_engine.engine import UnleashEngine

from UnleashClient.constants import STREAMING_URL
from UnleashClient.utils import LOGGER


class StreamingManager:
    """
    Simple SSE streaming manager with reconnect and backoff.
    Applies deltas to the engine by calling engine.take_state(raw_json).
    """

    def __init__(
        self,
        url: str,
        headers: dict,
        request_timeout: int,
        engine: UnleashEngine,
        on_ready: Optional[Callable[[], None]] = None,
        sse_client_factory: Optional[Callable[[str, dict, int], SSEClient]] = None,
        heartbeat_timeout: int = 60,
        backoff_initial: float = 2.0,
        backoff_max: float = 30.0,
        backoff_jitter: float = 0.5,
        custom_options: Optional[dict] = None,
    ) -> None:
        self._base_url = url.rstrip("/") + STREAMING_URL
        self._headers = {**headers, "Accept": "text/event-stream"}
        self._timeout = request_timeout
        self._engine = engine
        self._on_ready = on_ready
        self._sse_factory = sse_client_factory
        self._hb_timeout = heartbeat_timeout
        self._backoff_initial = backoff_initial
        self._backoff_max = backoff_max
        self._backoff_jitter = backoff_jitter
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._hydrated = False
        # Ensure urllib3 timeout is honored by ld_eventsource
        base_options = custom_options or {}
        if self._timeout is not None and "timeout" not in base_options:
            base_options = {"timeout": self._timeout, **base_options}
        self._custom_options = base_options

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="UnleashStreaming", daemon=True
        )
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self):  # noqa: PLR0912
        client: Optional[SSEClient] = None
        try:
            LOGGER.info("Connecting to Unleash streaming endpoint: %s", self._base_url)

            # Use LaunchDarkly EventSource client
            if self._sse_factory:
                client = self._sse_factory(self._base_url, self._headers, self._timeout)
            else:
                connect_strategy = ConnectStrategy.http(
                    self._base_url,
                    headers=self._headers,
                    urllib3_request_options=self._custom_options,
                )
                client = SSEClient(
                    connect=connect_strategy,
                    initial_retry_delay=self._backoff_initial,
                    logger=LOGGER,
                )

            last_event_time = time.time()

            # Iterate over events; SSEClient handles reconnects with internal backoff/jitter
            for event in client.events:
                if self._stop.is_set():
                    client.close()
                    break
                if not event.event:
                    continue

                last_event_time = time.time()

                if event.event in ("unleash-connected", "unleash-updated"):
                    try:
                        data = event.data
                        if not data:
                            continue
                        # Apply under lock
                        with self._lock:
                            self._engine.take_state(data)
                        if event.event == "unleash-connected" and not self._hydrated:
                            self._hydrated = True
                            if self._on_ready:
                                try:
                                    self._on_ready()
                                except Exception as cb_exc:  # noqa: BLE001
                                    LOGGER.debug("Ready callback error: %s", cb_exc)
                    except Exception as exc:  # noqa: BLE001
                        LOGGER.warning("Error processing SSE event: %s", exc)
                else:
                    LOGGER.debug("Ignoring SSE event type: %s", event.event)

                # Heartbeat timeout: trigger reconnect via SSEClient interrupt (uses internal retry)
                if self._hb_timeout and (
                    time.time() - last_event_time > self._hb_timeout
                ):
                    LOGGER.warning("Heartbeat timeout exceeded; reconnecting")
                    try:
                        client.interrupt()
                    except Exception:  # noqa: BLE001
                        # If interrupt fails, close will end the loop; SSEClient will not retry when closed
                        client.close()
                        break
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Streaming error: %s", exc)
        finally:
            try:
                if client is not None:
                    client.close()
            except Exception:  # noqa: BLE001
                pass
