from platform import python_implementation, python_version

import yggdrasil_engine
from yggdrasil_engine.engine import UnleashEngine

from UnleashClient.api.sync_api import send_metrics
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

    if metrics_bucket:
        send_metrics(url, metrics_request, headers, custom_options, request_timeout)
    else:
        LOGGER.debug("No feature flags with metrics, skipping metrics submission.")
