# pylint: disable=invalid-name
import asyncio
import random
import uuid
import warnings
from contextlib import suppress
from dataclasses import asdict
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any, Callable, Optional

from yggdrasil_engine.engine import UnleashEngine

from ..api.asynchronous import register_client
from ..asynchronous.cache import AsyncBaseCache, AsyncFileCache
from ..asynchronous.loader import check_cache
from ..constants import (
    APPLICATION_HEADERS,
    DISABLED_VARIATION,
    ETAG,
    METRIC_LAST_SENT_TIME,
    REQUEST_RETRIES,
    REQUEST_TIMEOUT,
    SDK_NAME,
    SDK_VERSION,
)
from ..events import (
    BaseEvent,
    UnleashEvent,
    UnleashEventType,
    UnleashReadyEvent,
)
from ..periodic_tasks.asynchronous import (
    aggregate_and_send_metrics,
    fetch_and_load_features,
)
from ..utils import LOGGER, InstanceAllowType, InstanceCounter

try:
    from typing import Literal, TypedDict
except ImportError:
    from typing_extensions import Literal, TypedDict  # type: ignore

INSTANCES = InstanceCounter()
_BASE_CONTEXT_FIELDS = [
    "userId",
    "sessionId",
    "environment",
    "appName",
    "currentTime",
    "remoteAddress",
    "properties",
]


class _RunState(IntEnum):
    UNINITIALIZED = 0
    INITIALIZED = 1
    SHUTDOWN = 2


class ExperimentalMode(TypedDict, total=False):
    type: Literal["polling"]


def build_ready_callback(
    event_callback: Optional[Callable[[BaseEvent], None]] = None,
) -> Optional[Callable]:
    """
    Builds a callback function that can be used to notify when the Unleash client is ready.
    """

    if not event_callback:
        return None

    already_fired = False

    async def ready_callback() -> None:
        """
        Callback function to notify that the Unleash client is ready.
        This will only call the event_callback once.
        """
        nonlocal already_fired
        if already_fired:
            return
        if event_callback:
            event = UnleashReadyEvent(
                event_type=UnleashEventType.READY,
                event_id=uuid.uuid4(),
            )
            already_fired = True
            event_callback(event)

    return ready_callback


# pylint: disable=dangerous-default-value
class AsyncUnleashClient:
    """
    An async client for the Unleash feature toggle system.

    :param url: URL of the unleash server, required.
    :param app_name: Name of the application using the unleash client, required.
    :param environment: Name of the environment using the unleash client, optional & defaults to "default".
    :param instance_id: Unique identifier for unleash client instance, optional & defaults to "unleash-python-sdk"
    :param refresh_interval: Provisioning refresh interval in seconds, optional & defaults to 15 seconds
    :params request_timeout: Timeout for requests to unleash server in seconds, optional & defaults to 30 seconds
    :params request_retries: Number of retries for requests to unleash server, optional & defaults to 3
    :param refresh_jitter: Provisioning refresh interval jitter in seconds, optional & defaults to None
    :param metrics_interval: Metrics refresh interval in seconds, optional & defaults to 60 seconds
    :param metrics_jitter: Metrics refresh interval jitter in seconds, optional & defaults to None
    :param disable_metrics: Disables sending metrics to unleash server, optional & defaults to false.
    :param disable_registration: Disables registration with unleash server, optional & defaults to false.
    :param custom_headers: Default headers to send to unleash server, optional & defaults to empty.
    :param custom_options: Default requests parameters, optional & defaults to empty.  Can be used to skip SSL verification.
    :param custom_strategies: Dictionary of custom strategy names : custom strategy objects.
    :param cache_directory: Location of the cache directory. When unset, FCache will determine the location.
    :param verbose_log_level: Numerical log level (https://docs.python.org/3/library/logging.html#logging-levels) for cases where checking a feature flag fails.
    :param cache: Custom cache implementation that extends AsyncBaseCache.  When unset, AsyncUnleashClient will use AsyncFileCache.
    :param multiple_instance_mode: Determines how multiple instances being instantiated is handled by the SDK
    :param event_callback: Function to call if impression events are enabled.
    :param experimental_mode: Optional dict to configure mode. Use {"type": "polling"} (default).
    """

    def __init__(
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
        cache: Optional[AsyncBaseCache] = None,
        multiple_instance_mode: InstanceAllowType = InstanceAllowType.WARN,
        event_callback: Optional[Callable[[BaseEvent], None]] = None,
        experimental_mode: Optional[ExperimentalMode] = None,
    ) -> None:
        custom_headers = custom_headers or {}
        custom_options = custom_options or {}
        custom_strategies = custom_strategies or {}

        # Configuration
        self.unleash_url = url.rstrip("/")
        self.unleash_app_name = app_name
        self.unleash_environment = environment
        self.unleash_instance_id = instance_id
        self._connection_id = str(uuid.uuid4())
        self.unleash_refresh_interval = refresh_interval
        self.unleash_request_timeout = request_timeout
        self.unleash_request_retries = request_retries
        self.unleash_refresh_jitter = (
            int(refresh_jitter) if refresh_jitter is not None else None
        )
        self.unleash_metrics_interval = metrics_interval
        self.unleash_metrics_jitter = (
            int(metrics_jitter) if metrics_jitter is not None else None
        )
        self.unleash_disable_metrics = disable_metrics
        self.unleash_disable_registration = disable_registration
        self.unleash_custom_headers = custom_headers
        self.unleash_custom_options = custom_options
        self.unleash_static_context = {
            "appName": self.unleash_app_name,
            "environment": self.unleash_environment,
        }
        self.unleash_project_name = project_name
        self.unleash_verbose_log_level = verbose_log_level
        self.unleash_event_callback = event_callback
        self._ready_callback = build_ready_callback(event_callback)
        self.connector_mode: ExperimentalMode = experimental_mode or {"type": "polling"}
        self._closed = asyncio.Event()

        self._do_instance_check(multiple_instance_mode)

        # Class objects
        self.engine = UnleashEngine()

        self.cache = cache or AsyncFileCache(
            self.unleash_app_name, directory=cache_directory
        )
        self.unleash_bootstrapped = self.cache.bootstrapped

        self.metrics_headers: dict = {}

        if custom_strategies:
            self.engine.register_custom_strategies(custom_strategies)

        self.strategy_mapping = {**custom_strategies}

        # Client status
        self._run_state = _RunState.UNINITIALIZED

        # Background tasks
        self._fetch_task: Optional[asyncio.Task] = None
        self._metrics_task: Optional[asyncio.Task] = None

    @property
    def unleash_metrics_interval_str_millis(self) -> str:
        return str(self.unleash_metrics_interval * 1000)

    @property
    def connection_id(self):
        return self._connection_id

    @property
    def is_initialized(self):
        return self._run_state == _RunState.INITIALIZED

    async def initialize_client(self, fetch_toggles: bool = True) -> None:
        """
        Initializes client and starts communication with central unleash server(s) asynchronously.

        This kicks off:

        * Client registration
        * Provisioning poll
        * Stats poll

        If `fetch_toggles` is `False`, feature toggle polling will be turned off
        and instead the client will only load features from the cache.

        This will raise an exception on registration if the URL is invalid.

        .. code-block:: python

            async with AsyncUnleashClient(
                url="https://foo.bar",
                app_name="myClient1",
                instance_id="myinstanceid"
                ) as client:
                pass
        """
        # Only perform initialization steps if client is not initialized.
        if self._closed.is_set() or self._run_state > _RunState.UNINITIALIZED:
            warnings.warn(
                "Attempted to initialize an Unleash Client instance that has already been initialized."
            )
            return
        try:
            await self.cache.mset(
                {METRIC_LAST_SENT_TIME: datetime.now(timezone.utc), ETAG: ""}
            )

            # Load from cache if available
            if self.unleash_bootstrapped or await check_cache(self.cache, self.engine):
                if self._ready_callback:
                    await self._ready_callback()

            base_headers = {
                **self.unleash_custom_headers,
                **APPLICATION_HEADERS,
                "unleash-connection-id": self.connection_id,
                "unleash-appname": self.unleash_app_name,
                "unleash-instanceid": self.unleash_instance_id,
                "unleash-sdk": f"{SDK_NAME}:{SDK_VERSION}",
            }

            # Register app
            if not self.unleash_disable_registration:
                await register_client(
                    self.unleash_url,
                    self.unleash_app_name,
                    self.unleash_instance_id,
                    self.connection_id,
                    self.unleash_metrics_interval,
                    base_headers,
                    self.unleash_custom_options,
                    self.strategy_mapping,
                    self.unleash_request_timeout,
                )

            if fetch_toggles:
                # Start periodic fetch task
                self._fetch_task = asyncio.create_task(
                    self._periodic_fetch(base_headers)
                )

            if not self.unleash_disable_metrics:
                self.metrics_headers = {
                    **base_headers,
                    "unleash-interval": self.unleash_metrics_interval_str_millis,
                }
                # Start periodic metrics task
                self._metrics_task = asyncio.create_task(self._periodic_metrics())

            self._run_state = _RunState.INITIALIZED

        except Exception as excep:
            # Log exceptions during initialization.  is_initialized will remain false.
            LOGGER.warning(
                "Exception during AsyncUnleashClient initialization: %s", excep
            )
            raise excep

    async def _periodic_fetch(self, headers: dict) -> None:
        """Periodically fetches feature toggles"""
        while not self._closed.is_set():
            # Create fetch task
            fetch_task = asyncio.create_task(
                fetch_and_load_features(
                    url=self.unleash_url,
                    app_name=self.unleash_app_name,
                    instance_id=self.unleash_instance_id,
                    headers=headers,
                    custom_options=self.unleash_custom_options,
                    request_timeout=self.unleash_request_timeout,
                    request_retries=self.unleash_request_retries,
                    cache=self.cache,
                    engine=self.engine,
                    project=self.unleash_project_name,
                )
            )

            try:
                # Wait for fetch to complete or for shutdown signal
                closed_task = asyncio.create_task(self._closed.wait())
                await asyncio.wait(
                    [fetch_task, closed_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # If closed event was set, cancel the fetch task
                if self._closed.is_set():
                    if not fetch_task.done():
                        fetch_task.cancel()
                        with suppress(asyncio.CancelledError):
                            await fetch_task
                    break
                if not closed_task.done():
                    closed_task.cancel()

                # Fetch completed successfully
                if self._ready_callback and self._run_state == _RunState.INITIALIZED:
                    await self._ready_callback()

            except Exception as exc:
                LOGGER.exception("Error in periodic fetch: %s", exc)

            # Apply jitter if configured
            interval = self.unleash_refresh_interval
            if self.unleash_refresh_jitter:
                interval += int(random.uniform(0, self.unleash_refresh_jitter))

            # Wait for interval or until closed
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._closed.wait(), timeout=interval)

    async def _periodic_metrics(self) -> None:
        """Periodically sends metrics"""
        while not self._closed.is_set():
            try:
                await aggregate_and_send_metrics(
                    url=self.unleash_url,
                    app_name=self.unleash_app_name,
                    connection_id=self.connection_id,
                    instance_id=self.unleash_instance_id,
                    headers=self.metrics_headers,
                    custom_options=self.unleash_custom_options,
                    request_timeout=self.unleash_request_timeout,
                    engine=self.engine,
                )
            except Exception as exc:
                LOGGER.exception("Error in periodic metrics: %s", exc)

            if self._closed.is_set():
                break

            # Apply jitter if configured
            interval = self.unleash_metrics_interval
            if self.unleash_metrics_jitter:
                interval += int(random.uniform(0, self.unleash_metrics_jitter))

            # Wait for interval or until closed
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._closed.wait(), timeout=interval)

    def feature_definitions(self) -> dict:
        """
        Returns a dict containing all feature definitions known to the SDK at the time of calling.
        """
        toggles = self.engine.list_known_toggles()
        return {
            toggle.name: {"type": toggle.type, "project": toggle.project}
            for toggle in toggles
        }

    async def destroy(self) -> None:
        """
        Gracefully shuts down the Unleash client by stopping tasks and deleting the cache.
        """
        if self._closed.is_set():
            return
        self._closed.set()
        self._run_state = _RunState.SHUTDOWN

        # Wait for background tasks to complete gracefully
        tasks = []
        if self._fetch_task:
            tasks.append(self._fetch_task)
        if self._metrics_task:
            tasks.append(self._metrics_task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        try:
            await self.cache.destroy()
        except Exception as exc:
            LOGGER.warning("Exception during cache teardown: %s", exc)

    @staticmethod
    def _get_fallback_value(
        fallback_function: Callable, feature_name: str, context: dict
    ) -> bool:
        if fallback_function:
            fallback_value = fallback_function(feature_name, context)
        else:
            fallback_value = False

        return fallback_value

    # pylint: disable=broad-except
    def is_enabled(
        self,
        feature_name: str,
        context: Optional[dict] = None,
        fallback_function: Callable = None,
    ) -> bool:
        """
        Checks if a feature toggle is enabled.

        Notes:

        * If client hasn't been initialized yet or an error occurs, flag will default to false.

        :param feature_name: Name of the feature
        :param context: Dictionary with context (e.g. IPs, email) for feature toggle.
        :param fallback_function: Allows users to provide a custom function to set default value.
        :return: Feature flag result
        """
        context = self._safe_context(context)
        feature_enabled = self.engine.is_enabled(feature_name, context)

        if feature_enabled is None:
            feature_enabled = self._get_fallback_value(
                fallback_function, feature_name, context
            )

        self.engine.count_toggle(feature_name, feature_enabled)
        try:
            if (
                self.unleash_event_callback
                and self.engine.should_emit_impression_event(feature_name)
            ):
                event = UnleashEvent(
                    event_type=UnleashEventType.FEATURE_FLAG,
                    event_id=uuid.uuid4(),
                    context=context,
                    enabled=feature_enabled,
                    feature_name=feature_name,
                )

                self.unleash_event_callback(event)
        except Exception as excep:
            LOGGER.log(
                self.unleash_verbose_log_level,
                "Error in event callback: %s",
                excep,
            )

        return feature_enabled

    # pylint: disable=broad-except
    def get_variant(self, feature_name: str, context: Optional[dict] = None) -> dict:
        """
        Checks if a feature toggle is enabled.  If so, return variant.

        Notes:

        * If client hasn't been initialized yet or an error occurs, flag will default to false.

        :param feature_name: Name of the feature
        :param context: Dictionary with context (e.g. IPs, email) for feature toggle.
        :return: Variant and feature flag status.
        """
        context = self._safe_context(context)
        variant = self._resolve_variant(feature_name, context)

        if not variant:
            if self.unleash_bootstrapped or self.is_initialized:
                LOGGER.log(
                    self.unleash_verbose_log_level,
                    "Attempted to get feature flag/variation %s, but client wasn't initialized!",
                    feature_name,
                )
            variant = DISABLED_VARIATION

        self.engine.count_variant(feature_name, variant["name"])
        self.engine.count_toggle(feature_name, variant["feature_enabled"])

        if self.unleash_event_callback and self.engine.should_emit_impression_event(
            feature_name
        ):
            try:
                event = UnleashEvent(
                    event_type=UnleashEventType.VARIANT,
                    event_id=uuid.uuid4(),
                    context=context,
                    enabled=bool(variant["enabled"]),
                    feature_name=feature_name,
                    variant=str(variant["name"]),
                )

                self.unleash_event_callback(event)
            except Exception as excep:
                LOGGER.log(
                    self.unleash_verbose_log_level,
                    "Error in event callback: %s",
                    excep,
                )

        return variant

    def _safe_context(self, context: Optional[dict]) -> dict:
        new_context: dict[str, Any] = self.unleash_static_context.copy()
        new_context.update(context or {})

        if "currentTime" not in new_context:
            new_context["currentTime"] = datetime.now(timezone.utc).isoformat()

        safe_properties = self._extract_properties(new_context)
        safe_properties = {
            k: self._safe_context_value(v) for k, v in safe_properties.items()
        }
        safe_context: dict[str, Any] = {
            k: self._safe_context_value(v)
            for k, v in new_context.items()
            if k != "properties"
        }

        safe_context["properties"] = safe_properties

        return safe_context

    def _extract_properties(self, context: dict) -> dict:
        properties = context.get("properties", {})
        extracted_fields = {
            k: v for k, v in context.items() if k not in _BASE_CONTEXT_FIELDS
        }
        extracted_fields.update(properties)
        return extracted_fields

    def _safe_context_value(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, (int, float)):
            return str(value)
        return str(value)

    def _resolve_variant(self, feature_name: str, context: dict) -> Optional[dict]:
        """
        Resolves a feature variant.
        """
        variant = self.engine.get_variant(feature_name, context)
        if variant:
            return {k: v for k, v in asdict(variant).items() if v is not None}
        return None

    def _do_instance_check(self, multiple_instance_mode: InstanceAllowType) -> None:
        identifier = self.__get_identifier()
        if identifier in INSTANCES:
            msg = f"You already have {INSTANCES.count(identifier)} instance(s) configured for this config: {identifier}, please double check the code where this client is being instantiated."
            if multiple_instance_mode == InstanceAllowType.BLOCK:
                raise Exception(msg)  # pylint: disable=broad-exception-raised
            if multiple_instance_mode == InstanceAllowType.WARN:
                LOGGER.error(msg)
        INSTANCES.increment(identifier)

    def __get_identifier(self) -> str:
        api_key = (
            self.unleash_custom_headers.get("Authorization")
            if self.unleash_custom_headers is not None
            else None
        )
        return f"apiKey:{api_key} appName:{self.unleash_app_name} instanceId:{self.unleash_instance_id}"

    async def __aenter__(self) -> "AsyncUnleashClient":
        await self.initialize_client()
        return self

    async def __aexit__(self, *args, **kwargs) -> bool:
        await self.destroy()
        return False


__all__ = ["AsyncUnleashClient", "AsyncBaseCache", "AsyncFileCache"]
