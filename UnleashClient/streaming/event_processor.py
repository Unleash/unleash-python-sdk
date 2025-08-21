from __future__ import annotations

from threading import Lock
from typing import Any

from yggdrasil_engine.engine import UnleashEngine

from UnleashClient.utils import LOGGER


class StreamingEventProcessor:
    """
    Processes SSE events from the Unleash streaming endpoint and applies
    resulting deltas/state to the provided engine in a thread-safe manner.

    This class is deliberately unaware of connection/reconnect concerns; it
    only deals with event semantics.
    """

    def __init__(self, engine: UnleashEngine) -> None:
        self._engine = engine
        self._lock = Lock()
        self._hydrated = False

    @property
    def hydrated(self) -> bool:
        return self._hydrated

    def process(self, event: Any) -> None:
        """
        Handle a single SSE event object. The object is expected to have
        attributes `event` (type) and `data` (payload string or dict).
        """
        try:
            etype = getattr(event, "event", None)
            if not etype:
                return

            if etype == "unleash-connected":
                self._handle_connected(event)
            elif etype == "unleash-updated":
                self._handle_updated(event)
            else:
                LOGGER.debug("Ignoring SSE event type: %s", etype)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Error processing SSE event: %s", exc)

    def _apply_delta(self, event_data: Any) -> None:
        if not event_data:
            return
        with self._lock:
            self._engine.take_state(event_data)

    def _handle_connected(self, event: Any) -> None:
        LOGGER.debug("Processing initial hydration data")
        self._apply_delta(getattr(event, "data", None))
        if not self._hydrated:
            self._hydrated = True

    def _handle_updated(self, event: Any) -> None:
        self._apply_delta(getattr(event, "data", None))
