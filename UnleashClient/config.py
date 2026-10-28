"""Configuration value object shared by the sync and async Unleash clients."""

import uuid
from dataclasses import KW_ONLY, dataclass, field
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Union

from UnleashClient.constants import REQUEST_RETRIES, REQUEST_TIMEOUT
from UnleashClient.utils import LOGGER, extract_environment_from_api_key


def redact_to_print_safely(value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    prefix, separator, secret = value.rpartition(":")
    redacted_secret = f"{secret[:6]}...{secret[-3:]}"
    return f"{prefix}{separator}{redacted_secret}"


def _optional_int(value: Any) -> Optional[int]:
    return int(value) if value is not None else None


@dataclass(frozen=True, kw_only=True)
class HttpOptions:
    """
    :param headers: Extra headers sent with every request.  The API key is not one of them: pass it as ``api_key`` to the client.
    :param options: Extra keyword arguments passed to every ``requests`` call.
    :param timeout: Request timeout in seconds.
    :param retries: Number of retries for failed requests.
    :raises ValueError: If ``headers`` contains an ``Authorization`` header.
    """

    # repr=False: custom headers can carry credentials of their own, such as a
    # proxy's, which the dataclass __repr__ would put into logs and tracebacks.
    headers: Optional[Mapping[str, str]] = field(default=None, repr=False)
    options: Optional[Mapping[str, Any]] = None
    timeout: int = REQUEST_TIMEOUT
    retries: int = REQUEST_RETRIES

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers or {})))
        object.__setattr__(self, "options", MappingProxyType(dict(self.options or {})))
        # not just silently ignoring the authorization header, because not properly migrated v6 clients
        # could start without an api_key and get 401s and serve cached flags
        if any(key.lower() == "authorization" for key in self.headers):
            raise ValueError(
                "Pass the API key as api_key to the client, "
                "not as an Authorization header in HttpOptions.headers."
            )


@dataclass(frozen=True, kw_only=True)
class IdentityOptions:
    """
    How the client identifies itself to the Unleash server.

    :param environment: Name of the environment, sent as part of the context.
    :param instance_id: Unique identifier for this client instance.
    :param sdk_flavor: Identifier of an integration built on top of this SDK. Leave unset for plain SDK usage.
    :param sdk_flavor_version: Version of the integration named by sdk_flavor.
    """

    environment: str = "default"
    instance_id: str = "unleash-python-sdk"
    sdk_flavor: Optional[str] = None
    sdk_flavor_version: Optional[str] = None


@dataclass(frozen=True, kw_only=True)
class PollingOptions:
    """
    Receive flag updates by polling the Unleash server.

    :param interval: Refresh interval in seconds.
    :param jitter: Maximum random delay, in seconds, added to each refresh.
    :param project_name: Only fetch the feature flags of this project.
    """

    interval: int = 15
    jitter: Optional[int] = None
    project_name: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "jitter", _optional_int(self.jitter))


@dataclass(frozen=True, kw_only=True)
class StreamingOptions:
    """
    Receive flag updates over a streaming connection to the Unleash server.
    Experimental, only supported by the sync client.
    """


@dataclass(frozen=True, kw_only=True)
class MetricsOptions:
    """
    How the client reports to the Unleash server.

    :param interval: Metrics send interval in seconds.
    :param jitter: Maximum random delay, in seconds, added to each metrics send.
    :param disabled: Disables sending metrics to the Unleash server.
    :param disable_registration: Disables registering the client with the Unleash server.
    """

    interval: int = 60
    jitter: Optional[int] = None
    disabled: bool = False
    disable_registration: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "jitter", _optional_int(self.jitter))


@dataclass(frozen=True)
class UnleashConfig:
    """
    Normalized constructor arguments, shared by every Unleash client flavor.
    Immutable once constructed.

    Types are not validated or coerced beyond ``url.rstrip("/")`` and ``int()``
    on the two jitters.  Option groups left as None get their defaults.

    ``api_key`` is optional because a client that only loads from a backup never talks to the server.
    """

    url: str
    app_name: str
    _: KW_ONLY
    # repr=False: the dataclass __repr__ would otherwise put the API key into
    # logs and tracebacks.
    api_key: Optional[str] = field(default=None, repr=False)
    identity: IdentityOptions = field(default_factory=IdentityOptions)
    http: HttpOptions = field(default_factory=HttpOptions)
    mode: Union[PollingOptions, StreamingOptions] = field(
        default_factory=PollingOptions
    )
    metrics: MetricsOptions = field(default_factory=MetricsOptions)
    verbose_log_level: int = 30
    connection_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        object.__setattr__(self, "url", self.url.rstrip("/"))
        if self.identity is None:
            object.__setattr__(self, "identity", IdentityOptions())
        if self.http is None:
            object.__setattr__(self, "http", HttpOptions())
        if self.mode is None:
            object.__setattr__(self, "mode", PollingOptions())
        if self.metrics is None:
            object.__setattr__(self, "metrics", MetricsOptions())
        if not isinstance(self.mode, (PollingOptions, StreamingOptions)):
            LOGGER.warning(
                "mode must be PollingOptions or StreamingOptions, got %s. "
                "Polling instead.",
                type(self.mode).__name__,
            )
            object.__setattr__(self, "mode", PollingOptions())

    @property
    def static_context(self) -> Dict[str, Any]:
        return {"appName": self.app_name, "environment": self.identity.environment}

    @property
    def metrics_interval_str_millis(self) -> str:
        return str(self.metrics.interval * 1000)

    @property
    def impact_metrics_environment(self) -> str:
        return (
            extract_environment_from_api_key(self.api_key) or self.identity.environment
        )

    @property
    def instance_identifier(self) -> str:
        return f"apiKey:{redact_to_print_safely(self.api_key)} appName:{self.app_name} instanceId:{self.identity.instance_id}"
