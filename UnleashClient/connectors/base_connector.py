import uuid
from abc import ABC, abstractmethod
from typing import Optional

from yggdrasil_engine.engine import UnleashEngine

from UnleashClient.cache import BaseCache
from UnleashClient.constants import FEATURES_URL
from UnleashClient.events import (
    BaseEvent,
    EventDispatcher,
    UnleashEventType,
    UnleashReadyEvent,
)
from UnleashClient.utils import LOGGER


class BaseConnector(ABC):
    def __init__(
        self,
        engine: UnleashEngine,
        cache: BaseCache,
        events: Optional[EventDispatcher] = None,
    ):
        """
        :param engine: Feature evaluation engine instance (UnleashEngine).
        :param cache: Should be the cache class variable from UnleashClient
        :param events: Optional dispatcher that delivers events to the user's callback.
        """
        self.engine = engine
        self.cache = cache
        self._events = events

    @abstractmethod
    def start(self):
        pass

    @abstractmethod
    def stop(self):
        pass

    def emit(self, event: BaseEvent) -> None:
        """
        Hands an event to the dispatcher, if the user asked for events at all.
        Emitting never raises: connectors shouldn't have to guard their own
        control flow against a failing event.
        """
        if not self._events:
            return

        try:
            self._events.emit_event(event)
        except Exception:
            LOGGER.debug("Failed to emit %s event", event.event_type, exc_info=True)

    def emit_ready(self) -> None:
        """
        The dispatcher only ever delivers READY once, so connectors are free to
        call this as often as they like.
        """
        self.emit(
            UnleashReadyEvent(
                event_type=UnleashEventType.READY,
                event_id=uuid.uuid4(),
            )
        )

    def load_features(self):
        feature_provisioning = self.cache.get(FEATURES_URL)
        if not feature_provisioning:
            LOGGER.warning(
                "Unleash client does not have cached features. "
                "Please make sure client can communicate with Unleash server!"
            )
            return

        try:
            warnings = self.engine.take_state(feature_provisioning)
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
