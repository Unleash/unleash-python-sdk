import json
from typing import Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import InvalidHeader, InvalidSchema, InvalidURL, MissingSchema
from urllib3 import Retry

from UnleashClient.api.packet_building import build_registration_packet
from UnleashClient.constants import (
    APPLICATION_HEADERS,
    FEATURES_URL,
    METRICS_URL,
    REGISTER_URL,
)
from UnleashClient.utils import LOGGER, log_resp_info


# pylint: disable=broad-except
def register_client_async(
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

    registration_request = build_registration_packet(
        app_name, instance_id, connection_id, metrics_interval, supported_strategies
    )

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

        if resp.status_code not in {200, 202}:
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
        LOGGER.info("unleash metrics information: %s", request_body)

        resp = requests.post(
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


# pylint: disable=broad-except
def get_feature_toggles(
    url: str,
    app_name: str,
    instance_id: str,
    headers: dict,
    custom_options: dict,
    request_timeout: int,
    request_retries: int,
    project: Optional[str] = None,
    cached_etag: str = "",
) -> Tuple[str, str]:
    """
    Retrieves feature flags from unleash central server.

    Notes:
    * If unsuccessful (i.e. not HTTP status code 200), exception will be caught and logged.
      This is to allow "safe" error handling if unleash server goes down.

    :param url:
    :param app_name:
    :param instance_id:
    :param headers:
    :param custom_options:
    :param request_timeout:
    :param request_retries:
    :param project:
    :param cached_etag:
    :return: (Feature flags, etag) if successful, ({},'') if not
    """
    try:
        LOGGER.info("Getting feature flag.")

        request_specific_headers = {
            "UNLEASH-APPNAME": app_name,
            "UNLEASH-INSTANCEID": instance_id,
        }

        if cached_etag:
            request_specific_headers["If-None-Match"] = cached_etag

        base_url = f"{url}{FEATURES_URL}"
        base_params = {}

        if project:
            base_params = {"project": project}

        adapter = HTTPAdapter(
            max_retries=Retry(total=request_retries, status_forcelist=[500, 502, 504])
        )
        with requests.Session() as session:
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            resp = session.get(
                base_url,
                headers={**headers, **request_specific_headers},
                params=base_params,
                timeout=request_timeout,
                **custom_options,
            )

        if resp.status_code not in [200, 304]:
            log_resp_info(resp)
            LOGGER.warning(
                "Unleash Client feature fetch failed due to unexpected HTTP status code: %s",
                resp.status_code,
            )
            raise Exception(
                "Unleash Client feature fetch failed!"
            )  # pylint: disable=broad-exception-raised

        etag = ""
        if "etag" in resp.headers.keys():
            etag = resp.headers["etag"]

        if resp.status_code == 304:
            return None, etag

        return resp.text, etag
    except Exception as exc:
        LOGGER.exception(
            "Unleash Client feature fetch failed due to exception: %s", exc
        )

    return None, ""
