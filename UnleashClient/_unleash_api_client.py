import json
import uuid
from typing import Any, Dict, NamedTuple, Optional, Tuple

from UnleashClient._event_dispatcher import _EventDispatcher
from UnleashClient._headers import _HeaderFactory
from UnleashClient._retry import _send_with_retries
from UnleashClient.config import PollingOptions, UnleashConfig
from UnleashClient.constants import FEATURES_URL, METRICS_URL, REGISTER_URL
from UnleashClient.events import (
    FetchStatus,
    UnleashEventType,
    UnleashFetchCompletedEvent,
)
from UnleashClient.transport import (
    Method,
    Request,
    RequestsTransport,
    Response,
    Transport,
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


def _header(resp: Response, name: str) -> str:
    name = name.lower()
    for key, value in resp.headers.items():
        if key.lower() == name:
            return value
    return ""


def _text(resp: Response) -> str:
    return resp.body.decode("utf-8", errors="replace")


def _log_resp_info(resp: Response) -> None:
    LOGGER.debug("HTTP status code: %s", resp.status)
    LOGGER.debug("HTTP headers: %s", resp.headers)
    LOGGER.debug("HTTP content: %s", _text(resp))


class _UnleashApiClient:
    """
    Talks to the Unleash API: feature fetches, client registration and metrics
    submission. Builds each request and decides what its response means; the
    transport only sends it.

    :param config: Client configuration.
    :param headers: Builds the header set each endpoint needs.
    :param events: Receives ``FETCH_COMPLETED`` after every feature fetch.
    :param transport: Sends the requests. Defaults to a :class:`RequestsTransport`
                      built from ``config.http``. A transport passed in is never
                      closed: whoever created it closes it.
    """

    def __init__(
        self,
        config: UnleashConfig,
        headers: _HeaderFactory,
        events: Optional[_EventDispatcher] = None,
        transport: Optional[Transport] = None,
    ) -> None:
        self._config: UnleashConfig = config
        self._headers: _HeaderFactory = headers
        self._events: Optional[_EventDispatcher] = events

        self._transport: Transport = transport or RequestsTransport(
            timeout=config.http.timeout,
            # this is going to go away soon, just like the whole httpOptions in the client constructor
            _request_kwargs=config.http.options,
        )

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

            resp = _send_with_retries(
                self._transport,
                Request(
                    method=Method.GET,
                    url=base_url,
                    headers={
                        **self._headers.polling(options),
                        **request_specific_headers,
                    },
                    params=base_params,
                ),
                config.http.retries,
            )

            http_status_code = resp.status
            if resp.status not in [200, 304]:
                _log_resp_info(resp)
                LOGGER.warning(
                    "Unleash Client feature fetch failed due to unexpected HTTP status code: %s",
                    resp.status,
                )
                raise Exception(
                    "Unleash Client feature fetch failed!"
                )  # pylint: disable=broad-exception-raised

            fetched_etag = _header(resp, "etag")

            if resp.status == 304:
                return (
                    FetchResult(None, fetched_etag, not_modified=True),
                    FetchStatus.NOT_CHANGED,
                )

            raw_state = _text(resp)
            return FetchResult(raw_state, fetched_etag), _fetched_status(raw_state)
        except Exception as exc:
            LOGGER.exception(
                "Unleash Client feature fetch failed due to exception: %s", exc
            )

        return FetchResult(None, ""), _failure_status(http_status_code)

    def register(self, payload: Dict[str, Any]) -> bool:
        """
        Register this client with the Unleash server.

        Any exception from the transport is a failed request: it is logged and
        False is returned.

        :param payload: Registration request body.
        :return: True on 200 or 202; False on any other status and on a request
                 error.
        """
        config = self._config
        LOGGER.info("Registering unleash client with unleash @ %s", config.url)
        LOGGER.info("Registration request information: %s", payload)

        request = Request(
            method=Method.POST,
            url=_normalized_url(config.url, REGISTER_URL),
            headers=self._headers.base(),
            body=json.dumps(payload).encode("utf-8"),
        )
        try:
            resp = self._transport.execute(request)
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.exception(
                "Unleash Client registration failed due to exception: %s", exc
            )
            return False

        if resp.status not in {200, 202}:
            _log_resp_info(resp)
            LOGGER.warning(
                "Unleash Client registration failed due to unexpected HTTP status code: %s",
                resp.status,
            )
            return False

        LOGGER.info("Unleash Client successfully registered!")

        return True

    def send_metrics(self, payload: Dict[str, Any]) -> bool:
        """
        Send one metrics bucket to the Unleash server.

        Any exception from the transport is a failed request: it is logged and
        False is returned.

        :param payload: Metrics request body.
        :return: True on 202; False on any other status and on a request error.
        """
        config = self._config
        LOGGER.info("Sending messages to with unleash @ %s", config.url)
        LOGGER.info("unleash metrics information: %s", payload)

        request = Request(
            method=Method.POST,
            url=_normalized_url(config.url, METRICS_URL),
            headers=self._headers.metrics(),
            body=json.dumps(payload).encode("utf-8"),
        )
        try:
            resp = self._transport.execute(request)
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.warning(
                "Unleash Client metrics submission failed due to exception: %s", exc
            )
            return False

        if resp.status != 202:
            _log_resp_info(resp)
            LOGGER.warning(
                "Unleash Client metrics submission due to unexpected HTTP status code: %s",
                resp.status,
            )
            return False

        LOGGER.info("Unleash Client metrics successfully sent!")

        return True
