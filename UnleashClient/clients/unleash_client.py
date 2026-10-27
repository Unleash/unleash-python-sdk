# pylint: disable=invalid-name
import threading
import uuid
import warnings
from datetime import datetime, timezone
from enum import IntEnum
from typing import Callable, Optional, Union

from apscheduler.schedulers.base import BaseScheduler
from yggdrasil_engine.engine import UnleashEngine

from UnleashClient._context import _ContextEnricher
from UnleashClient._evaluator import _Evaluator
from UnleashClient._event_dispatcher import _EventDispatcher
from UnleashClient._feature_store import _FeatureStore
from UnleashClient._headers import _HeaderFactory
from UnleashClient._instance_registry import _get_instance_registry
from UnleashClient._metrics import _MetricsReporter
from UnleashClient._payloads import _build_register_payload
from UnleashClient._scheduler import _ScheduledJob, _Scheduler
from UnleashClient._transport import _Transport
from UnleashClient.cache import BaseCache, FileCache
from UnleashClient.config import (
    HttpOptions,
    IdentityOptions,
    MetricsOptions,
    PollingOptions,
    StreamingOptions,
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
from UnleashClient.constants import ETAG, METRIC_LAST_SENT_TIME
from UnleashClient.events import (
    BaseEvent,
    UnleashEventType,
    UnleashReadyEvent,
)
from UnleashClient.impact_metrics import ImpactMetrics
from UnleashClient.utils import (
    LOGGER,
    InstanceAllowType,
)

INSTANCES = _get_instance_registry()


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
        READY is now emitted through :class:`UnleashClient._event_dispatcher._EventDispatcher`,
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

    Example::

        with UnleashClient(
            url="https://unleash.example.com/api",
            app_name="my-app",
            api_key="<API token>",
        ) as client:
            client.is_enabled("new-checkout", {"userId": "42"})

    :param url: URL of the Unleash server, required.
    :param app_name: Name of the application using the client, required.
    :param api_key: Client API token.  Optional, because a client that only loads from a backup never talks to the server.
    :param identity: How the client identifies itself, see :class:`~UnleashClient.config.IdentityOptions`.
    :param http: How the client talks to the server, see :class:`~UnleashClient.config.HttpOptions`.
    :param mode: How the client receives flag update.
    :param metrics: How the client reports to the server, see :class:`~UnleashClient.config.MetricsOptions`.
    :param verbose_log_level: Numerical log level (https://docs.python.org/3/library/logging.html#logging-levels) for cases where checking a feature flag fails.
    :param custom_strategies: Dictionary of custom strategy names : custom strategy objects.
    :param cache: Custom cache implementation that extends UnleashClient.cache.BaseCache.  When unset, UnleashClient will use Fcache.
    :param cache_directory: Location of the cache directory. When unset, FCache will determine the location.
    :param scheduler: Custom APScheduler object.  Use this if you want to customize jobstore or executors.  When unset, UnleashClient will create it's own scheduler.
    :param scheduler_executor: Name of APSCheduler executor to use if using a custom scheduler.
    :param multiple_instance_mode: Determines how multiple instances being instantiated is handled by the SDK, when set to InstanceAllowType.BLOCK, the client constructor will fail when more than one instance is detected, when set to InstanceAllowType.WARN, multiple instances will be allowed but log a warning, when set to InstanceAllowType.SILENTLY_ALLOW, no warning or failure will be raised when instantiating multiple instances of the client. Defaults to InstanceAllowType.WARN
    :param event_callback: Function to call if impression events are enabled.  Called on a dedicated background thread, so it must not rely on thread local state from the caller.
    """

    def __init__(
        self,
        url: str,
        app_name: str,
        *,
        api_key: Optional[str] = None,
        identity: Optional[IdentityOptions] = None,
        http: Optional[HttpOptions] = None,
        mode: Optional[Union[PollingOptions, StreamingOptions]] = None,
        metrics: Optional[MetricsOptions] = None,
        verbose_log_level: int = 30,
        custom_strategies: Optional[dict] = None,
        cache: Optional[BaseCache] = None,
        cache_directory: Optional[str] = None,
        scheduler: Optional[BaseScheduler] = None,
        scheduler_executor: Optional[str] = None,
        multiple_instance_mode: InstanceAllowType = InstanceAllowType.WARN,
        event_callback: Optional[Callable[[BaseEvent], None]] = None,
    ) -> None:
        self._config = UnleashConfig(
            url=url,
            app_name=app_name,
            api_key=api_key,
            identity=identity,
            http=http,
            mode=mode,
            metrics=metrics,
            verbose_log_level=verbose_log_level,
        )
        self._custom_strategies = custom_strategies or {}
        self._enricher = _ContextEnricher(self._config)
        self._headers = _HeaderFactory(self._config)
        self.unleash_event_callback = event_callback
        # Events are handed to the dispatcher, which delivers them to the user's
        # callback on its own thread.  The callback is never called from here.
        self.__events: Optional[_EventDispatcher] = (
            _EventDispatcher(event_callback) if event_callback is not None else None
        )
        self._lifecycle_lock = threading.RLock()
        self._closed = threading.Event()

        _get_instance_registry().register(
            identifier=self._config.instance_identifier, mode=multiple_instance_mode
        )

        # Class objects
        self._engine = UnleashEngine()

        self.impact_metrics = ImpactMetrics(
            self._engine,
            self._config.app_name,
            self._config.impact_metrics_environment,
        )

        self._cache = cache or FileCache(
            self._config.app_name, directory=cache_directory
        )
        self._cache.mset({METRIC_LAST_SENT_TIME: datetime.now(timezone.utc), ETAG: ""})
        self.unleash_bootstrapped = self._cache.bootstrapped

        self._store = _FeatureStore(
            engine=self._engine, cache=self._cache, events=self.__events
        )

        self._evaluator = _Evaluator(
            engine=self._engine,
            enricher=self._enricher,
            config=self._config,
            events=self.__events,
        )

        self._transport = _Transport(self._config, self._headers)

        self._scheduler = _Scheduler(scheduler, scheduler_executor)

        self._metrics = _MetricsReporter(
            config=self._config,
            transport=self._transport,
            scheduler=self._scheduler,
            engine=self._engine,
            impact_metrics=self.impact_metrics,
        )

        # Client status
        self._run_state = _RunState.UNINITIALIZED

        # Bootstrapping
        if self.unleash_bootstrapped:
            # A store with no dispatcher: start() runs here, before
            # initialize_client(), and emitting READY from the constructor would
            # move it earlier for bootstrapped clients.  See the TODO on
            # BootstrapConnector.
            BootstrapConnector(
                store=_FeatureStore(engine=self._engine, cache=self._cache)
            ).start()

        self.connector: BaseConnector = None

    @property
    def metric_job(self) -> _ScheduledJob:
        return self._metrics.job

    @metric_job.setter
    def metric_job(self, value: _ScheduledJob) -> None:
        self._metrics.job = value

    @property
    def unleash_scheduler(self) -> BaseScheduler:
        return self._scheduler.scheduler

    @unleash_scheduler.setter
    def unleash_scheduler(self, value: BaseScheduler) -> None:
        self._scheduler.scheduler = value

    @property
    def unleash_executor_name(self) -> str:
        return self._scheduler.executor_name

    @unleash_executor_name.setter
    def unleash_executor_name(self, value: str) -> None:
        self._scheduler.executor_name = value

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

            with UnleashClient(url="https://foo.bar", app_name="myClient1") as client:
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

                if self._custom_strategies:
                    self._engine.register_custom_strategies(self._custom_strategies)

                # Register app
                if not self._config.metrics.disable_registration:
                    self._transport.register(
                        _build_register_payload(self._config, self._custom_strategies)
                    )
                mode = self._config.mode

                if isinstance(mode, StreamingOptions) and fetch_toggles:
                    self.connector = StreamingConnector(
                        store=self._store,
                        url=self._config.url,
                        headers=self._headers.streaming(),
                        request_timeout=self._config.http.timeout,
                        custom_options=self._config.http.options,
                    )
                elif isinstance(mode, PollingOptions) and fetch_toggles:
                    start_scheduler = True
                    self.connector = PollingConnector(
                        store=self._store,
                        scheduler=self._scheduler,
                        transport=self._transport,
                        options=mode,
                    )
                else:
                    # Offline mode reloads the cache on an interval.  A
                    # streaming client sets none, so it falls back on the
                    # polling defaults.
                    offline = (
                        mode if isinstance(mode, PollingOptions) else PollingOptions()
                    )
                    start_scheduler = True
                    self.connector = OfflineConnector(
                        store=self._store,
                        scheduler=self._scheduler,
                        refresh_interval=offline.interval,
                        refresh_jitter=offline.jitter,
                    )

                self.connector.start()

                if not self._config.metrics.disabled:
                    # _Scheduler.start() no-ops when it is already running, so this can
                    # be unconditional.
                    start_scheduler = True

                    self._metrics.start()

                if start_scheduler:
                    self._scheduler.start()
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

        return self._evaluator.feature_definitions()

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

            self._metrics.stop()

            try:
                # hasattr: the constructor raises before assigning _scheduler when a
                # custom scheduler was passed without an executor name.
                if hasattr(self, "_scheduler") and self._scheduler.scheduler:
                    self._scheduler.shutdown(wait=True)
            except Exception as exc:
                LOGGER.warning("Exception during scheduler teardown: %s", exc)

            # Disk-backed FileCache instances can be shared across processes.
            # Avoid deleting them during shutdown to prevent cache races.
            if not isinstance(self._cache, FileCache):
                try:
                    self._cache.destroy()
                except Exception as exc:
                    LOGGER.warning("Exception during cache teardown: %s", exc)

            # Closed last: the scheduler has to drain first, otherwise an
            # in-flight poll can still queue events we'd silently drop.
            if self.__events:
                self.__events.close()

    @staticmethod
    def _redact_to_print_safely(value: Optional[str]) -> Optional[str]:
        return redact_to_print_safely(value)

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
        return self._evaluator.is_enabled(feature_name, context, fallback_function)

    def get_variant(self, feature_name: str, context: Optional[dict] = None) -> dict:
        """
        Checks if a feature toggle is enabled.  If so, return variant.

        Notes:

        * If client hasn't been initialized yet or an error occurs, flag will default to false.

        :param feature_name: Name of the feature
        :param context: Dictionary with context (e.g. IPs, email) for feature toggle.
        :return: Variant and feature flag status.
        """
        result = self._evaluator.get_variant(feature_name, context)

        if not result.is_found and (self.unleash_bootstrapped or self.is_initialized):
            LOGGER.log(
                self._config.verbose_log_level,
                "Attempted to get feature flag/variation %s, but client wasn't initialized!",
                feature_name,
            )

        return result.variant

    def __enter__(self) -> "UnleashClient":
        self.initialize_client()
        return self

    def __exit__(self, *args, **kwargs):
        self.destroy()
        return False
