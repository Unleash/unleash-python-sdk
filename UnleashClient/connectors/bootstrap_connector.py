from UnleashClient.store import FeatureStore

from .base_connector import BaseConnector


class BootstrapConnector(BaseConnector):
    def __init__(
        self,
        store: FeatureStore,
    ):
        super().__init__(store)
        self.job = None

    # TODO: the client hands this connector a store with no EventDispatcher, so
    # bootstrapping does not emit a READY event. Bootstrapped clients only see
    # READY once initialize_client() builds a polling, streaming or offline
    # connector. Passing the dispatcher here would emit READY from
    # ``UnleashClient``'s constructor, ahead of initialize_client(); moving this
    # start() call into initialize_client() is the prerequisite for that change.
    def start(self):
        self._store.load_from_cache()

    def stop(self):
        pass
