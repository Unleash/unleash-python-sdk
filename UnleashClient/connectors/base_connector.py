from abc import ABC, abstractmethod
from typing import Callable, Optional

from yggdrasil_engine.engine import UnleashEngine

from UnleashClient.cache import BaseCache
from UnleashClient.constants import FEATURES_URL
from UnleashClient.utils import LOGGER

class BaseConnector(ABC):
    def __init__(
        self,
        engine: UnleashEngine,
        cache: BaseCache,
        ready_callback: Optional[Callable] = None,
    ):
        """
        :param engine: Feature evaluation engine instance (UnleashEngine).
        :param cache: Should be the cache class variable from UnleashClient
        :param ready_callback: Optional function to call when features are successfully loaded.
        """
        self.engine = engine
        self.cache = cache
        self.ready_callback = ready_callback

    @abstractmethod
    def run(self):
        pass

    @abstractmethod
    def stop(self):
        pass

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
            if self.ready_callback:
                self.ready_callback()
            if warnings:
                LOGGER.warning(
                    "Some features were not able to be parsed correctly, they may not evaluate as expected"
                )
                LOGGER.warning(warnings)
        except Exception as e:
            LOGGER.error(f"Error loading features: {e}")
            LOGGER.debug(f"Full feature response body from server: {feature_provisioning}")
