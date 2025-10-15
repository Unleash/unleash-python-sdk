import json

import niquests as requests

from ...constants import APPLICATION_HEADERS, METRICS_URL
from ...utils import LOGGER, log_resp_info


# pylint: disable=broad-except
async def send_metrics(
    url: str,
    request_body: dict,
    headers: dict,
    custom_options: dict,
    request_timeout: int,
) -> bool:
    """
    Attempts to send metrics to Unleash server asynchronously

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
        LOGGER.info("unleash metrics information: %s", request_body)

        async with requests.AsyncSession() as session:
            resp = await session.post(
                url + METRICS_URL,
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
