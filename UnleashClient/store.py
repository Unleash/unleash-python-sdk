"""Feature state application, shared by the sync and async Unleash clients."""

import uuid
from typing import Optional

from yggdrasil_engine.engine import UnleashEngine

from UnleashClient.cache import BaseCache
from UnleashClient.constants import ETAG, FEATURES_URL
from UnleashClient.events import (
    BaseEvent,
    EventDispatcher,
    UnleashEventType,
    UnleashFetchedEvent,
    UnleashReadyEvent,
)
from UnleashClient.utils import LOGGER


class FeatureStore:
    """
    Owns what happens to feature state once it has arrived: the cache write, the
    handover to the engine, and the events that follow.

    There is one method per source rather than a single ``apply``, because the
    three steps happen in a different order, over different payloads, with
    different failure handling depending on where the state came from.
    """

    def __init__(
        self,
        engine: UnleashEngine,
        cache: BaseCache,
        events: Optional[EventDispatcher] = None,
    ) -> None:
        """
        :param engine: Feature evaluation engine instance (UnleashEngine).
        :param cache: The cache the client was built with.
        :param events: Optional dispatcher that delivers events to the user's callback.
        """
        self._engine = engine
        self._cache = cache
        self._events = events

    @property
    def cached_etag(self) -> str:
        """The ETag of the last fetch, for conditional requests."""
        return self._cache.get(ETAG, "")

    def load_from_cache(self) -> None:
        """
        Hands the cached feature state to the engine and emits READY.

        Warns and returns when the cache is empty, so nothing is emitted and the
        engine keeps whatever state it already had.  Engine failures are logged
        with the offending body at debug level, never raised: every caller is
        already falling back on the cache and has nothing better to do with the
        failure.
        """
        feature_provisioning = self._cache.get(FEATURES_URL)
        if not feature_provisioning:
            LOGGER.warning(
                "Unleash client does not have cached features. "
                "Please make sure client can communicate with Unleash server!"
            )
            return

        try:
            warnings = self._engine.take_state(feature_provisioning)
            self.emit_ready()
            if warnings:
                LOGGER.warning(
                    "Some features were not able to be parsed correctly, they may not evaluate as expected"
                )
                LOGGER.warning(warnings)
        except Exception as e:
            LOGGER.error(f"Error loading features: {e}")
            LOGGER.debug(
                f"Full feature response body from server: {feature_provisioning}"
            )

    def apply_fetched(
        self, raw_state: Optional[str], etag: Optional[str] = None
    ) -> None:
        """
        Applies the result of a features fetch: cache the payload and the ETag,
        load from the cache, then emit FETCHED.

        ``raw_state`` is None on a 304 or a failed fetch; the cached state is
        loaded again and no FETCHED event is emitted.  A falsy ``etag`` leaves
        the cached one in place.

        The engine is fed from the cache rather than from ``raw_state``, so a
        custom cache's round-trip is what reaches the engine.
        """
        if raw_state:
            self._cache.set(FEATURES_URL, raw_state)
        else:
            LOGGER.debug(
                "No feature provisioning returned from server, using cached provisioning."
            )

        if etag:
            self._cache.set(ETAG, etag)

        self.load_from_cache()

        if raw_state:
            self._emit(
                UnleashFetchedEvent(
                    event_type=UnleashEventType.FETCHED,
                    event_id=uuid.uuid4(),
                    raw_features=raw_state,
                )
            )
            self.emit_ready()

    def apply_streamed(self, raw_state: str, emit_ready: bool = False) -> None:
        """
        Applies a payload from the streaming endpoint: hand it to the engine
        first, then cache the engine's full state.

        An ``unleash-updated`` payload is a delta, so it is the engine's
        post-merge state, not the payload, that a later ``load_from_cache`` can
        use.  Raises whatever the engine raises: the caller decides whether to
        fall back on the cache.
        """
        self._engine.take_state(raw_state)
        self._cache.set(FEATURES_URL, self._engine.get_state())

        if emit_ready:
            self.emit_ready()

    def emit_ready(self) -> None:
        """
        The dispatcher only ever delivers READY once, so callers are free to call
        this as often as they like.
        """
        self._emit(
            UnleashReadyEvent(
                event_type=UnleashEventType.READY,
                event_id=uuid.uuid4(),
            )
        )

    def _emit(self, event: BaseEvent) -> None:
        """
        Hands an event to the dispatcher, if the user asked for events at all.
        Emitting never raises: callers shouldn't have to guard their own control
        flow against a failing event.
        """
        if not self._events:
            return

        try:
            self._events.emit_event(event)
        except Exception:
            LOGGER.debug("Failed to emit %s event", event.event_type, exc_info=True)
