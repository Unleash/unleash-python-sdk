import asyncio
from typing import Any, Mapping, Optional, Tuple
import aiohttp

import json
from UnleashClient.api.packet_building import build_registration_packet
from UnleashClient.constants import APPLICATION_HEADERS, FEATURES_URL, REGISTER_URL
from UnleashClient.utils import LOGGER


_TRANSIENT_ERROR_CODES = {500, 502, 504}


def _backoff(attempt: int) -> float:
    return min(0.5 * (2**attempt), 5.0)


async def register_client_async(
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
    payload = build_registration_packet(
        app_name, instance_id, connection_id, metrics_interval, supported_strategies
    )

    LOGGER.info("Registering unleash client with unleash @ %s", url)
    LOGGER.info("Registration request information: %s", payload)

    timeout = aiohttp.ClientTimeout(total=request_timeout)
    session_kwargs = _session_opts_from(custom_options)

    try:
        async with aiohttp.ClientSession(timeout=timeout, **session_kwargs) as session:
            async with session.post(
                url + REGISTER_URL,
                data=json.dumps(payload),
                headers={**headers, **APPLICATION_HEADERS},
            ) as resp:
                if resp.status in (200, 202):
                    LOGGER.info("Unleash Client successfully registered!")
                    return True

                body = await resp.text()
                LOGGER.warning(
                    "Unleash Client registration failed due to unexpected HTTP status code: %s; body: %r",
                    resp.status,
                    body,
                )
                return False

    except (aiohttp.InvalidURL, ValueError) as exc:
        LOGGER.exception(
            "Registration failed fatally due to invalid request parameters: %s", exc
        )
        raise
    except (aiohttp.ClientError, TimeoutError) as exc:
        LOGGER.exception("Registration failed due to exception: %s", exc)
        return False


async def send_metrics_async(
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

        timeout = aiohttp.ClientTimeout(total=request_timeout)
        session_kwargs = _session_opts_from(custom_options)

        async with aiohttp.ClientSession(timeout=timeout, **session_kwargs) as session:
            async with session.post(
                url,
                data=json.dumps(request_body),
                headers={**headers, **APPLICATION_HEADERS},
            ) as resp:
                if resp.status == 200:
                    LOGGER.info("Unleash Client metrics successfully sent!")
                    return True

                body = await resp.text()
                LOGGER.warning(
                    "Unleash Client metrics sending failed due to unexpected HTTP status code: %s; body: %r",
                    resp.status,
                    body,
                )
                return False
    except aiohttp.ClientError as exc:
        LOGGER.warning(
            "Unleash Client metrics submission failed due to exception: %s", exc
        )
    return False


async def get_feature_toggles_async(
    url: str,
    app_name: str,
    instance_id: str,
    headers: dict,
    custom_options: dict,
    request_timeout: int,
    request_retries: int,
    project: Optional[str] = None,
    cached_etag: str = "",
) -> Tuple[Optional[str], str]:
    try:
        LOGGER.info("Getting feature flag.")
        timeout = aiohttp.ClientTimeout(total=request_timeout)
        session_kwargs = _session_opts_from(custom_options)

        base_url = f"{url}{FEATURES_URL}"
        params = {"project": project} if project else None

        request_specific_headers = {
            "UNLEASH-APPNAME": app_name,
            "UNLEASH-INSTANCEID": instance_id,
        }
        if cached_etag:
            request_specific_headers["If-None-Match"] = cached_etag

        async with aiohttp.ClientSession(timeout=timeout, **session_kwargs) as session:
            for attempt in range(request_retries + 1):
                try:
                    async with session.get(
                        base_url,
                        headers={**headers, **request_specific_headers},
                        params=params,
                    ) as resp:
                        status = resp.status
                        etag = resp.headers.get("etag", "")

                        if status == 304:
                            return None, etag
                        if status == 200:
                            body = await resp.text()
                            return body, etag

                        body = await resp.text()
                        if (
                            status in _TRANSIENT_ERROR_CODES
                            and attempt < request_retries
                        ):
                            LOGGER.debug(
                                "Feature fetch got %s; retrying attempt %d/%d",
                                status,
                                attempt + 1,
                                request_retries,
                            )
                            await asyncio.sleep(_backoff(attempt))
                            continue

                        LOGGER.warning(
                            "Unleash Client feature fetch failed due to unexpected HTTP status code: %s; body: %r",
                            status,
                            body,
                        )
                        raise Exception("Unleash Client feature fetch failed!")
                except aiohttp.ClientError as exc:
                    if attempt < request_retries:
                        LOGGER.debug("Feature fetch client error (%s); retrying", exc)
                        await asyncio.sleep(_backoff(attempt))
                        continue
                    LOGGER.exception(
                        "Unleash Client feature fetch failed due to exception: %s", exc
                    )
                    return None, ""
    except Exception as exc:
        LOGGER.exception(
            "Unleash Client feature fetch failed due to exception: %s", exc
        )
        return None, ""


def _session_opts_from(custom_options: Mapping[str, Any]) -> dict:
    opts: dict = {}
    if "verify" in custom_options and not custom_options["verify"]:
        opts["connector"] = aiohttp.TCPConnector(ssl=False)
    if custom_options.get("trust_env"):
        opts["trust_env"] = True
    return opts
