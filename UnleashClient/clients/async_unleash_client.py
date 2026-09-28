"""
Asynchronous Unleash client. Requires the optional ``aiohttp`` dependency:
``pip install UnleashClient[async]``.
"""

import asyncio
import warnings
from datetime import datetime, timezone
from typing import Callable, Optional

from yggdrasil_engine.engine import UnleashEngine

from UnleashClient._async_scheduler import _AsyncScheduler
from UnleashClient._async_transport import _AsyncTransport
from UnleashClient._context import _ContextEnricher
from UnleashClient._evaluator import _Evaluator
from UnleashClient._event_dispatcher import _EventDispatcher
from UnleashClient._feature_store import _FeatureStore
from UnleashClient._headers import _HeaderFactory
from UnleashClient._instance_registry import _get_instance_registry
from UnleashClient._metrics import _AsyncMetricsReporter
from UnleashClient._payloads import _build_register_payload
from UnleashClient.cache import BaseCache, FileCache
from UnleashClient.clients.unleash_client import _RunState
from UnleashClient.config import ExperimentalMode, UnleashConfig
from UnleashClient.connectors._async_connector import _AsyncPollingConnector
from UnleashClient.constants import (
    ETAG,
    METRIC_LAST_SENT_TIME,
    REQUEST_RETRIES,
    REQUEST_TIMEOUT,
)
from UnleashClient.events import BaseEvent
from UnleashClient.impact_metrics import ImpactMetrics
from UnleashClient.utils import LOGGER, InstanceAllowType

_NOT_IMPLEMENTED = (
    "AsyncUnleashClient is a work in progress and does not support this yet. "
    "Use UnleashClient."
)


class AsyncUnleashClient:
    """
    An asyncio-native client for the Unleash feature toggle system.

    The client keeps feature state fresh by polling the Unleash server on the
    event loop it was initialized on, and reports metrics on the same loop.
    Streaming, offline mode and bootstrapping are not supported.
    Flag evaluation is not implemented yet: :meth:`is_enabled`,
    :meth:`get_variant` and :meth:`feature_definitions` raise
    :class:`NotImplementedError`.

    Example::

        async with AsyncUnleashClient(
            url="https://unleash.example.com/api",
            app_name="my-app",
            custom_headers={"Authorization": "<API token>"},
        ) as client:
            client.impact_metrics.define_counter("purchases", "Number of purchases")
            client.impact_metrics.increment_counter("purchases")
    """

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
        multiple_instance_mode: InstanceAllowType = InstanceAllowType.WARN,
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
            custom_strategies=custom_strategies,
        )
        self._enricher: _ContextEnricher = _ContextEnricher(self._config)
        self._headers: _HeaderFactory = _HeaderFactory(self._config)

        self._event_dispatcher: Optional[_EventDispatcher] = (
            _EventDispatcher(event_callback) if event_callback is not None else None
        )

        _get_instance_registry().register(
            identifier=self._config.instance_identifier, mode=multiple_instance_mode
        )

        self._engine: UnleashEngine = UnleashEngine()
        self.impact_metrics: ImpactMetrics = ImpactMetrics(
            self._engine,
            self._config.app_name,
            self._config.impact_metrics_environment,
        )
        self._cache: BaseCache = cache or FileCache(
            self._config.app_name, directory=cache_directory
        )
        self._store: _FeatureStore = _FeatureStore(
            engine=self._engine, cache=self._cache, events=self._event_dispatcher
        )
        self._evaluator: _Evaluator = _Evaluator(
            engine=self._engine,
            enricher=self._enricher,
            config=self._config,
            events=self._event_dispatcher,
        )
        self._transport: _AsyncTransport = _AsyncTransport(self._config, self._headers)
        self._scheduler: _AsyncScheduler = _AsyncScheduler()
        self._metrics: _AsyncMetricsReporter = _AsyncMetricsReporter(
            config=self._config,
            transport=self._transport,
            scheduler=self._scheduler,
            engine=self._engine,
            impact_metrics=self.impact_metrics,
        )
        self._connector: Optional[_AsyncPollingConnector] = None
        self._run_state: _RunState = _RunState.UNINITIALIZED
        self._starting: bool = False
        self._closed: bool = False

    @property
    def is_initialized(self) -> bool:
        return self._run_state == _RunState.INITIALIZED

    def is_enabled(
        self,
        feature_name: str,
        context: Optional[dict] = None,
        fallback_function: Callable = None,
    ) -> bool:
        """
        Checks if a feature toggle is enabled.

        Notes:

        * A toggle the client does not know, which is every toggle before the
          client has fetched state, resolves to ``fallback_function``'s answer,
          or to false when no fallback function is given.

        :param feature_name: Name of the feature
        :param context: Dictionary with context (e.g. IPs, email) for feature toggle.
        :param fallback_function: Allows users to provide a custom function to set default value.
        :return: Feature flag result
        """
        raise NotImplementedError(_NOT_IMPLEMENTED)

    def get_variant(self, feature_name: str, context: Optional[dict] = None) -> dict:
        """
        Checks if a feature toggle is enabled. If so, return variant.

        Notes:

        * A toggle the client does not know resolves to the disabled variant.

        :param feature_name: Name of the feature
        :param context: Dictionary with context (e.g. IPs, email) for feature toggle.
        :return: Variant and feature flag status.
        """
        raise NotImplementedError(_NOT_IMPLEMENTED)

    def feature_definitions(self) -> dict:
        """
        Returns a dict containing all feature definitions known to the SDK at the time of calling.
        Normally this would be a pared down version of the response from the Unleash API but this
        may also be a result from bootstrapping or loading from backup.

        Example response:

        {
            "feature1": {
                "project": "default",
                "type": "release",
            }
        }
        """
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def initialize_client(self, fetch_toggles: bool = True) -> None:
        """
        Initializes the client and starts communication with the Unleash server.

        This kicks off:

        * Client registration
        * Loading the cached feature state
        * Feature polling, every ``refresh_interval`` seconds
        * Metrics reporting, every ``metrics_interval`` seconds

        Returns without waiting for the server's feature state. The first fetch
        runs one ``refresh_interval`` after this returns, and until then the
        client holds the cached state.

        Calling it again, or after :meth:`destroy`, warns and does nothing.

        This is done automatically when the client is used as an async context
        manager:

        .. code-block:: python

            async with AsyncUnleashClient(
                url="https://foo.bar",
                app_name="myClient1",
                instance_id="myinstanceid",
            ) as client:
                pass

        :param fetch_toggles: Accepted for parity with :class:`UnleashClient`. It
                              has no effect: the client always polls.
        :raises aiohttp.InvalidURL: If registration is enabled and the URL is invalid.
        :raises ValueError: If a custom strategy is invalid.
        """
        if self._closed or self._starting or self._run_state > _RunState.UNINITIALIZED:
            warnings.warn(
                "Attempted to initialize an Unleash Client instance that has already been initialized."
            )
            return

        self._starting = True
        try:
            self._cache.mset(
                {METRIC_LAST_SENT_TIME: datetime.now(timezone.utc), ETAG: ""}
            )

            if self._config.custom_strategies:
                self._engine.register_custom_strategies(self._config.custom_strategies)

            if not self._config.disable_registration:
                await self._transport.register(
                    _build_register_payload(
                        self._config, self._config.custom_strategies
                    )
                )

            if self._closed:
                return

            self._connector = _AsyncPollingConnector(
                store=self._store,
                transport=self._transport,
                refresh_interval=self._config.refresh_interval,
                refresh_jitter=self._config.refresh_jitter,
            )
            await self._connector.start()

            if not self._config.disable_metrics:
                self._metrics.start()
                self._scheduler.start()

            self._run_state = _RunState.INITIALIZED
        except Exception as excep:
            LOGGER.warning(
                "Exception during AsyncUnleashClient initialization: %s", excep
            )
            raise
        finally:
            self._starting = False

    async def destroy(self) -> None:
        """
        Gracefully shuts down the client: stops polling, sends the metrics
        collected since the last send and closes the connection to the server.

        For cache teardown:

        * Default disk-backed FileCache instances are preserved on disk.
        * Custom non-FileCache implementations will have ``destroy()`` called.

        Calling it more than once does nothing.
        """
        if self._closed:
            return
        self._closed = True
        self._run_state = _RunState.SHUTDOWN

        if self._connector is not None:
            await self._connector.stop()

        await self._metrics.stop()

        try:
            await self._scheduler.shutdown()
        except Exception as exc:
            LOGGER.warning("Exception during scheduler teardown: %s", exc)

        await self._transport.aclose()

        if not isinstance(self._cache, FileCache):
            try:
                self._cache.destroy()
            except Exception as exc:
                LOGGER.warning("Exception during cache teardown: %s", exc)

        if self._event_dispatcher is not None:
            await asyncio.get_running_loop().run_in_executor(
                None, self._event_dispatcher.close
            )

    async def __aenter__(self) -> "AsyncUnleashClient":
        await self.initialize_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        await self.destroy()
        return False
