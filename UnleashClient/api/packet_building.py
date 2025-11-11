from datetime import datetime, timezone
from platform import python_implementation, python_version
import yggdrasil_engine
from UnleashClient.constants import (
    CLIENT_SPEC_VERSION,
    SDK_NAME,
    SDK_VERSION,
)


def build_registration_packet(
    app_name: str,
    instance_id: str,
    connection_id: str,
    metrics_interval: int,
    supported_strategies: dict,
) -> dict:
    return {
        "appName": app_name,
        "instanceId": instance_id,
        "connectionId": connection_id,
        "sdkVersion": f"{SDK_NAME}:{SDK_VERSION}",
        "strategies": [*supported_strategies],
        "started": datetime.now(timezone.utc).isoformat(),
        "interval": metrics_interval,
        "platformName": python_implementation(),
        "platformVersion": python_version(),
        "yggdrasilVersion": yggdrasil_engine.__yggdrasil_core_version__,
        "specVersion": CLIENT_SPEC_VERSION,
    }
