from yggdrasil_engine.engine import UnleashEngine

from UnleashClient.cache import BaseCache
from UnleashClient.connectors.hydration import hydrate_engine

from .base_sync_connector import BaseSyncConnector


class BootstrapConnector(BaseSyncConnector):
    def __init__(
        self,
        engine: UnleashEngine,
        cache: BaseCache,
    ):
        self.engine = engine
        self.cache = cache
        self.job = None

    def start(self):
        hydrate_engine(self.cache, self.engine, None)

    def stop(self):
        pass
