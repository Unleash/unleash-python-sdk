from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from UnleashClient.api import get_feature_toggles
from UnleashClient.store import FeatureStore

from .base_connector import BaseConnector


class PollingConnector(BaseConnector):
    def __init__(
        self,
        store: FeatureStore,
        scheduler: BackgroundScheduler,
        url: str,
        app_name: str,
        instance_id: str,
        headers: Optional[dict] = None,
        custom_options: Optional[dict] = None,
        request_timeout: int = 30,
        request_retries: int = 3,
        project: Optional[str] = None,
        scheduler_executor: str = "default",
        refresh_interval: int = 15,
        refresh_jitter: Optional[int] = None,
    ):
        super().__init__(store)
        self.scheduler = scheduler
        self.url = url
        self.app_name = app_name
        self.instance_id = instance_id
        self.headers = headers or {}
        self.custom_options = custom_options or {}
        self.request_timeout = request_timeout
        self.request_retries = request_retries
        self.project = project
        self.scheduler_executor = scheduler_executor
        self.refresh_interval = refresh_interval
        self.refresh_jitter = refresh_jitter
        self.job = None

    def _fetch_and_load(self):
        state, etag = get_feature_toggles(
            url=self.url,
            app_name=self.app_name,
            instance_id=self.instance_id,
            headers=self.headers,
            custom_options=self.custom_options,
            request_timeout=self.request_timeout,
            request_retries=self.request_retries,
            project=self.project,
            cached_etag=self._store.cached_etag,
        )

        self._store.apply_fetched(state, etag)

    def start(self):
        self._fetch_and_load()

        self.job = self.scheduler.add_job(
            self._fetch_and_load,
            trigger=IntervalTrigger(
                seconds=self.refresh_interval,
                jitter=self.refresh_jitter,
            ),
            executor=self.scheduler_executor,
        )

    def stop(self):
        if self.job:
            self.job.remove()
            self.job = None
