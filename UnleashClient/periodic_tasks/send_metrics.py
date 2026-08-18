from platform import python_implementation, python_version
from typing import Optional

import yggdrasil_engine
from yggdrasil_engine.engine import UnleashEngine

from UnleashClient.constants import CLIENT_SPEC_VERSION
from UnleashClient.transport import Transport
from UnleashClient.utils import LOGGER


def aggregate_and_send_metrics(
    transport: Transport,
    app_name: str,
    instance_id: str,
    connection_id: str,
    engine: UnleashEngine,
    sdk_flavor: Optional[str] = None,
    sdk_flavor_version: Optional[str] = None,
) -> None:
    metrics_bucket = engine.get_metrics()

    try:
        impact_metrics = engine.collect_impact_metrics()
    except Exception as exc:
        LOGGER.warning("Failed to collect impact metrics: %s", exc)
        impact_metrics = None

    metrics_request = {
        "appName": app_name,
        "instanceId": instance_id,
        "connectionId": connection_id,
        "bucket": metrics_bucket,
        "platformName": python_implementation(),
        "platformVersion": python_version(),
        "yggdrasilVersion": yggdrasil_engine.__yggdrasil_core_version__,
        "specVersion": CLIENT_SPEC_VERSION,
    }
    # Only sent when the client was configured with an integration flavor
    if sdk_flavor:
        metrics_request["sdkFlavor"] = sdk_flavor
    if sdk_flavor_version:
        metrics_request["sdkFlavorVersion"] = sdk_flavor_version

    if impact_metrics:
        metrics_request["impactMetrics"] = impact_metrics

    if metrics_bucket or impact_metrics:
        success = transport.send_metrics(metrics_request)
        if not success and impact_metrics:
            engine.restore_impact_metrics(impact_metrics)
    else:
        LOGGER.debug("No feature flags with metrics, skipping metrics submission.")
