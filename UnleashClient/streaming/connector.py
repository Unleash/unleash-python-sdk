import threading
from typing import Callable, Optional

from ld_eventsource import SSEClient
from ld_eventsource.config import ConnectStrategy, ErrorStrategy, RetryDelayStrategy

from UnleashClient.constants import STREAMING_URL
from UnleashClient.utils import LOGGER

from .event_processor import StreamingEventProcessor


class StreamingConnector:
    """
    Manages the SSE connection lifecycle with reconnect/backoff and delegates
    event handling to an injected StreamingEventProcessor.
    """

    def __init__(
        self,
        url: str,
        headers: dict,
        request_timeout: int,
        event_processor: StreamingEventProcessor,
        on_ready: Optional[Callable[[], None]] = None,
        sse_client_factory: Optional[Callable[[str, dict, int], SSEClient]] = None,
        backoff_initial: float = 2.0,
        backoff_max: float = 30.0,
        backoff_multiplier: float = 2.0,
        backoff_jitter: Optional[float] = 0.5,
        custom_options: Optional[dict] = None,
    ) -> None:
        self._base_url = url.rstrip("/") + STREAMING_URL
        self._headers = {**headers, "Accept": "text/event-stream"}
        self._timeout = request_timeout
        self._on_ready = on_ready
        self._sse_factory = sse_client_factory
        self._backoff_initial = backoff_initial
        self._backoff_max = backoff_max
        self._backoff_multiplier = backoff_multiplier
        self._backoff_jitter = backoff_jitter
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._processor = event_processor
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
        """
        Main streaming loop. Creates SSEClient once and lets it handle retries internally.
        Only recreates client if there's a catastrophic failure.
        """
        client: Optional[SSEClient] = None

        try:
            LOGGER.info("Connecting to Unleash streaming endpoint: %s", self._base_url)

            if self._sse_factory:
                client = self._sse_factory(self._base_url, self._headers, self._timeout)
            else:
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

                client = SSEClient(
                    connect=connect_strategy,
                    initial_retry_delay=self._backoff_initial,
                    retry_delay_strategy=retry_strategy,
                    retry_delay_reset_threshold=60.0,
                    error_strategy=ErrorStrategy.always_continue(),
                    logger=LOGGER,
                )

            for event in client.events:
                if self._stop.is_set():
                    break
                if not event.event:
                    continue

                self._processor.process(event)
                if event.event == "unleash-connected" and self._processor.hydrated:
                    if self._on_ready:
                        try:
                            self._on_ready()
                        except Exception as cb_exc:  # noqa: BLE001
                            LOGGER.debug("Ready callback error: %s", cb_exc)

            LOGGER.debug("SSE stream ended")

        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Streaming connection failed: %s", exc)

        finally:
            try:
                if client is not None:
                    client.close()
            except Exception:  # noqa: BLE001
                pass
