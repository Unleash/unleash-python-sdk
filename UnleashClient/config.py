"""Configuration value object shared by the sync and async Unleash clients."""

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from UnleashClient.constants import REQUEST_RETRIES, REQUEST_TIMEOUT
from UnleashClient.utils import extract_environment_from_headers

try:
    from typing import Literal, TypedDict
except ImportError:
    from typing_extensions import Literal, TypedDict  # type: ignore


class ExperimentalMode(TypedDict, total=False):
    type: Literal["streaming", "polling"]


def redact_to_print_safely(value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    prefix, separator, secret = value.rpartition(":")
    redacted_secret = f"{secret[:6]}...{secret[-3:]}"
    return f"{prefix}{separator}{redacted_secret}"


def _optional_int(value: Any) -> Optional[int]:
    return int(value) if value is not None else None


@dataclass(frozen=True)
class HttpOptions:
    """
    How the client talks to the Unleash server.

    :param headers: Headers sent with every request, typically ``{"Authorization": "<API token>"}``.
    :param options: Extra keyword arguments passed to every ``requests`` call.  Can be used to skip SSL verification.
    :param timeout: Request timeout in seconds.
    :param retries: Number of retries for failed requests.
    """

    # repr=False: the dataclass __repr__ would otherwise put the Authorization
    # API key into logs and tracebacks.
    headers: Optional[Dict[str, str]] = field(default=None, repr=False)
    options: Optional[Dict[str, Any]] = None
    timeout: int = REQUEST_TIMEOUT
    retries: int = REQUEST_RETRIES

    def __post_init__(self) -> None:
        # Copied, so that mutating the caller's dicts can't change a frozen config.
        object.__setattr__(self, "headers", dict(self.headers or {}))
        object.__setattr__(self, "options", dict(self.options or {}))


@dataclass(frozen=True)
class FetchOptions:
    """
    How often the client fetches feature flags.

    :param interval: Refresh interval in seconds.
    :param jitter: Random jitter added to the refresh interval, in seconds.
    """

    interval: int = 15
    jitter: Optional[int] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "jitter", _optional_int(self.jitter))


@dataclass(frozen=True)
class MetricsOptions:
    """
    How the client reports usage metrics.

    :param interval: Metrics send interval in seconds.
    :param jitter: Random jitter added to the metrics interval, in seconds.
    :param disabled: Disables sending metrics to the Unleash server.
    """

    interval: int = 60
    jitter: Optional[int] = None
    disabled: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "jitter", _optional_int(self.jitter))


@dataclass(frozen=True)
class UnleashConfig:
    """
    Settings for an Unleash client, shared by every client flavor.  Immutable
    once constructed: build a new config and a new client to change settings.

    Types are not validated or coerced beyond ``url.rstrip("/")`` and ``int()``
    on the two jitters.

    Example::

        config = UnleashConfig(
            url="https://unleash.example.com/api",
            app_name="my-app",
            http=HttpOptions(headers={"Authorization": "<API token>"}),
            metrics=MetricsOptions(interval=30),
        )

    :param url: URL of the Unleash server.
    :param app_name: Name of the application using the client.
    :param environment: Name of the environment, defaults to "default".
    :param instance_id: Unique identifier for this client instance.
    :param project_name: Only fetch the feature flags of this project.
    :param http: See :class:`HttpOptions`.
    :param fetching: See :class:`FetchOptions`.
    :param metrics: See :class:`MetricsOptions`.
    :param disable_registration: Disables registration with the Unleash server.
    :param verbose_log_level: Numerical log level (https://docs.python.org/3/library/logging.html#logging-levels) for cases where checking a feature flag fails.
    :param experimental_mode: Use {"type": "streaming"} to enable streaming or {"type": "polling"} (default).
    :param sdk_flavor: Identifier of an integration built on top of this SDK (e.g. an OpenFeature provider). Sent in the register + metrics payloads alongside sdkVersion so adoption of the integration can be tracked. Leave unset for plain SDK usage.
    :param sdk_flavor_version: Version of the integration named by sdk_flavor.
    """

    url: str
    app_name: str
    environment: str = "default"
    instance_id: str = "unleash-python-sdk"
    project_name: Optional[str] = None
    http: HttpOptions = field(default_factory=HttpOptions)
    fetching: FetchOptions = field(default_factory=FetchOptions)
    metrics: MetricsOptions = field(default_factory=MetricsOptions)
    disable_registration: bool = False
    verbose_log_level: int = 30
    experimental_mode: Optional[ExperimentalMode] = None
    sdk_flavor: Optional[str] = None
    sdk_flavor_version: Optional[str] = None
    connection_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        object.__setattr__(self, "url", self.url.rstrip("/"))
        object.__setattr__(
            self, "experimental_mode", self.experimental_mode or {"type": "polling"}
        )

    @property
    def static_context(self) -> Dict[str, Any]:
        return {"appName": self.app_name, "environment": self.environment}

    @property
    def mode(self) -> str:
        return self.experimental_mode.get("type", "polling")

    @property
    def refresh_interval_str_millis(self) -> str:
        return str(self.fetching.interval * 1000)

    @property
    def metrics_interval_str_millis(self) -> str:
        return str(self.metrics.interval * 1000)

    @property
    def impact_metrics_environment(self) -> str:
        return extract_environment_from_headers(self.http.headers) or self.environment

    @property
    def instance_identifier(self) -> str:
        api_key = self.http.headers.get("Authorization")
        return f"apiKey:{redact_to_print_safely(api_key)} appName:{self.app_name} instanceId:{self.instance_id}"
