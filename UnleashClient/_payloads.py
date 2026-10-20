"""Request payload assembly, shared by the sync and async Unleash clients."""

from datetime import datetime, timezone
from platform import python_implementation, python_version
from typing import Any, Dict, Optional

from yggdrasil_engine.engine import UnleashEngine

from UnleashClient.config import UnleashConfig
from UnleashClient.constants import CLIENT_SPEC_VERSION, SDK_NAME, SDK_VERSION


def _client_metadata(config: UnleashConfig) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {
        "appName": config.app_name,
        "instanceId": config.identity.instance_id,
        "connectionId": config.connection_id,
        "platformName": python_implementation(),
        "platformVersion": python_version(),
        "yggdrasilVersion": UnleashEngine.get_core_version(),
        "specVersion": CLIENT_SPEC_VERSION,
    }
    if config.identity.sdk_flavor:
        metadata["sdkFlavor"] = config.identity.sdk_flavor
    if config.identity.sdk_flavor_version:
        metadata["sdkFlavorVersion"] = config.identity.sdk_flavor_version

    return metadata


def _build_register_payload(
    config: UnleashConfig, strategies: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Build the body of a client registration request.

    ``started`` is stamped when this is called.

    :param config: read for the metrics interval.
    :param strategies: the strategy mapping; only its keys are sent.
    """
    return {
        **_client_metadata(config),
        "sdkVersion": f"{SDK_NAME}:{SDK_VERSION}",
        "strategies": [*strategies],
        "started": datetime.now(timezone.utc).isoformat(),
        "interval": config.metrics.interval,
    }


def _build_metrics_payload(
    config: UnleashConfig,
    bucket: Optional[Dict[str, Any]],
    impact_metrics: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Build the body of a metrics submission.

    :param bucket: the engine's toggle metrics bucket, or None when nothing was counted.
    :param impact_metrics: impact metrics collected for this send, if any.
    """
    payload: Dict[str, Any] = {**_client_metadata(config), "bucket": bucket}
    if impact_metrics:
        payload["impactMetrics"] = impact_metrics

    return payload
