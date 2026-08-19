import json
from typing import Any, Dict, NamedTuple, Optional

import requests
from requests import Response
from requests.adapters import HTTPAdapter
from requests.exceptions import InvalidHeader, InvalidSchema, InvalidURL, MissingSchema
from urllib3 import Retry

from UnleashClient.config import UnleashConfig
from UnleashClient.constants import FEATURES_URL, METRICS_URL, REGISTER_URL
from UnleashClient.headers import HeaderFactory
from UnleashClient.utils import LOGGER


class FetchResult(NamedTuple):
    """
    The outcome of one feature fetch.

    :param raw_state: Feature state body, or None on a 304 and on failure.
    :param etag: ETag returned by the server, or "" when the response had none.
    :param not_modified: True when the server answered 304.
    """

    raw_state: Optional[str]
    etag: str
    not_modified: bool = False


def normalized_url(url: str, path: str) -> str:
    # config.url can carry a trailing slash: the UnleashClient.unleash_url setter
    # writes it without re-normalizing.
    return f"{url.rstrip('/')}{path}"


def _log_resp_info(resp: Response) -> None:
    LOGGER.debug("HTTP status code: %s", resp.status_code)
    LOGGER.debug("HTTP headers: %s", resp.headers)
    LOGGER.debug("HTTP content: %s", resp.text)


class Transport:
    """
    Sends the SDK's requests to the Unleash server: feature fetches, client
    registration and metrics submission.

    Config and headers are read on every request, so changes to the client's
    writable settings (url, timeouts, retries, project, custom headers and
    options) take effect on the next call.

    :param config: Client configuration.
    :param headers: Builds the header set each endpoint needs.
    """

    def __init__(self, config: UnleashConfig, headers: HeaderFactory) -> None:
        self._config: UnleashConfig = config
        self._headers: HeaderFactory = headers

    # pylint: disable=broad-except
    def fetch_features(self, etag: str = "") -> FetchResult:
        """
        Fetch feature state, sending ``If-None-Match`` when an etag is known.

        Never raises: any failure is logged and returned as an empty result, so
        a polling job keeps running against a server that is down.

        :param etag: Etag from the last fetch, or "" to fetch unconditionally.
        :return: The fetched state, or an empty result on a 304 and on failure.
        """
        config = self._config
        try:
            LOGGER.info("Getting feature flag.")

            request_specific_headers = {
                "UNLEASH-APPNAME": config.app_name,
                "UNLEASH-INSTANCEID": config.instance_id,
            }

            if etag:
                request_specific_headers["If-None-Match"] = etag

            base_url = normalized_url(config.url, FEATURES_URL)
            base_params = {}

            if config.project_name:
                base_params = {"project": config.project_name}

            adapter = HTTPAdapter(
                max_retries=Retry(
                    total=config.request_retries, status_forcelist=[500, 502, 504]
                )
            )
            with requests.Session() as session:
                session.mount("https://", adapter)
                session.mount("http://", adapter)
                resp = session.get(
                    base_url,
                    headers={**self._headers.polling(), **request_specific_headers},
                    params=base_params,
                    timeout=config.request_timeout,
                    **config.custom_options,
                )

            if resp.status_code not in [200, 304]:
                _log_resp_info(resp)
                LOGGER.warning(
                    "Unleash Client feature fetch failed due to unexpected HTTP status code: %s",
                    resp.status_code,
                )
                raise Exception(
                    "Unleash Client feature fetch failed!"
                )  # pylint: disable=broad-exception-raised

            fetched_etag = ""
            if "etag" in resp.headers.keys():
                fetched_etag = resp.headers["etag"]

            if resp.status_code == 304:
                return FetchResult(None, fetched_etag, not_modified=True)

            return FetchResult(resp.text, fetched_etag)
        except Exception as exc:
            LOGGER.exception(
                "Unleash Client feature fetch failed due to exception: %s", exc
            )

        return FetchResult(None, "")

    def register(self, payload: Dict[str, Any]) -> bool:
        """
        Register this client with the Unleash server.

        Malformed-URL errors (``MissingSchema``, ``InvalidSchema``,
        ``InvalidHeader``, ``InvalidURL``) propagate, so ``initialize_client()``
        fails loudly instead of starting a client that can never reach the
        server.

        :param payload: Registration request body.
        :return: True on 200 or 202; False on any other status and on a request
                 error.
        """
        config = self._config
        try:
            LOGGER.info("Registering unleash client with unleash @ %s", config.url)
            LOGGER.info("Registration request information: %s", payload)

            resp = requests.post(
                normalized_url(config.url, REGISTER_URL),
                data=json.dumps(payload),
                headers=self._headers.base(),
                timeout=config.request_timeout,
                **config.custom_options,
            )

            if resp.status_code not in {200, 202}:
                _log_resp_info(resp)
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
            LOGGER.exception(
                "Unleash Client registration failed due to exception: %s", exc
            )

        return False

    def send_metrics(self, payload: Dict[str, Any]) -> bool:
        """
        Send one metrics bucket to the Unleash server.

        :param payload: Metrics request body.
        :return: True on 202; False on any other status and on a request error.
        """
        config = self._config
        try:
            LOGGER.info("Sending messages to with unleash @ %s", config.url)
            LOGGER.info("unleash metrics information: %s", payload)

            resp = requests.post(
                normalized_url(config.url, METRICS_URL),
                data=json.dumps(payload),
                headers=self._headers.metrics(),
                timeout=config.request_timeout,
                **config.custom_options,
            )

            if resp.status_code != 202:
                _log_resp_info(resp)
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
