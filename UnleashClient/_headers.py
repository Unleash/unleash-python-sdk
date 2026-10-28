"""HTTP header assembly, shared by the sync and async Unleash clients."""

from typing import Dict

from UnleashClient.config import PollingOptions, UnleashConfig
from UnleashClient.constants import APPLICATION_HEADERS, SDK_NAME, SDK_VERSION


class _HeaderFactory:
    """
    Builds the header sets the SDK sends to Unleash.

    Every method builds a new dict on each call, so a caller can change the
    headers it was given without affecting the config or other callers.

    Example::

        headers = _HeaderFactory(config)
        response = requests.get(url, headers=headers.polling(options))
    """

    def __init__(self, config: UnleashConfig) -> None:
        self._config: UnleashConfig = config

    def base(self) -> Dict[str, str]:
        return {
            # Custom headers go first: the application and identification
            # headers below are not overridable.
            **self._config.http.headers,
            # HttpOptions rejects an Authorization header, so the custom
            # headers cannot override the API key.
            **({"Authorization": self._config.api_key} if self._config.api_key else {}),
            **APPLICATION_HEADERS,
            "unleash-connection-id": self._config.connection_id,
            "unleash-appname": self._config.app_name,
            "unleash-instanceid": self._config.identity.instance_id,
            "unleash-sdk": f"{SDK_NAME}:{SDK_VERSION}",
        }

    def polling(self, options: PollingOptions) -> Dict[str, str]:
        return {
            **self.base(),
            "unleash-interval": str(options.interval * 1000),
        }

    def metrics(self) -> Dict[str, str]:
        return {
            **self.base(),
            "unleash-interval": self._config.metrics_interval_str_millis,
        }

    def streaming(self) -> Dict[str, str]:
        return {**self.base(), "Accept": "text/event-stream"}
