import json
import uuid
from typing import Any, Dict, NamedTuple, Optional, Tuple

import requests
from requests import Response
from requests.adapters import HTTPAdapter
from requests.exceptions import InvalidHeader, InvalidSchema, InvalidURL, MissingSchema
from urllib3 import Retry

from UnleashClient._event_dispatcher import _EventDispatcher
from UnleashClient._headers import _HeaderFactory
from UnleashClient.config import PollingOptions, UnleashConfig
from UnleashClient.constants import FEATURES_URL, METRICS_URL, REGISTER_URL
from UnleashClient.events import (
    FetchStatus,
    UnleashEventType,
    UnleashFetchCompletedEvent,
)
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


def _failure_status(http_status_code: Optional[int]) -> FetchStatus:
    """Classifies a failed fetch by the response it got, if any."""
    if http_status_code is None:
        return FetchStatus.UNAVAILABLE
    if http_status_code in (401, 403):
        return FetchStatus.UNAUTHORIZED
    if http_status_code == 429:
        return FetchStatus.RATE_LIMITED
    if http_status_code >= 500:
        return FetchStatus.UNAVAILABLE
    return FetchStatus.INVALID_RESPONSE


def _fetched_status(raw_state: str) -> FetchStatus:
    """An empty 200 is not usable: there is no state to apply."""
    return FetchStatus.CHANGED if raw_state else FetchStatus.INVALID_RESPONSE


def _emit_fetch_completed(
    events: Optional[_EventDispatcher], status: FetchStatus
) -> None:
    """
    Reports how a fetch ended. Never raises: a broken listener must not break
    the fetch.
    """
    if events is None:
        return

    try:
        events.emit_event(
            UnleashFetchCompletedEvent(
                event_type=UnleashEventType.FETCH_COMPLETED,
                event_id=uuid.uuid4(),
                status=status,
            )
        )
    except Exception:  # pylint: disable=broad-except
        LOGGER.debug("Failed to emit the fetch completed event", exc_info=True)


def _normalized_url(url: str, path: str) -> str:
    return f"{url}{path}"


def _log_resp_info(resp: Response) -> None:
    LOGGER.debug("HTTP status code: %s", resp.status_code)
    LOGGER.debug("HTTP headers: %s", resp.headers)
    LOGGER.debug("HTTP content: %s", resp.text)


class _Transport:
    """
    Sends the SDK's requests to the Unleash server: feature fetches, client
    registration and metrics submission.

    :param config: Client configuration.
    :param headers: Builds the header set each endpoint needs.
    """

    def __init__(
        self,
        config: UnleashConfig,
        headers: _HeaderFactory,
        events: Optional[_EventDispatcher] = None,
    ) -> None:
        self._config: UnleashConfig = config
        self._headers: _HeaderFactory = headers
        self._events: Optional[_EventDispatcher] = events

    # pylint: disable=broad-except
    def fetch_features(self, etag: str = "", *, options: PollingOptions) -> FetchResult:
        """
        Fetch feature state, sending ``If-None-Match`` when an etag is known.

        Never raises: any failure is logged and returned as an empty result, so
        a polling job keeps running against a server that is down.

        Emits ``FETCH_COMPLETED`` with how the fetch ended, before the caller
        applies the result.

        :param etag: Etag from the last fetch, or "" to fetch unconditionally.
        :param options: The polling settings: the project to filter on, and the
                        interval reported to the server.
        :return: The fetched state, or an empty result on a 304 and on failure.
        """
        result, status = self._fetch_features(etag, options)
        _emit_fetch_completed(self._events, status)
        return result

    def _fetch_features(
        self, etag: str, options: PollingOptions
    ) -> Tuple[FetchResult, FetchStatus]:
        """The fetch itself, with how it ended."""
        config = self._config
        http_status_code: Optional[int] = None
        try:
            LOGGER.info("Getting feature flag.")

            request_specific_headers = {
                "UNLEASH-APPNAME": config.app_name,
                "UNLEASH-INSTANCEID": config.identity.instance_id,
            }

            if etag:
                request_specific_headers["If-None-Match"] = etag

            base_url = _normalized_url(config.url, FEATURES_URL)
            base_params = {}

            if options.project_name:
                base_params = {"project": options.project_name}

            adapter = HTTPAdapter(
                max_retries=Retry(
                    total=config.http.retries, status_forcelist=[500, 502, 504]
                )
            )
            with requests.Session() as session:
                session.mount("https://", adapter)
                session.mount("http://", adapter)
                resp = session.get(
                    base_url,
                    headers={
                        **self._headers.polling(options),
                        **request_specific_headers,
                    },
                    params=base_params,
                    timeout=config.http.timeout,
                    **config.http.options,
                )

            http_status_code = resp.status_code
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
                return (
                    FetchResult(None, fetched_etag, not_modified=True),
                    FetchStatus.NOT_CHANGED,
                )

            return FetchResult(resp.text, fetched_etag), _fetched_status(resp.text)
        except Exception as exc:
            LOGGER.exception(
                "Unleash Client feature fetch failed due to exception: %s", exc
            )

        return FetchResult(None, ""), _failure_status(http_status_code)

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
                _normalized_url(config.url, REGISTER_URL),
                data=json.dumps(payload),
                headers=self._headers.base(),
                timeout=config.http.timeout,
                **config.http.options,
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
                _normalized_url(config.url, METRICS_URL),
                data=json.dumps(payload),
                headers=self._headers.metrics(),
                timeout=config.http.timeout,
                **config.http.options,
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
