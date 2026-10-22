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
    refresh_interval: int = 15
    refresh_jitter: Optional[int] = None
    metrics_interval: int = 60
    metrics_jitter: Optional[int] = None
    disable_metrics: bool = False
    disable_registration: bool = False
    # repr=False: the dataclass __repr__ would otherwise put the Authorization
    # API key into logs and tracebacks.
    custom_headers: Optional[Dict[str, str]] = field(default=None, repr=False)
    custom_options: Optional[dict] = None
    request_timeout: int = REQUEST_TIMEOUT
    request_retries: int = REQUEST_RETRIES
    project_name: Optional[str] = None
    verbose_log_level: int = 30
    experimental_mode: Optional[ExperimentalMode] = None
    connection_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        object.__setattr__(self, "url", self.url.rstrip("/"))
        if self.identity is None:
            object.__setattr__(self, "identity", IdentityOptions())
        object.__setattr__(self, "refresh_jitter", _optional_int(self.refresh_jitter))
        object.__setattr__(self, "metrics_jitter", _optional_int(self.metrics_jitter))
        object.__setattr__(self, "custom_headers", dict(self.custom_headers or {}))
        object.__setattr__(self, "custom_options", dict(self.custom_options or {}))
        object.__setattr__(
            self, "experimental_mode", self.experimental_mode or {"type": "polling"}
        )

    @property
    def static_context(self) -> Dict[str, Any]:
        return {"appName": self.app_name, "environment": self.identity.environment}

    @property
    def mode(self) -> str:
        return self.experimental_mode.get("type", "polling")

    @property
    def refresh_interval_str_millis(self) -> str:
        return str(self.refresh_interval * 1000)

    @property
    def metrics_interval_str_millis(self) -> str:
        return str(self.metrics_interval * 1000)

    @property
    def impact_metrics_environment(self) -> str:
        return (
            extract_environment_from_headers(self.custom_headers)
            or self.identity.environment
        )

    @property
    def instance_identifier(self) -> str:
        api_key = (
            self.custom_headers.get("Authorization")
            if self.custom_headers is not None
            else None
        )
        return f"apiKey:{redact_to_print_safely(api_key)} appName:{self.app_name} instanceId:{self.identity.instance_id}"
