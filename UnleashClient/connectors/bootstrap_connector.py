from yggdrasil_engine.engine import UnleashEngine

from UnleashClient.cache import BaseCache

from .base_connector import BaseConnector


class BootstrapConnector(BaseConnector):
    def __init__(
        self,
        engine: UnleashEngine,
        cache: BaseCache,
    ):
        super().__init__(engine, cache)
        self.engine = engine
        self.cache = cache
        self.job = None

    def start(self):
        self.load_features()

    def stop(self):
        pass
