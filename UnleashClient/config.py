"""Configuration value object shared by the sync and async Unleash clients."""

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional, TypedDict

from UnleashClient.constants import REQUEST_RETRIES, REQUEST_TIMEOUT
from UnleashClient.utils import extract_environment_from_headers


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
    :param headers: Headers sent with every request, typically ``{"Authorization": "<API key>"}``.
    :param options: Extra keyword arguments passed to every ``requests`` call.
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
        object.__setattr__(self, "headers", dict(self.headers or {}))
        object.__setattr__(self, "options", dict(self.options or {}))


@dataclass(frozen=True)
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


@dataclass(frozen=True)
class FetchOptions:
    """
    Which feature flags the client fetches, and how.

    :param interval: Refresh interval in seconds.
    :param jitter: Maximum random delay, in seconds, added to each refresh.
    :param project_name: Only fetch the feature flags of this project.
    :param mode: "polling" (default) or "streaming".  Streaming is experimental and only supported by the sync client.
    """

    interval: int = 15
    jitter: Optional[int] = None
    project_name: Optional[str] = None
    mode: Literal["polling", "streaming"] = "polling"

    def __post_init__(self) -> None:
        object.__setattr__(self, "jitter", _optional_int(self.jitter))


@dataclass(frozen=True)
class UnleashConfig:
    """
    Normalized constructor arguments, shared by every Unleash client flavor.
    Immutable once constructed.

    Types are not validated or coerced beyond what the client constructor has
    always done: ``url.rstrip("/")`` and ``int()`` on the two jitters.
    """

    url: str
    app_name: str
    identity: IdentityOptions = field(default_factory=IdentityOptions)
    http: HttpOptions = field(default_factory=HttpOptions)
    fetching: FetchOptions = field(default_factory=FetchOptions)
    metrics_interval: int = 60
    metrics_jitter: Optional[int] = None
    disable_metrics: bool = False
    disable_registration: bool = False
    verbose_log_level: int = 30
    connection_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        object.__setattr__(self, "url", self.url.rstrip("/"))
        if self.identity is None:
            object.__setattr__(self, "identity", IdentityOptions())
        if self.http is None:
            object.__setattr__(self, "http", HttpOptions())
        if self.fetching is None:
            object.__setattr__(self, "fetching", FetchOptions())
        object.__setattr__(self, "metrics_jitter", _optional_int(self.metrics_jitter))

    @property
    def static_context(self) -> Dict[str, Any]:
        return {"appName": self.app_name, "environment": self.identity.environment}

    @property
    def refresh_interval_str_millis(self) -> str:
        return str(self.fetching.interval * 1000)

    @property
    def metrics_interval_str_millis(self) -> str:
        return str(self.metrics_interval * 1000)

    @property
    def impact_metrics_environment(self) -> str:
        return (
            extract_environment_from_headers(self.http.headers)
            or self.identity.environment
        )

    @property
    def instance_identifier(self) -> str:
        api_key = self.http.headers.get("Authorization")
        return f"apiKey:{redact_to_print_safely(api_key)} appName:{self.app_name} instanceId:{self.identity.instance_id}"
