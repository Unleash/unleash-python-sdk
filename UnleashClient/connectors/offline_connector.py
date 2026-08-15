from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from UnleashClient.store import FeatureStore

from .base_connector import BaseConnector


class OfflineConnector(BaseConnector):
    def __init__(
        self,
        store: FeatureStore,
        scheduler: BackgroundScheduler,
        scheduler_executor: str = "default",
        refresh_interval: int = 15,
        refresh_jitter: Optional[int] = None,
    ):
        super().__init__(store)
        self.scheduler = scheduler
        self.scheduler_executor = scheduler_executor
        self.refresh_interval = refresh_interval
        self.refresh_jitter = refresh_jitter
        self.job = None

    def start(self):
        self._store.load_from_cache()

        self.job = self.scheduler.add_job(
            self._store.load_from_cache,
            trigger=IntervalTrigger(
                seconds=self.refresh_interval, jitter=self.refresh_jitter
            ),
            executor=self.scheduler_executor,
        )

        # load_from_cache() returns without emitting when the cache is empty,
        # therefore, and an offline client still needs READY.
        # One could argue if `load_from_cache` should emit READY even when the cache is empty.
        self._store.emit_ready()

    def stop(self):
        if self.job:
            self.job.remove()
            self.job = None
