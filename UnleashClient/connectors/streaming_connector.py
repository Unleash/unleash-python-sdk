import threading
from typing import Callable, Optional

from ld_eventsource import SSEClient
from ld_eventsource.config import ConnectStrategy, ErrorStrategy, RetryDelayStrategy
from yggdrasil_engine.engine import UnleashEngine

from UnleashClient.cache import BaseCache
from UnleashClient.connectors.base_connector import BaseConnector
from UnleashClient.constants import APPLICATION_HEADERS, FEATURES_URL, STREAMING_URL
from UnleashClient.utils import LOGGER


class StreamingConnector(BaseConnector):
    def __init__(
        self,
        engine: UnleashEngine,
        cache: BaseCache,
        url: str,
        headers: dict,
        request_timeout: int,
        ready_callback: Optional[Callable] = None,
        backoff_initial: float = 2.0,
        backoff_max: float = 30.0,
        backoff_multiplier: float = 2.0,
        backoff_jitter: Optional[float] = 0.5,
        custom_options: Optional[dict] = None,
    ) -> None:
        super().__init__(engine=engine, cache=cache, ready_callback=ready_callback)
        self._base_url = url.rstrip("/") + STREAMING_URL
        self._headers = {
            **headers,
            **APPLICATION_HEADERS,
            "Accept": "text/event-stream",
        }
        self._timeout = request_timeout
        self._backoff_initial = backoff_initial
        self._backoff_max = backoff_max
        self._backoff_multiplier = backoff_multiplier
        self._backoff_jitter = backoff_jitter
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._client: Optional[SSEClient] = None
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
        try:
            if self._client:
                self._client.close()
        except Exception:
            pass
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self):
        try:
            LOGGER.info("Connecting to Unleash streaming endpoint: %s", self._base_url)

            connect_strategy = ConnectStrategy.http(
                self._base_url,
                headers=self._headers,
                urllib3_request_options=self._custom_options,
            )

            retry_strategy = RetryDelayStrategy.default(
                max_delay=self._backoff_max,
                backoff_multiplier=self._backoff_multiplier,
                jitter_multiplier=self._backoff_jitter,
            )

            self._client = SSEClient(
                connect=connect_strategy,
                initial_retry_delay=self._backoff_initial,
                retry_delay_strategy=retry_strategy,
                retry_delay_reset_threshold=60.0,
                error_strategy=ErrorStrategy.always_continue(),
                logger=LOGGER,
            )

            # Initial hydration happens in the stream.
            for item in self._client.all:
                if self._stop.is_set():
                    LOGGER.debug("SSE stream stopped by user request")
                    break

                if hasattr(item, "event") and hasattr(item, "data"):
                    if not item.event:
                        continue

                    if item.event in ("unleash-connected", "unleash-updated"):
                        try:
                            self.engine.take_state(item.data)
                            self.cache.set(FEATURES_URL, self.engine.get_state())

                            if (
                                item.event == "unleash-connected"
                                and self.ready_callback
                            ):
                                try:
                                    self.ready_callback()
                                except Exception:
                                    LOGGER.debug("Ready callback failed", exc_info=True)
                        except Exception:
                            LOGGER.error(
                                "Error applying streaming state", exc_info=True
                            )
                            self.load_features()
                    else:
                        LOGGER.warning("Ignoring SSE event type: %s", item.event)
                elif hasattr(item, "error"):
                    if item.error is None:
                        if not self._stop.is_set():
                            LOGGER.info(
                                "SSE stream ended - server closed connection gracefully"
                            )
                    else:
                        if not self._stop.is_set():
                            LOGGER.warning(
                                "SSE stream error: %s - will retry", item.error
                            )
        except Exception as exc:
            LOGGER.warning("Streaming connection failed: %s", exc)
            self.load_features()
        finally:
            try:
                if self._client is not None:
                    self._client.close()
            except Exception:
                pass
