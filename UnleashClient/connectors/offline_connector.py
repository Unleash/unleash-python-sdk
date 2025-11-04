from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from yggdrasil_engine.engine import UnleashEngine

from UnleashClient.cache import BaseCache
from UnleashClient.connectors.hydration import hydrate_engine

from .base_sync_connector import BaseSyncConnector


class OfflineConnector(BaseSyncConnector):
    def __init__(
        self,
        engine: UnleashEngine,
        cache: BaseCache,
        scheduler: BackgroundScheduler,
        scheduler_executor: str = "default",
        refresh_interval: int = 15,
        refresh_jitter: int = None,
        ready_callback: Callable = None,
    ):
        self.engine = engine
        self.cache = cache
        self.ready_callback = ready_callback
        self.scheduler = scheduler
        self.scheduler_executor = scheduler_executor
        self.refresh_interval = refresh_interval
        self.refresh_jitter = refresh_jitter
        self.job = None

    def hydrate(self):
        hydrate_engine(self.cache, self.engine, self.ready_callback)

    def start(self):
        self.hydrate()

        self.job = self.scheduler.add_job(
            self.hydrate,
            trigger=IntervalTrigger(
                seconds=self.refresh_interval, jitter=self.refresh_jitter
            ),
            executor=self.scheduler_executor,
        )

        if self.ready_callback:
            self.ready_callback()

    def stop(self):
        if self.job:
            self.job.remove()
            self.job = None
