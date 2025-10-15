from platform import python_implementation, python_version

import yggdrasil_engine
from yggdrasil_engine.engine import UnleashEngine

from ...api.asynchronous import send_metrics
from ...constants import CLIENT_SPEC_VERSION
from ...utils import LOGGER


async def aggregate_and_send_metrics(
    url: str,
    app_name: str,
    instance_id: str,
    connection_id: str,
    headers: dict,
    custom_options: dict,
    request_timeout: int,
    engine: UnleashEngine,
) -> None:
    """
    Aggregates and sends metrics to Unleash server asynchronously.

    :param url: Unleash server URL
    :param app_name: Application name
    :param instance_id: Instance ID
    :param connection_id: Connection ID
    :param headers: Request headers
    :param custom_options: Custom request options
    :param request_timeout: Request timeout
    :param engine: Engine instance
    """
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
        await send_metrics(
            url, metrics_request, headers, custom_options, request_timeout
        )
    else:
        LOGGER.debug("No feature flags with metrics, skipping metrics submission.")
