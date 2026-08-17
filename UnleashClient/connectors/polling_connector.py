from typing import Optional

from UnleashClient.api import get_feature_toggles
from UnleashClient.scheduler import ScheduledJob, Scheduler
from UnleashClient.store import FeatureStore

from .base_connector import BaseConnector


class PollingConnector(BaseConnector):
    def __init__(
        self,
        store: FeatureStore,
        scheduler: Scheduler,
        url: str,
        app_name: str,
        instance_id: str,
        headers: Optional[dict] = None,
        custom_options: Optional[dict] = None,
        request_timeout: int = 30,
        request_retries: int = 3,
        project: Optional[str] = None,
        refresh_interval: int = 15,
        refresh_jitter: Optional[int] = None,
    ):
        """
        :param refresh_interval: Seconds between fetches.
        :param refresh_jitter: Maximum seconds to randomly offset each fetch by, or
                               None for no jitter.
        :param request_timeout: Seconds to wait for the features response.
        """
        super().__init__(store)
        self.scheduler: Scheduler = scheduler
        self.url = url
        self.app_name = app_name
        self.instance_id = instance_id
        self.headers = headers or {}
        self.custom_options = custom_options or {}
        self.request_timeout = request_timeout
        self.request_retries = request_retries
        self.project = project
        self.refresh_interval = refresh_interval
        self.refresh_jitter = refresh_jitter
        self.job: ScheduledJob = None

    def _fetch_and_load(self) -> None:
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
