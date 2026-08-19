# pylint: disable=invalid-name
import random
import string
import threading
import uuid
import warnings
from dataclasses import asdict
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any, Callable, Dict, Optional

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.job import Job
from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import STATE_RUNNING, BaseScheduler
from apscheduler.triggers.interval import IntervalTrigger
from yggdrasil_engine.engine import UnleashEngine

from UnleashClient.api import register_client
from UnleashClient.cache import BaseCache, FileCache
from UnleashClient.config import (
    ExperimentalMode,
    UnleashConfig,
    redact_to_print_safely,
)
from UnleashClient.connectors import (
    BaseConnector,
    BootstrapConnector,
    OfflineConnector,
    PollingConnector,
    StreamingConnector,
)
from UnleashClient.constants import (
    APPLICATION_HEADERS,
    ETAG,
    METRIC_LAST_SENT_TIME,
    REQUEST_RETRIES,
    REQUEST_TIMEOUT,
    SDK_NAME,
    SDK_VERSION,
)
from UnleashClient.context import ContextEnricher
from UnleashClient.events import (
    BaseEvent,
    EventDispatcher,
    UnleashEvent,
    UnleashEventType,
    UnleashReadyEvent,
)
from UnleashClient.impact_metrics import ImpactMetrics
from UnleashClient.periodic_tasks import (
    aggregate_and_send_metrics,
)
from UnleashClient.utils import (
    LOGGER,
    InstanceAllowType,
    InstanceCounter,
)

INSTANCES = InstanceCounter()


class _RunState(IntEnum):
    UNINITIALIZED = 0
    INITIALIZED = 1
    SHUTDOWN = 2


def build_ready_callback(
    event_callback: Optional[Callable[[BaseEvent], None]] = None,
) -> Optional[Callable]:
    """
    Builds a callback function that can be used to notify when the Unleash client is ready.

    .. deprecated::
        READY is now emitted through :class:`UnleashClient.events.EventDispatcher`,
        which deduplicates it itself.  This helper is retained for backwards
        compatibility and is no longer used internally.
    """

    if not event_callback:
        return None

    already_fired = False

    def ready_callback() -> None:
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
class UnleashClient:
    """
    A client for the Unleash feature toggle system.

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
    :param cache: Custom cache implementation that extends UnleashClient.cache.BaseCache.  When unset, UnleashClient will use Fcache.
    :param scheduler: Custom APScheduler object.  Use this if you want to customize jobstore or executors.  When unset, UnleashClient will create it's own scheduler.
    :param scheduler_executor: Name of APSCheduler executor to use if using a custom scheduler.
    :param multiple_instance_mode: Determines how multiple instances being instantiated is handled by the SDK, when set to InstanceAllowType.BLOCK, the client constructor will fail when more than one instance is detected, when set to InstanceAllowType.WARN, multiple instances will be allowed but log a warning, when set to InstanceAllowType.SILENTLY_ALLOW, no warning or failure will be raised when instantiating multiple instances of the client. Defaults to InstanceAllowType.WARN
    :param event_callback: Function to call if impression events are enabled.  Called on a dedicated background thread, so it must not rely on thread local state from the caller.
    :param experimental_mode: Optional dict to configure mode. Use {"type": "streaming"} to enable streaming or {"type": "polling"} (default).
    :param sdk_flavor: Optional identifier of an integration built on top of this SDK (e.g. an OpenFeature provider). Sent in the register + metrics payloads alongside sdkVersion so adoption of the integration can be tracked. Leave unset for plain SDK usage.
    :param sdk_flavor_version: Optional version of the integration named by sdk_flavor.
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
        scheduler: Optional[BaseScheduler] = None,
        scheduler_executor: Optional[str] = None,
        multiple_instance_mode: InstanceAllowType = InstanceAllowType.WARN,
        event_callback: Optional[Callable[[BaseEvent], None]] = None,
        experimental_mode: Optional[ExperimentalMode] = None,
        sdk_flavor: Optional[str] = None,
        sdk_flavor_version: Optional[str] = None,
    ) -> None:
        custom_strategies = custom_strategies or {}

        self._config = UnleashConfig(
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
        self._enricher = ContextEnricher(self._config)
        self.unleash_event_callback = event_callback
        # Events are handed to the dispatcher, which delivers them to the user's
        # callback on its own thread.  The callback is never called from here.
        self.__events: Optional[EventDispatcher] = (
            EventDispatcher(event_callback) if event_callback is not None else None
        )
        self._lifecycle_lock = threading.RLock()
        self._closed = threading.Event()

        self._do_instance_check(multiple_instance_mode)

        # Class objects
        self.fl_job: Job = None
        self.metric_job: Job = None
        self.engine = UnleashEngine()

        self.impact_metrics = ImpactMetrics(
            self.engine,
            self._config.app_name,
            self._config.impact_metrics_environment,
        )

        self.cache = cache or FileCache(
            self.unleash_app_name, directory=cache_directory
        )
        self.cache.mset({METRIC_LAST_SENT_TIME: datetime.now(timezone.utc), ETAG: ""})
        self.unleash_bootstrapped = self.cache.bootstrapped

        self.metrics_headers: dict = {}

        self._init_scheduler(scheduler, scheduler_executor)

        if custom_strategies:
            self.engine.register_custom_strategies(custom_strategies)

        self.strategy_mapping = {**custom_strategies}

        # Client status
        self._run_state = _RunState.UNINITIALIZED

        # Bootstrapping
        if self.unleash_bootstrapped:
            BootstrapConnector(
                engine=self.engine,
                cache=self.cache,
            ).start()

        self.connector: BaseConnector = None

    def _init_scheduler(
        self, scheduler: Optional[BaseScheduler], scheduler_executor: Optional[str]
    ) -> None:
        """
        Scheduler bootstrapping
        """
        # - Figure out the Unleash executor name.
        if scheduler and scheduler_executor:
            self.unleash_executor_name = scheduler_executor
        elif scheduler and not scheduler_executor:
            raise ValueError(
                "If using a custom scheduler, you must specify a executor."
            )
        else:
            if not scheduler and scheduler_executor:
                LOGGER.warning(
                    "scheduler_executor should only be used with a custom scheduler."
                )

            self.unleash_executor_name = f"unleash_executor_{''.join(random.choices(string.ascii_uppercase + string.digits, k=6))}"

        # Set up the scheduler.
        if scheduler:
            self.unleash_scheduler = scheduler
        else:
            executors = {self.unleash_executor_name: ThreadPoolExecutor()}
            self.unleash_scheduler = BackgroundScheduler(executors=executors)

    @property
    def unleash_url(self) -> str:
        return self._config.url

    @unleash_url.setter
    def unleash_url(self, value: str) -> None:
        self._config.url = value

    @property
    def unleash_app_name(self) -> str:
        return self._config.app_name

    @unleash_app_name.setter
    def unleash_app_name(self, value: str) -> None:
        self._config.app_name = value

    @property
    def unleash_environment(self) -> str:
        return self._config.environment

    @unleash_environment.setter
    def unleash_environment(self, value: str) -> None:
        self._config.environment = value

    @property
    def unleash_instance_id(self) -> str:
        return self._config.instance_id

    @unleash_instance_id.setter
    def unleash_instance_id(self, value: str) -> None:
        self._config.instance_id = value

    @property
    def unleash_refresh_interval(self) -> int:
        return self._config.refresh_interval

    @unleash_refresh_interval.setter
    def unleash_refresh_interval(self, value: int) -> None:
        self._config.refresh_interval = value

    @property
    def unleash_refresh_jitter(self) -> Optional[int]:
        return self._config.refresh_jitter

    @unleash_refresh_jitter.setter
    def unleash_refresh_jitter(self, value: Optional[int]) -> None:
        self._config.refresh_jitter = value

    @property
    def unleash_metrics_interval(self) -> int:
        return self._config.metrics_interval

    @unleash_metrics_interval.setter
    def unleash_metrics_interval(self, value: int) -> None:
        self._config.metrics_interval = value

    @property
    def unleash_metrics_jitter(self) -> Optional[int]:
        return self._config.metrics_jitter

    @unleash_metrics_jitter.setter
    def unleash_metrics_jitter(self, value: Optional[int]) -> None:
        self._config.metrics_jitter = value

    @property
    def unleash_request_timeout(self) -> int:
        return self._config.request_timeout

    @unleash_request_timeout.setter
    def unleash_request_timeout(self, value: int) -> None:
        self._config.request_timeout = value

    @property
    def unleash_request_retries(self) -> int:
        return self._config.request_retries

    @unleash_request_retries.setter
    def unleash_request_retries(self, value: int) -> None:
        self._config.request_retries = value

    @property
    def unleash_disable_metrics(self) -> bool:
        return self._config.disable_metrics

    @unleash_disable_metrics.setter
    def unleash_disable_metrics(self, value: bool) -> None:
        self._config.disable_metrics = value

    @property
    def unleash_disable_registration(self) -> bool:
        return self._config.disable_registration

    @unleash_disable_registration.setter
    def unleash_disable_registration(self, value: bool) -> None:
        self._config.disable_registration = value

    @property
    def unleash_custom_headers(self) -> dict:
        return self._config.custom_headers

    @unleash_custom_headers.setter
    def unleash_custom_headers(self, value: dict) -> None:
        self._config.custom_headers = value

    @property
    def unleash_custom_options(self) -> dict:
        return self._config.custom_options

    @unleash_custom_options.setter
    def unleash_custom_options(self, value: dict) -> None:
        self._config.custom_options = value

    @property
    def unleash_static_context(self) -> Dict[str, Any]:
        return self._config.static_context

    @unleash_static_context.setter
    def unleash_static_context(self, value: Dict[str, Any]) -> None:
        self._config.static_context = value

    @property
    def unleash_project_name(self) -> Optional[str]:
        return self._config.project_name

    @unleash_project_name.setter
    def unleash_project_name(self, value: Optional[str]) -> None:
        self._config.project_name = value

    @property
    def unleash_verbose_log_level(self) -> int:
        return self._config.verbose_log_level

    @unleash_verbose_log_level.setter
    def unleash_verbose_log_level(self, value: int) -> None:
        self._config.verbose_log_level = value

    @property
    def unleash_sdk_flavor(self) -> Optional[str]:
        return self._config.sdk_flavor

    @unleash_sdk_flavor.setter
    def unleash_sdk_flavor(self, value: Optional[str]) -> None:
        self._config.sdk_flavor = value

    @property
    def unleash_sdk_flavor_version(self) -> Optional[str]:
        return self._config.sdk_flavor_version

    @unleash_sdk_flavor_version.setter
    def unleash_sdk_flavor_version(self, value: Optional[str]) -> None:
        self._config.sdk_flavor_version = value

    @property
    def connector_mode(self) -> ExperimentalMode:
        return self._config.experimental_mode

    @connector_mode.setter
    def connector_mode(self, value: ExperimentalMode) -> None:
        self._config.experimental_mode = value

    @property
    def unleash_metrics_interval_str_millis(self) -> str:
        return self._config.metrics_interval_str_millis

    @property
    def connection_id(self):
        return self._config.connection_id

    @property
    def is_initialized(self):
        return self._run_state == _RunState.INITIALIZED

    def initialize_client(self, fetch_toggles: bool = True) -> None:
        """
        Initializes client and starts communication with central unleash server(s).

        This kicks off:

        * Client registration
        * Provisioning poll
        * Stats poll

        If `fetch_toggles` is `False`, feature toggle polling will be turned off
        and instead the client will only load features from the cache. This is
        usually used to cater the multi-process setups, e.g. Django, Celery,
        etc.

        This will raise an exception on registration if the URL is invalid. It is done automatically if called inside a context manager as in:

        .. code-block:: python

            with UnleashClient(
                url="https://foo.bar",
                app_name="myClient1",
                instance_id="myinstanceid"
                ) as client:
                pass
        """
        # Only perform initialization steps if client is not initialized.
        with self._lifecycle_lock:
            if self._closed.is_set() or self._run_state > _RunState.UNINITIALIZED:
                warnings.warn(
                    "Attempted to initialize an Unleash Client instance that has already been initialized."
                )
                return
            try:
                start_scheduler = False
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
                    register_client(
                        self.unleash_url,
                        self.unleash_app_name,
                        self.unleash_instance_id,
                        self.connection_id,
                        self.unleash_metrics_interval,
                        base_headers,
                        self.unleash_custom_options,
                        self.strategy_mapping,
                        self.unleash_request_timeout,
                        self.unleash_sdk_flavor,
                        self.unleash_sdk_flavor_version,
                    )
                mode = self.connector_mode.get("type", "polling")

                if mode == "streaming" and fetch_toggles:
                    self.connector = StreamingConnector(
                        engine=self.engine,
                        cache=self.cache,
                        url=self.unleash_url,
                        headers=base_headers,
                        request_timeout=self.unleash_request_timeout,
                        events=self.__events,
                        custom_options=self.unleash_custom_options,
                    )
                elif fetch_toggles:
                    start_scheduler = True
                    self.connector = PollingConnector(
                        engine=self.engine,
                        cache=self.cache,
                        scheduler=self.unleash_scheduler,
                        url=self.unleash_url,
                        app_name=self.unleash_app_name,
                        instance_id=self.unleash_instance_id,
                        headers=base_headers,
                        custom_options=self.unleash_custom_options,
                        request_timeout=self.unleash_request_timeout,
                        request_retries=self.unleash_request_retries,
                        project=self.unleash_project_name,
                        scheduler_executor=self.unleash_executor_name,
                        refresh_interval=self.unleash_refresh_interval,
                        events=self.__events,
                    )
                else:
                    start_scheduler = True
                    self.connector = OfflineConnector(
                        engine=self.engine,
                        cache=self.cache,
                        scheduler=self.unleash_scheduler,
                        scheduler_executor=self.unleash_executor_name,
                        refresh_interval=self.unleash_refresh_interval,
                        refresh_jitter=self.unleash_refresh_jitter,
                        events=self.__events,
                    )

                self.connector.start()

                if not self.unleash_disable_metrics:
                    if getattr(self.unleash_scheduler, "state", None) != STATE_RUNNING:
                        start_scheduler = True

                    self.metrics_headers = {
                        **base_headers,
                        "unleash-interval": self.unleash_metrics_interval_str_millis,
                    }

                    metrics_args = {
                        "url": self.unleash_url,
                        "app_name": self.unleash_app_name,
                        "connection_id": self.connection_id,
                        "instance_id": self.unleash_instance_id,
                        "headers": self.metrics_headers,
                        "custom_options": self.unleash_custom_options,
                        "request_timeout": self.unleash_request_timeout,
                        "engine": self.engine,
                        "sdk_flavor": self.unleash_sdk_flavor,
                        "sdk_flavor_version": self.unleash_sdk_flavor_version,
                    }

                    self.metric_job = self.unleash_scheduler.add_job(
                        aggregate_and_send_metrics,
                        trigger=IntervalTrigger(
                            seconds=int(self.unleash_metrics_interval),
                            jitter=self.unleash_metrics_jitter,
                        ),
                        executor=self.unleash_executor_name,
                        kwargs=metrics_args,
                    )

                if start_scheduler:
                    self.unleash_scheduler.start()
                self._run_state = _RunState.INITIALIZED

            except Exception as excep:
                # Log exceptions during initialization.  is_initialized will remain false.
                LOGGER.warning(
                    "Exception during UnleashClient initialization: %s", excep
                )
                raise excep

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

        toggles = self.engine.list_known_toggles()
        return {
            toggle.name: {"type": toggle.type, "project": toggle.project}
            for toggle in toggles
        }

    def destroy(self) -> None:
        """
        Gracefully shuts down the Unleash client by stopping jobs and stopping
        the scheduler.

        For cache teardown:
        - Default disk-backed FileCache instances are preserved on disk.
        - Custom non-FileCache implementations will have destroy() called.

        You shouldn't need this too much!
        """
        with self._lifecycle_lock:
            if self._closed.is_set():
                return
            self._closed.set()
            self._run_state = _RunState.SHUTDOWN
            if self.connector:
                self.connector.stop()

            if self.metric_job:
                # Flush metrics before shutting down.
                aggregate_and_send_metrics(
                    url=self.unleash_url,
                    app_name=self.unleash_app_name,
                    connection_id=self.connection_id,
                    instance_id=self.unleash_instance_id,
                    headers=self.metrics_headers,
                    custom_options=self.unleash_custom_options,
                    request_timeout=self.unleash_request_timeout,
                    engine=self.engine,
                )
                try:
                    self.metric_job.remove()
                except JobLookupError as exc:
                    LOGGER.info("Exception during connector teardown: %s", exc)

            try:
                if hasattr(self, "unleash_scheduler") and self.unleash_scheduler:
                    self.unleash_scheduler.remove_all_jobs()
                    self.unleash_scheduler.shutdown(wait=True)
            except Exception as exc:
                LOGGER.warning("Exception during scheduler teardown: %s", exc)

            # Disk-backed FileCache instances can be shared across processes.
            # Avoid deleting them during shutdown to prevent cache races.
            if not isinstance(self.cache, FileCache):
                try:
                    self.cache.destroy()
                except Exception as exc:
                    LOGGER.warning("Exception during cache teardown: %s", exc)

            # Closed last: the scheduler has to drain first, otherwise an
            # in-flight poll can still queue events we'd silently drop.
            if self.__events:
                self.__events.close()

    @staticmethod
    def _redact_to_print_safely(value: Optional[str]) -> Optional[str]:
        return redact_to_print_safely(value)

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
        context = self._enricher.build(context)
        result = self.engine.is_enabled(
            feature_name, context, fallback_function=fallback_function
        )

        try:
            if self.__events and result.requires_impression_event_emission:
                self.__events.emit_event(
                    UnleashEvent(
                        event_type=UnleashEventType.FEATURE_FLAG,
                        event_id=uuid.uuid4(),
                        context=context,
                        enabled=result.is_enabled,
                        feature_name=feature_name,
                    )
                )
        except Exception as excep:
            LOGGER.log(
                self.unleash_verbose_log_level,
                "Error emitting impression event: %s",
                excep,
            )

        return result.is_enabled

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
        context = self._enricher.build(context)
        result = self.engine.get_variant(feature_name, context)

        if not result.is_found and (self.unleash_bootstrapped or self.is_initialized):
            LOGGER.log(
                self.unleash_verbose_log_level,
                "Attempted to get feature flag/variation %s, but client wasn't initialized!",
                feature_name,
            )

        try:
            if self.__events and result.requires_impression_event_emission:
                self.__events.emit_event(
                    UnleashEvent(
                        event_type=UnleashEventType.VARIANT,
                        event_id=uuid.uuid4(),
                        context=context,
                        enabled=bool(result.variant.enabled),
                        feature_name=feature_name,
                        variant=str(result.variant.name),
                    )
                )
        except Exception as excep:
            LOGGER.log(
                self.unleash_verbose_log_level,
                "Error emitting impression event: %s",
                excep,
            )

        # This can probably become a to_dict method of the Variant type.
        variant = {k: v for k, v in asdict(result.variant).items() if v is not None}
        return variant

    def _do_instance_check(self, multiple_instance_mode):
        identifier = self._config.instance_identifier
        if identifier in INSTANCES:
            msg = f"You already have {INSTANCES.count(identifier)} instance(s) configured for this config: {identifier}, please double check the code where this client is being instantiated."
            if multiple_instance_mode == InstanceAllowType.BLOCK:
                raise Exception(msg)  # pylint: disable=broad-exception-raised
            if multiple_instance_mode == InstanceAllowType.WARN:
                LOGGER.error(msg)
        INSTANCES.increment(identifier)

    def __enter__(self) -> "UnleashClient":
        self.initialize_client()
        return self

    def __exit__(self, *args, **kwargs):
        self.destroy()
        return False
