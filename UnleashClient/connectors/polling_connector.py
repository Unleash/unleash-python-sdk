from typing import Optional

from UnleashClient._scheduler import _ScheduledJob, _Scheduler
from UnleashClient.store import FeatureStore
from UnleashClient.transport import Transport

from .base_connector import BaseConnector


class PollingConnector(BaseConnector):
    """Keeps feature state fresh by fetching it on a fixed interval."""

    def __init__(
        self,
        store: FeatureStore,
        scheduler: _Scheduler,
        transport: Transport,
        refresh_interval: int = 15,
        refresh_jitter: Optional[int] = None,
    ):
        """
        :param transport: Performs the fetch against the Unleash server.
        :param refresh_interval: Seconds between fetches.
        :param refresh_jitter: Maximum seconds to randomly offset each fetch by, or
                               None for no jitter.
        """
        super().__init__(store)
        self.scheduler: _Scheduler = scheduler
        self.transport: Transport = transport
        self.refresh_interval = refresh_interval
        self.refresh_jitter = refresh_jitter
        self.job: _ScheduledJob = None

    def _fetch_and_load(self) -> None:
        result = self.transport.fetch_features(self._store.cached_etag)

        self._store.apply_fetched(result.raw_state, result.etag)

    def start(self) -> None:
        self._fetch_and_load()

        self.job = self.scheduler.every(
            interval_seconds=self.refresh_interval,
            jitter_seconds=self.refresh_jitter,
            fn=self._fetch_and_load,
        )

    def stop(self) -> None:
        self.scheduler.cancel(self.job)
        self.job = None
