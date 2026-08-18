"""Request payload assembly, shared by the sync and async Unleash clients."""

from datetime import datetime, timezone
from platform import python_implementation, python_version
from typing import Any, Dict

import yggdrasil_engine

from UnleashClient.config import UnleashConfig
from UnleashClient.constants import CLIENT_SPEC_VERSION, SDK_NAME, SDK_VERSION


def build_register_payload(
    config: UnleashConfig, strategies: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Build the body of a client registration request.

    Called immediately before the request, as it was when this dict lived at the
    top of ``register_client``: ``started`` is the moment of the call, not the
    moment the client was constructed.

    :param config: read for the app name, instance id, connection id, metrics
                   interval and the two SDK flavor fields.
    :param strategies: the strategy mapping; only its keys are sent.
    """
    payload: Dict[str, Any] = {
        "appName": config.app_name,
        "instanceId": config.instance_id,
        "connectionId": config.connection_id,
        "sdkVersion": f"{SDK_NAME}:{SDK_VERSION}",
        "strategies": [*strategies],
        "started": datetime.now(timezone.utc).isoformat(),
        "interval": config.metrics_interval,
        "platformName": python_implementation(),
        "platformVersion": python_version(),
        "yggdrasilVersion": yggdrasil_engine.__yggdrasil_core_version__,
        "specVersion": CLIENT_SPEC_VERSION,
    }
    # Only sent when the client was configured with an integration flavor
    if config.sdk_flavor:
        payload["sdkFlavor"] = config.sdk_flavor
    if config.sdk_flavor_version:
        payload["sdkFlavorVersion"] = config.sdk_flavor_version

    return payload
