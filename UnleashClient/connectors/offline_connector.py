from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from yggdrasil_engine.engine import UnleashEngine

from UnleashClient.cache import BaseCache
from UnleashClient.events import EventDispatcher

from .base_connector import BaseConnector


class OfflineConnector(BaseConnector):
    def __init__(
        self,
        engine: UnleashEngine,
        cache: BaseCache,
        scheduler: BackgroundScheduler,
        scheduler_executor: str = "default",
        refresh_interval: int = 15,
        refresh_jitter: int = None,
        events: Optional[EventDispatcher] = None,
    ):
        super().__init__(engine, cache, events)
        self.scheduler = scheduler
        self.scheduler_executor = scheduler_executor
        self.refresh_interval = refresh_interval
        self.refresh_jitter = refresh_jitter
        self.job = None

    def start(self):
        self.load_features()

        self.job = self.scheduler.add_job(
            self.load_features,
            trigger=IntervalTrigger(
                seconds=self.refresh_interval, jitter=self.refresh_jitter
            ),
            executor=self.scheduler_executor,
        )

        self.emit_ready()

    def stop(self):
        if self.job:
            self.job.remove()
            self.job = None
