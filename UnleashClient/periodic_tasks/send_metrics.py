from platform import python_implementation, python_version

import yggdrasil_engine
from yggdrasil_engine.engine import UnleashEngine

from UnleashClient.api import send_metrics
from UnleashClient.constants import CLIENT_SPEC_VERSION
from UnleashClient.utils import LOGGER


def aggregate_and_send_metrics(
    url: str,
    app_name: str,
    instance_id: str,
    connection_id: str,
    headers: dict,
    custom_options: dict,
    request_timeout: int,
    engine: UnleashEngine,
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

    if impact_metrics:
        metrics_request["impactMetrics"] = impact_metrics

    if metrics_bucket or impact_metrics:
        success = send_metrics(
            url, metrics_request, headers, custom_options, request_timeout
        )
        if not success and impact_metrics:
            engine.restore_impact_metrics(impact_metrics)
    else:
        LOGGER.debug("No feature flags with metrics, skipping metrics submission.")
