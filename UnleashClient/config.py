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


@dataclass
class UnleashConfig:
    """
    Normalized constructor arguments, shared by every Unleash client flavor.

    Types are not validated or coerced beyond what the client constructor has
    always done: ``url.rstrip("/")`` and ``int()`` on the two jitters.
    """

    url: str
    app_name: str
    environment: str = "default"
    instance_id: str = "unleash-python-sdk"
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
    sdk_flavor: Optional[str] = None
    sdk_flavor_version: Optional[str] = None
    experimental_mode: Optional[ExperimentalMode] = None
    connection_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    # Appended after connection_id so no existing positional argument shifts.
    custom_strategies: Optional[dict] = None
    static_context: Dict[str, Any] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self.url = self.url.rstrip("/")
        self.refresh_jitter = (
            int(self.refresh_jitter) if self.refresh_jitter is not None else None
        )
        self.metrics_jitter = (
            int(self.metrics_jitter) if self.metrics_jitter is not None else None
        )
        # `or` rather than `is None`, so that passing {} yields a fresh dict,
        # as the client constructor has always done.
        self.custom_headers = self.custom_headers or {}
        self.custom_options = self.custom_options or {}
        self.custom_strategies = self.custom_strategies or {}
        self.experimental_mode = self.experimental_mode or {"type": "polling"}
        self.static_context = {
            "appName": self.app_name,
            "environment": self.environment,
        }

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
        return extract_environment_from_headers(self.custom_headers) or self.environment

    @property
    def instance_identifier(self) -> str:
        api_key = (
            self.custom_headers.get("Authorization")
            if self.custom_headers is not None
            else None
        )
        return f"apiKey:{redact_to_print_safely(api_key)} appName:{self.app_name} instanceId:{self.instance_id}"
