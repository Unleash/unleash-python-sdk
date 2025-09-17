import json
from datetime import datetime, timezone
from platform import python_implementation, python_version

import requests
import yggdrasil_engine
from requests.exceptions import InvalidHeader, InvalidSchema, InvalidURL, MissingSchema

from UnleashClient.constants import (
    APPLICATION_HEADERS,
    CLIENT_SPEC_VERSION,
    REGISTER_URL,
    SDK_NAME,
    SDK_VERSION,
)
from UnleashClient.utils import LOGGER, log_resp_info


# pylint: disable=broad-except
def register_client(
    url: str,
    app_name: str,
    instance_id: str,
    connection_id: str,
    metrics_interval: int,
    headers: dict,
    custom_options: dict,
    supported_strategies: dict,
    request_timeout: int,
) -> bool:
    """
    Attempts to register client with unleash server.

    Notes:
    * If unsuccessful (i.e. not HTTP status code 202), exception will be caught and logged.
      This is to allow "safe" error handling if unleash server goes down.

    :param url:
    :param app_name:
    :param instance_id:
    :param metrics_interval:
    :param headers:
    :param custom_options:
    :param supported_strategies:
    :param request_timeout:
    :return: true if registration successful, false if registration unsuccessful or exception.
    """
    registration_request = {
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

    try:
        LOGGER.info("Registering unleash client with unleash @ %s", url)
        LOGGER.info("Registration request information: %s", registration_request)

        resp = requests.post(
            url + REGISTER_URL,
            data=json.dumps(registration_request),
            headers={**headers, **APPLICATION_HEADERS},
            timeout=request_timeout,
            **custom_options,
        )

        if resp.status_code != 200 and resp.status_code != 202:
            log_resp_info(resp)
            LOGGER.warning(
                "Unleash Client registration failed due to unexpected HTTP status code: %s",
                resp.status_code,
            )
            return False

        LOGGER.info("Unleash Client successfully registered!")

        return True
    except (MissingSchema, InvalidSchema, InvalidHeader, InvalidURL) as exc:
        LOGGER.exception(
            "Unleash Client registration failed fatally due to exception: %s", exc
        )
        raise exc
    except requests.RequestException as exc:
        LOGGER.exception("Unleash Client registration failed due to exception: %s", exc)

    return False
