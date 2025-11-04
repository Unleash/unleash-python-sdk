from abc import ABC, abstractmethod
from typing import Callable, Optional

from yggdrasil_engine.engine import UnleashEngine

from UnleashClient.cache import BaseCache


class BaseSyncConnector(ABC):
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
    def start(self):
        pass

    @abstractmethod
    def stop(self):
        pass
