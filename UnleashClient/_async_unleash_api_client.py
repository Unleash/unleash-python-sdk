"""Unleash API client for the async Unleash client."""

import asyncio
import json
import threading
from typing import Any, Dict, Optional, Tuple

from UnleashClient._aiohttp_transport import AiohttpTransport
from UnleashClient._event_dispatcher import _EventDispatcher
from UnleashClient._headers import _HeaderFactory
from UnleashClient._retry import _send_with_retries_async
from UnleashClient._unleash_api_client import (
    FetchResult,
    _emit_fetch_completed,
    _failure_status,
    _fetched_status,
    _header,
    _log_resp_info,
    _normalized_url,
    _text,
)
from UnleashClient.config import PollingOptions, UnleashConfig
from UnleashClient.constants import FEATURES_URL, METRICS_URL, REGISTER_URL
from UnleashClient.errors import AlreadyClosedError
from UnleashClient.events import FetchStatus
from UnleashClient.transport import AsyncTransport, Request
from UnleashClient.utils import LOGGER


class _AsyncUnleashApiClient:
    """The asyncio twin of :class:`UnleashClient._unleash_api_client._UnleashApiClient`."""

    def __init__(
        self,
        config: UnleashConfig,
        headers: _HeaderFactory,
        events: Optional[_EventDispatcher] = None,
        transport: Optional[AsyncTransport] = None,
    ) -> None:
        """
        :param config: read for the url, timeouts, retries and project.
        :param headers: builds the header set each request needs.
        :param events: receives ``FETCH_COMPLETED`` after every feature fetch.
        :param transport: sends the requests. Defaults to an
                          :class:`AiohttpTransport` built from ``config.http``,
                          which :meth:`aclose` closes. A transport passed in is
                          left open: whoever created it closes it.
        """
        self._config: UnleashConfig = config
        self._headers: _HeaderFactory = headers
        self._events: Optional[_EventDispatcher] = events
        # set only when this API client built the transport, and so it closes it.
        self._default_transport: Optional[AiohttpTransport] = None
        if transport is None:
            transport = self._default_transport = AiohttpTransport(
                timeout=config.http.timeout
            )
        self._transport: AsyncTransport = transport
        self._is_closed: bool = False
        self._close_lock = threading.Lock()

    def _raise_if_closed(self) -> None:
        if self._is_closed:
            raise AlreadyClosedError()

    async def aclose(self) -> None:
        """
        Put the API client out of service, and close its transport if the API
        client created it.

        Every later request raises :class:`AlreadyClosedError`. Closing an already
        closed API client does nothing.
        """
        with self._close_lock:
            if self._is_closed:
                return

            self._is_closed = True

        if self._default_transport is not None:
            await self._default_transport.aclose()

    async def fetch_features(
        self, etag: str = "", *, options: PollingOptions
    ) -> FetchResult:
        """
        Fetch feature state, sending ``If-None-Match`` when an etag is known.

        :class:`AlreadyClosedError` is the only error this raises. Every other
        failure is logged and returned as an empty result, so a polling job can
        keep running against a server that is down.

        Emits ``FETCH_COMPLETED`` with how the fetch ended, before the caller
        applies the result.

        :param etag: the cached etag, or "" to fetch unconditionally.
        :param options: the polling settings
        :raises AlreadyClosedError: if the API client has been closed.
        """
        self._raise_if_closed()

        result, status = await self._fetch_features(etag, options)
        _emit_fetch_completed(self._events, status)
        return result

    async def _fetch_features(
        self, etag: str, options: PollingOptions
    ) -> Tuple[FetchResult, FetchStatus]:
        """The fetch itself, with how it ended."""
        config = self._config
        http_status_code: Optional[int] = None
        try:
            LOGGER.info("Getting feature flags.")

            headers = self._headers.polling(options)

            if etag:
                headers["If-None-Match"] = etag

            base_url = _normalized_url(config.url, FEATURES_URL)
            base_params = {}

            if options.project_name:
                base_params = {"project": options.project_name}

            resp = await _send_with_retries_async(
                self._transport,
                Request(
                    method="GET", url=base_url, headers=headers, params=base_params
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
                raise Exception(  # pylint: disable=broad-exception-raised
                    "Unleash Client feature fetch failed!"
                )

            fetched_etag = _header(resp, "etag")

            if resp.status == 304:
                return (
                    FetchResult(None, fetched_etag, not_modified=True),
                    FetchStatus.NOT_CHANGED,
                )

            raw_state = _text(resp)
            return (
                FetchResult(raw_state, fetched_etag),
                _fetched_status(raw_state),
            )
        except Exception as exc:
            LOGGER.exception(
                "Unleash Client feature fetch failed due to exception: %s", exc
            )

        return FetchResult(None, ""), _failure_status(http_status_code)

    async def register(self, payload: Dict[str, Any]) -> bool:
        """
        Register this client with the server.

        Returns True on 200 or 202, False on any other status and when the
        request fails: any exception from the transport is logged and reported
        as False.

        :param payload: as built by
                        :func:`UnleashClient._payloads._build_register_payload`.
        :raises AlreadyClosedError: if the API client has been closed.
        """
        self._raise_if_closed()

        config = self._config
        LOGGER.info("Registering unleash client with unleash @ %s", config.url)
        LOGGER.info("Registration request information: %s", payload)

        request = Request(
            method="POST",
            url=_normalized_url(config.url, REGISTER_URL),
            headers=self._headers.base(),
            body=json.dumps(payload).encode("utf-8"),
        )
        try:
            resp = await self._transport.execute(request)
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

    async def send_metrics(self, payload: Dict[str, Any]) -> bool:
        """
        Send one metrics bucket.

        Returns True only on 202. Every other status and any exception from the
        transport return False.

        :param payload: the metrics request body.
        :raises AlreadyClosedError: if the API client has been closed.
        :raises asyncio.CancelledError: if the send is cancelled.
        """
        self._raise_if_closed()

        config = self._config
        LOGGER.info("Sending messages to with unleash @ %s", config.url)
        LOGGER.info("unleash metrics information: %s", payload)

        request = Request(
            method="POST",
            url=_normalized_url(config.url, METRICS_URL),
            headers=self._headers.metrics(),
            body=json.dumps(payload).encode("utf-8"),
        )
        try:
            resp = await self._transport.execute(request)
        except asyncio.CancelledError:
            LOGGER.warning("Unleash Client metrics submission was cancelled.")
            raise
        except asyncio.TimeoutError:
            LOGGER.warning("Unleash Client metrics submission timed out.")
            return False
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
