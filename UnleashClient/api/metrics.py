import json

import requests

from UnleashClient.api.urls import build_normalized_url
from UnleashClient.constants import APPLICATION_HEADERS, METRICS_URL
from UnleashClient.utils import LOGGER, log_resp_info, redact_to_print_safely


# pylint: disable=broad-except
def send_metrics(
    url: str,
    request_body: dict,
    headers: dict,
    custom_options: dict,
    request_timeout: int,
) -> bool:
    """
    Attempts to send metrics to Unleash server

    Notes:
    * If unsuccessful (i.e. not HTTP status code 200), message will be logged

    :param url:
    :param request_body:
    :param headers:
    :param custom_options:
    :param request_timeout:
    :return: true if registration successful, false if registration unsuccessful or exception.
    """
    try:
        LOGGER.info("Sending messages to with unleash @ %s", url)
        LOGGER.info(
            "unleash metrics information: %s",
            {
                **request_body,
                "instanceId": redact_to_print_safely(request_body.get("instanceId")),
            },
        )

        resp = requests.post(
            build_normalized_url(url, METRICS_URL),
            data=json.dumps(request_body),
            headers={**headers, **APPLICATION_HEADERS},
            timeout=request_timeout,
            **custom_options,
        )

        if resp.status_code != 202:
            log_resp_info(resp)
            LOGGER.warning(
                "Unleash Client metrics submission due to unexpected HTTP status code: %s",
                resp.status_code,
            )
            return False

        LOGGER.info("Unleash Client metrics successfully sent!")

        return True
    except requests.RequestException as exc:
        LOGGER.warning(
            "Unleash Client metrics submission failed due to exception: %s", exc
        )

    return False
