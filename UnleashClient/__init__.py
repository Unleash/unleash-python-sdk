# pylint: disable=invalid-name
import random
import string
import uuid
import warnings
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Union

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.job import Job
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import STATE_RUNNING, BaseScheduler
from apscheduler.triggers.interval import IntervalTrigger
from yggdrasil_engine.engine import UnleashEngine

from UnleashClient.api import register_client
from UnleashClient.connectors import OfflineConnector, PollingConnector
from UnleashClient.constants import (
    DISABLED_VARIATION,
    ETAG,
    METRIC_LAST_SENT_TIME,
    REQUEST_RETRIES,
    REQUEST_TIMEOUT,
    SDK_NAME,
    SDK_VERSION,
)
from UnleashClient.events import (
    BaseEvent,
    UnleashEvent,
    UnleashEventType,
    UnleashReadyEvent,
)
from UnleashClient.periodic_tasks import (
    aggregate_and_send_metrics,
)

from .cache import BaseCache, FileCache
from .utils import LOGGER, InstanceAllowType, InstanceCounter

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


def build_ready_callback(
    event_callback: Optional[Callable[[BaseEvent], None]] = None,
) -> Optional[Callable]:
    """
    Builds a callback function that can be used to notify when the Unleash client is ready.
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
    :param event_callback: Function to call if impression events are enabled.  WARNING: Depending on your event library, this may have performance implications!
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
        cache: Optional[BaseCache] = None,
        scheduler: Optional[BaseScheduler] = None,
        scheduler_executor: Optional[str] = None,
        multiple_instance_mode: InstanceAllowType = InstanceAllowType.WARN,
        event_callback: Optional[Callable[[BaseEvent], None]] = None,
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

        self._do_instance_check(multiple_instance_mode)

        # Class objects
        self.fl_job: Job = None
        self.metric_job: Job = None
        self.engine = UnleashEngine()

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
        self.is_initialized = False

        # Bootstrapping
        if self.unleash_bootstrapped:
            OfflineConnector(
                engine=self.engine,
                cache=self.cache,
                scheduler=None,
            ).load_features()

        self.connector: Union[OfflineConnector, PollingConnector] = None

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
    def unleash_metrics_interval_str_millis(self) -> str:
        return str(self.unleash_metrics_interval * 1000)

    @property
    def connection_id(self):
        return self._connection_id

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
        if not self.is_initialized:
            # pylint: disable=no-else-raise
            try:
                base_headers = {
                    **self.unleash_custom_headers,
                    "unleash-connection-id": self.connection_id,
                    "unleash-appname": self.unleash_app_name,
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
                    )

                if fetch_toggles:
                    self.unleash_scheduler.start()
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
                        event_callback=self.unleash_event_callback,
                        ready_callback=self._ready_callback,
                    )
                else:
                    self.unleash_scheduler.start()
                    self.connector = OfflineConnector(
                        engine=self.engine,
                        cache=self.cache,
                        scheduler=self.unleash_scheduler,
                        scheduler_executor=self.unleash_executor_name,
                        refresh_interval=self.unleash_refresh_interval,
                        refresh_jitter=self.unleash_refresh_jitter,
                        ready_callback=self._ready_callback,
                    )

                self.connector.start()

                if not self.unleash_disable_metrics:
                    if getattr(self.unleash_scheduler, "state", None) != STATE_RUNNING:
                        self.unleash_scheduler.start()

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
            except Exception as excep:
                # Log exceptions during initialization.  is_initialized will remain false.
                LOGGER.warning(
                    "Exception during UnleashClient initialization: %s", excep
                )
                raise excep
            else:
                # Set is_initialized to true if no exception is encountered.
                self.is_initialized = True
        else:
            warnings.warn(
                "Attempted to initialize an Unleash Client instance that has already been initialized."
            )

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
        Gracefully shuts down the Unleash client by stopping jobs, stopping the scheduler, and deleting the cache.

        You shouldn't need this too much!
        """
        if self.connector:
            self.connector.stop()
        if self.metric_job:
            self.metric_job.remove()

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

        if getattr(self.unleash_scheduler, "state", None) == STATE_RUNNING:
            self.unleash_scheduler.shutdown()
        self.cache.destroy()

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

    def _safe_context(self, context) -> dict:
        new_context: Dict[str, Any] = self.unleash_static_context.copy()
        new_context.update(context or {})

        if "currentTime" not in new_context:
            new_context["currentTime"] = datetime.now(timezone.utc).isoformat()

        safe_properties = self._extract_properties(new_context)
        safe_properties = {
            k: self._safe_context_value(v) for k, v in safe_properties.items()
        }
        safe_context = {
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

    def _safe_context_value(self, value):
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, (int, float)):
            return str(value)
        return str(value)

    def _resolve_variant(self, feature_name: str, context: dict) -> dict:
        """
        Resolves a feature variant.
        """
        variant = self.engine.get_variant(feature_name, context)
        if variant:
            return {k: v for k, v in asdict(variant).items() if v is not None}
        return None

    def _do_instance_check(self, multiple_instance_mode):
        identifier = self.__get_identifier()
        if identifier in INSTANCES:
            msg = f"You already have {INSTANCES.count(identifier)} instance(s) configured for this config: {identifier}, please double check the code where this client is being instantiated."
            if multiple_instance_mode == InstanceAllowType.BLOCK:
                raise Exception(msg)  # pylint: disable=broad-exception-raised
            if multiple_instance_mode == InstanceAllowType.WARN:
                LOGGER.error(msg)
        INSTANCES.increment(identifier)

    def __get_identifier(self):
        api_key = (
            self.unleash_custom_headers.get("Authorization")
            if self.unleash_custom_headers is not None
            else None
        )
        return f"apiKey:{api_key} appName:{self.unleash_app_name} instanceId:{self.unleash_instance_id}"

    def __enter__(self) -> "UnleashClient":
        self.initialize_client()
        return self

    def __exit__(self, *args, **kwargs):
        self.destroy()
        return False
