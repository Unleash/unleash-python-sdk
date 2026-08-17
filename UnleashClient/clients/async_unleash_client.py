"""
Asynchronous Unleash client.

Work in progress.  This class currently only builds the collaborators it
shares with :class:`UnleashClient.clients.unleash_client.UnleashClient`; it
performs no network I/O and is not exported from the package root.  See
``docs/object-composition.md``.
"""

from typing import Callable, Optional

from yggdrasil_engine.engine import UnleashEngine

from UnleashClient.cache import BaseCache, FileCache
from UnleashClient.config import ExperimentalMode, UnleashConfig
from UnleashClient.constants import REQUEST_RETRIES, REQUEST_TIMEOUT
from UnleashClient.context import ContextEnricher
from UnleashClient.events import BaseEvent, EventDispatcher
from UnleashClient.headers import HeaderFactory
from UnleashClient.scheduler import Scheduler
from UnleashClient.store import FeatureStore

_NOT_IMPLEMENTED = (
    "AsyncUnleashClient is a work in progress and does not do anything yet. "
    "Use UnleashClient."
)


class AsyncUnleashClient:
    """An asyncio-native client for the Unleash feature toggle system."""

    def __init__(  # noqa: PLR0913, PLR0917
        self,
        url: str,
        app_name: str,
        environment: str = "default",
        instance_id: str = "unleash-python-sdk",
        refresh_interval: int = 15,
        refresh_jitter: Optional[int] = None,
        metrics_interval: int = 60,
        metrics_jitter: Optional[int] = None,
        disable_metrics: bool = False,
        disable_registration: bool = False,
        custom_headers: Optional[dict] = None,
        custom_options: Optional[dict] = None,
        request_timeout: int = REQUEST_TIMEOUT,
        request_retries: int = REQUEST_RETRIES,
        custom_strategies: Optional[dict] = None,
        cache_directory: Optional[str] = None,
        project_name: Optional[str] = None,
        verbose_log_level: int = 30,
        cache: Optional[BaseCache] = None,
        event_callback: Optional[Callable[[BaseEvent], None]] = None,
        experimental_mode: Optional[ExperimentalMode] = None,
        sdk_flavor: Optional[str] = None,
        sdk_flavor_version: Optional[str] = None,
    ) -> None:
        self._config: UnleashConfig = UnleashConfig(
            url=url,
            app_name=app_name,
            environment=environment,
            instance_id=instance_id,
            refresh_interval=refresh_interval,
            refresh_jitter=refresh_jitter,
            metrics_interval=metrics_interval,
            metrics_jitter=metrics_jitter,
            disable_metrics=disable_metrics,
            disable_registration=disable_registration,
            custom_headers=custom_headers,
            custom_options=custom_options,
            request_timeout=request_timeout,
            request_retries=request_retries,
            project_name=project_name,
            verbose_log_level=verbose_log_level,
            sdk_flavor=sdk_flavor,
            sdk_flavor_version=sdk_flavor_version,
            experimental_mode=experimental_mode,
        )
        self._enricher: ContextEnricher = ContextEnricher(self._config)
        self._headers: HeaderFactory = HeaderFactory(self._config)

        self._event_dispatcher: Optional[EventDispatcher] = (
            EventDispatcher(event_callback) if event_callback is not None else None
        )
        self._engine: UnleashEngine = UnleashEngine()
        self._cache: BaseCache = cache or FileCache(
            self._config.app_name, directory=cache_directory
        )
        self._store: FeatureStore = FeatureStore(
            engine=self._engine, cache=self._cache, events=self._event_dispatcher
        )
        self._scheduler: Scheduler = Scheduler()

    async def initialize_client(self) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def destroy(self) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def __aenter__(self) -> "AsyncUnleashClient":
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED)
