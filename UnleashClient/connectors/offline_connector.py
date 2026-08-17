from typing import Optional

from UnleashClient.scheduler import ScheduledJob, Scheduler
from UnleashClient.store import FeatureStore

from .base_connector import BaseConnector


class OfflineConnector(BaseConnector):
    def __init__(
        self,
        store: FeatureStore,
        scheduler: Scheduler,
        refresh_interval: int = 15,
        refresh_jitter: Optional[int] = None,
    ):
        """
        :param store: Applies feature state to the engine and the cache.
        :param scheduler: Runs the reload job.
        :param refresh_interval: Seconds between cache reloads.
        :param refresh_jitter: Maximum seconds to randomly offset each reload by, or
                               None for no jitter.
        """
        super().__init__(store)
        self.scheduler: Scheduler = scheduler
        self.refresh_interval = refresh_interval
        self.refresh_jitter = refresh_jitter
        self.job: ScheduledJob = None

    def start(self) -> None:
        self._store.load_from_cache()

        self.job = self.scheduler.every(
            interval_seconds=self.refresh_interval,
            jitter_seconds=self.refresh_jitter,
            fn=self._store.load_from_cache,
        )

        # load_from_cache() returns without emitting when the cache is empty,
        # therefore, and an offline client still needs READY.
        # One could argue if `load_from_cache` should emit READY even when the cache is empty.
        self._store.emit_ready()

    def stop(self) -> None:
        self.scheduler.cancel(self.job)
        self.job = None
