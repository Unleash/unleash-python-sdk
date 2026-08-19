"""HTTP header assembly, shared by the sync and async Unleash clients."""

from typing import Dict

from UnleashClient.config import UnleashConfig
from UnleashClient.constants import APPLICATION_HEADERS, SDK_NAME, SDK_VERSION


class HeaderFactory:
    """
    Builds the header sets the SDK sends to Unleash.

    Every method returns a fresh dict and reads the config on each call, so
    reassigning or mutating ``config.custom_headers`` (which
    ``UnleashClient.unleash_custom_headers`` allows) is picked up by the next
    call. The clients call each method once, at initialization, and pass the
    resulting dict on; a connector that is already running keeps the headers it
    was given.
    """

    def __init__(self, config: UnleashConfig) -> None:
        self._config: UnleashConfig = config

    def base(self) -> Dict[str, str]:
        return {
            # Custom headers go first: the application and identification
            # headers below are not overridable.  `or {}` because the field is
            # declared Optional, though __post_init__ has already replaced None.
            **(self._config.custom_headers or {}),
            **APPLICATION_HEADERS,
            "unleash-connection-id": self._config.connection_id,
            "unleash-appname": self._config.app_name,
            "unleash-instanceid": self._config.instance_id,
            "unleash-sdk": f"{SDK_NAME}:{SDK_VERSION}",
        }

    def polling(self) -> Dict[str, str]:
        return {
            **self.base(),
            "unleash-interval": self._config.refresh_interval_str_millis,
        }

    def metrics(self) -> Dict[str, str]:
        return {
            **self.base(),
            "unleash-interval": self._config.metrics_interval_str_millis,
        }

    def streaming(self) -> Dict[str, str]:
        return {**self.base(), "Accept": "text/event-stream"}
