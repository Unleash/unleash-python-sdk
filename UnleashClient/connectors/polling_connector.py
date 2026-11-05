from UnleashClient._feature_store import _FeatureStore
from UnleashClient._scheduler import _ScheduledJob, _Scheduler
from UnleashClient._unleash_api_client import _UnleashApiClient
from UnleashClient.config import PollingOptions

from .base_connector import BaseConnector


class PollingConnector(BaseConnector):
    """Keeps feature state fresh by fetching it on a fixed interval."""

    def __init__(
        self,
        store: _FeatureStore,
        scheduler: _Scheduler,
        api_client: _UnleashApiClient,
        options: PollingOptions,
    ):
        """
        :param api_client: Performs the fetch against the Unleash server.
        :param options: How often to fetch, and which project to fetch.
        """
        super().__init__(store)
        self.scheduler: _Scheduler = scheduler
        self.api_client: _UnleashApiClient = api_client
        self.options: PollingOptions = options
        self.job: _ScheduledJob = None

    def _fetch_and_load(self) -> None:
        result = self.api_client.fetch_features(
            self._store.cached_etag, options=self.options
        )

        self._store.apply_fetched(result.raw_state, result.etag)

    def start(self) -> None:
        self._fetch_and_load()

        self.job = self.scheduler.every(
            interval_seconds=self.options.interval,
            jitter_seconds=self.options.jitter,
            fn=self._fetch_and_load,
        )

    def stop(self) -> None:
        self.scheduler.cancel(self.job)
        self.job = None
