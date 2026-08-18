"""HTTP transport, shared by the sync and async Unleash clients."""

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

    ``raw_state`` is None both when the server answered 304 and when the fetch
    failed outright; ``not_modified`` is what tells the two apart. Nothing acts
    on that distinction yet — :class:`UnleashClient.store.FeatureStore` reloads
    from the cache in either case, as it always has.
    """

    raw_state: Optional[str]
    etag: str
    not_modified: bool = False


def _normalized_url(url: str, path: str) -> str:
    # The rstrip is not redundant with UnleashConfig.__post_init__: the
    # UnleashClient.unleash_url setter writes config.url directly and never
    # re-normalizes, so a trailing slash can be there at request time.
    return f"{url.rstrip('/')}{path}"


def _log_resp_info(resp: Response) -> None:
    LOGGER.debug("HTTP status code: %s", resp.status_code)
    LOGGER.debug("HTTP headers: %s", resp.headers)
    LOGGER.debug("HTTP content: %s", resp.text)


class Transport:
    """
    Owns every HTTP request the SDK makes to Unleash, apart from the streaming
    connection and ``FileCache.bootstrap_from_url``.

    This is a colored object: an async client needs its own implementation
    rather than this one, and the three methods below are the surface it has to
    match. Payload assembly (:mod:`UnleashClient.payloads`) lives elsewhere, so
    that an async twin duplicates the sending and nothing else.

    Each method asks the :class:`~UnleashClient.headers.HeaderFactory` for the
    header set its endpoint needs; callers pass none. Both the factory and the
    config are read on every request rather than captured, because
    ``unleash_url``, ``unleash_custom_options``, ``unleash_request_timeout``,
    ``unleash_request_retries``, ``unleash_project_name``,
    ``unleash_custom_headers``, ``unleash_app_name`` and ``unleash_instance_id``
    are all public and writable.

    Each method keeps the error handling its ``api/`` predecessor had, and the
    three are deliberately not the same: see the individual docstrings.
    """

    def __init__(self, config: UnleashConfig, headers: HeaderFactory) -> None:
        """
        :param config: read for the url, timeouts, retries, project and custom
                       options.
        :param headers: builds the header set each request needs.
        """
        self._config: UnleashConfig = config
        self._headers: HeaderFactory = headers

    # pylint: disable=broad-except
    def fetch_features(self, etag: str = "") -> FetchResult:
        """
        Fetch feature state, sending ``If-None-Match`` when an etag is known.

        Never raises. Any failure — an unexpected status, a connection error, a
        bad key in ``custom_options`` — is logged and returned as an empty
        result, so a polling job can keep running against a server that is down.

        :param etag: the cached etag, or "" to fetch unconditionally.
        """
        config = self._config
        try:
            LOGGER.info("Getting feature flag.")

            # The features endpoint has always been sent an uppercase copy of
            # the two identification headers, on top of the lowercase pair in
            # HeaderFactory.base().  It stays here rather than in polling()
            # because it is a quirk of this one endpoint, and because
            # test_polling_and_metrics_differ_only_in_the_interval pins
            # polling() against exactly this kind of addition.
            request_specific_headers = {
                "UNLEASH-APPNAME": config.app_name,
                "UNLEASH-INSTANCEID": config.instance_id,
            }

            if etag:
                request_specific_headers["If-None-Match"] = etag

            base_url = _normalized_url(config.url, FEATURES_URL)
            base_params = {}

            if config.project_name:
                base_params = {"project": config.project_name}

            adapter = HTTPAdapter(
                max_retries=Retry(
                    total=config.request_retries, status_forcelist=[500, 502, 504]
                )
            )
            # A session per fetch, as the api/ function did. One Transport is
            # reachable from the polling thread, the metrics thread and
            # destroy()'s caller at once, and requests.Session is not documented
            # as thread-safe.
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
        Register this client with the server.

        Returns True on 200 or 202, False on any other status and on a general
        ``RequestException``. Re-raises ``MissingSchema``, ``InvalidSchema``,
        ``InvalidHeader`` and ``InvalidURL``, which is what makes
        ``initialize_client()`` fail loudly on a malformed URL instead of
        starting a client that can never reach the server.

        :param payload: as built by
                        :func:`UnleashClient.payloads.build_register_payload`.
        """
        config = self._config
        try:
            LOGGER.info("Registering unleash client with unleash @ %s", config.url)
            LOGGER.info("Registration request information: %s", payload)

            resp = requests.post(
                _normalized_url(config.url, REGISTER_URL),
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
        # Ahead of the RequestException clause below: all four subclass it, and
        # Python matches the first clause that fits.
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
        Send one metrics bucket.

        Returns True only on 202; every other status is a failure, which is what
        the caller's impact-metrics restore path keys off. Catches only
        ``RequestException``, so a bad key in ``custom_options`` still surfaces
        as a ``TypeError`` to the caller rather than being reported as a failed
        send.

        :param payload: the metrics request body.
        """
        config = self._config
        try:
            LOGGER.info("Sending messages to with unleash @ %s", config.url)
            LOGGER.info("unleash metrics information: %s", payload)

            resp = requests.post(
                _normalized_url(config.url, METRICS_URL),
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
