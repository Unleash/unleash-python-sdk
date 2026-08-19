from abc import ABC, abstractmethod

from UnleashClient.store import FeatureStore


class BaseConnector(ABC):
    def __init__(self, store: FeatureStore):
        """
        :param store: Applies feature state to the engine and the cache, and
                      emits the events that follow.
        """
        self._store = store

    @abstractmethod
    def start(self):
        pass

    @abstractmethod
    def stop(self):
        pass
