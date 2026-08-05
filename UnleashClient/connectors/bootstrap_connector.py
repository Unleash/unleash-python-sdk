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
        self.job = None

    # TODO: this connector is never given an EventDispatcher, so bootstrapping
    # does not emit a READY event. Bootstrapped clients only see READY once
    # initialize_client() builds a polling, streaming or offline connector.
    #
    # This call to start() might need to be moved from ``UnleashClient``'s
    # constructor to ``initialize_client``.
    def start(self):
        self.load_features()

    def stop(self):
        pass
