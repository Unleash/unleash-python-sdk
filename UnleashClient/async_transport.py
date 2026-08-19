"""Asynchronous HTTP transport, for the async Unleash client."""

import asyncio
import json
from typing import Any, Dict, Optional

from multidict import CIMultiDict

from UnleashClient.config import UnleashConfig
from UnleashClient.constants import FEATURES_URL, METRICS_URL, REGISTER_URL
from UnleashClient.headers import HeaderFactory
from UnleashClient.transport import FetchResult, normalized_url
from UnleashClient.utils import LOGGER

try:
    import aiohttp
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "AsyncUnleashClient requires aiohttp, which is not installed. "
        "Install it with: pip install UnleashClient[async]"
    ) from exc


# The statuses urllib3's Retry is given in Transport.fetch_features.
RETRY_STATUSES = frozenset({500, 502, 504})

# What a retry is worth attempting for. Deliberately narrower than
# aiohttp.ClientError: InvalidUrlClientError and NonHttpUrlClientError also
# subclass it, and a malformed url is not going to fix itself on attempt two.
RETRYABLE_ERRORS = (aiohttp.ClientConnectionError, asyncio.TimeoutError)

# The two aiohttp raises for a url it cannot use at all -- the analogue of the
# requests quartet Transport.register re-raises. Both subclass ClientError, so
# they have to be caught ahead of it. aiohttp has no InvalidHeader: an illegal
# header surfaces as a bare ValueError, which is not a ClientError and so
# escapes register() without a clause of its own.
FATAL_URL_ERRORS = (aiohttp.InvalidURL, aiohttp.NonHttpUrlClientError)


async def _log_resp_info(resp: "aiohttp.ClientResponse") -> None:
    LOGGER.debug("HTTP status code: %s", resp.status)
    LOGGER.debug("HTTP headers: %s", resp.headers)
    LOGGER.debug("HTTP content: %s", await resp.text())


class AsyncTransport:
    """
    The asyncio twin of :class:`UnleashClient.transport.Transport`, and the
    async half of the one colored leaf in the SDK.

    It matches ``Transport`` method for method and returns the same
    :class:`~UnleashClient.transport.FetchResult`, so everything downstream of a
    request -- :class:`~UnleashClient.store.FeatureStore`, the payload builders,
    the :class:`~UnleashClient.headers.HeaderFactory` -- is shared rather than
    duplicated. ``aclose()`` is the one method with no sync counterpart.

    Like ``Transport``, it reads the config and asks the header factory on every
    request rather than capturing either, because the ``unleash_*`` properties
    that back them are public and writable.

    Two things differ from the sync class, both forced by aiohttp:

    - ``custom_options`` are ``requests`` keyword arguments and do not transfer.
      ``verify``, ``cert`` and ``proxies`` all raise ``TypeError`` here; the
      aiohttp spellings are ``ssl`` and ``proxy``.
    - One pooled ``ClientSession`` is held rather than a session per request,
      and it is built on first use, not in ``__init__`` -- aiohttp resolves the
      running loop eagerly, and ``AsyncUnleashClient.__init__`` is synchronous.
      That binds a transport to whichever loop first used it, and makes
      ``aclose()`` an obligation on the caller.
    """

    def __init__(self, config: UnleashConfig, headers: HeaderFactory) -> None:
        """
        :param config: read for the url, timeouts, retries, project and custom
                       options.
        :param headers: builds the header set each request needs.
        """
        self._config: UnleashConfig = config
        self._headers: HeaderFactory = headers
        self._session: Optional["aiohttp.ClientSession"] = None

    async def _get_session(self) -> "aiohttp.ClientSession":
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def _timeout(self) -> "aiohttp.ClientTimeout":
        # sock_connect/sock_read rather than total, because requests' scalar
        # timeout bounds each socket operation and not the whole request. Under
        # `total` a large feature payload over a slow but healthy link would
        # start failing at a request_timeout that works today.
        seconds = self._config.request_timeout
        return aiohttp.ClientTimeout(
            total=None, sock_connect=seconds, sock_read=seconds
        )

    async def aclose(self) -> None:
        """
        Close the pooled session, if one was ever opened.

        Nothing calls this yet -- ``AsyncUnleashClient.destroy()`` is still
        unimplemented, and closing is its job when it lands. Until then every
        caller that makes a request owns the close, or aiohttp logs an unclosed
        session on garbage collection.
        """
        session, self._session = self._session, None
        if session is not None and not session.closed:
            await session.close()

    # pylint: disable=broad-except
    # TODO: narrow the except clause to the same set of errors the sync transport
    # so TransportError becomes part of the API of transports.
    async def fetch_features(self, etag: str = "") -> FetchResult:
        """
        Fetch feature state, sending ``If-None-Match`` when an etag is known.

        Never raises. Any failure -- an unexpected status, a connection error, a
        bad key in ``custom_options`` -- is logged and returned as an empty
        result, so a polling job can keep running against a server that is down.

        :param etag: the cached etag, or "" to fetch unconditionally.
        """
        config = self._config
        try:
            LOGGER.info("Getting feature flag.")

            # A CIMultiDict rather than a dict: the uppercase pair below
            # collides with the lowercase one HeaderFactory.base() already
            # carries, and aiohttp would put *both* spellings on the wire where
            # requests folds them into one. Updating a CIMultiDict replaces,
            # which is the behaviour the sync transport has always had.
            headers = CIMultiDict(self._headers.polling())

            # The features endpoint has always been sent an uppercase copy of
            # the two identification headers. It stays here rather than in
            # polling() because it is a quirk of this one endpoint.
            headers.update(
                {
                    "UNLEASH-APPNAME": config.app_name,
                    "UNLEASH-INSTANCEID": config.instance_id,
                }
            )

            if etag:
                headers["If-None-Match"] = etag

            base_url = normalized_url(config.url, FEATURES_URL)
            base_params = {}

            if config.project_name:
                base_params = {"project": config.project_name}

            session = await self._get_session()
            # aiohttp has no equivalent of the HTTPAdapter/Retry the sync
            # transport mounts, so the loop is here. urllib3's Retry defaults to
            # backoff_factor=0, so neither path sleeps between attempts.
            attempts = 1 + max(config.request_retries, 0)

            for attempt in range(attempts):
                last_attempt = attempt == attempts - 1
                try:
                    async with session.get(
                        base_url,
                        headers=headers,
                        params=base_params,
                        timeout=self._timeout(),
                        **config.custom_options,
                    ) as resp:
                        if resp.status in RETRY_STATUSES and not last_attempt:
                            continue

                        if resp.status not in [200, 304]:
                            await _log_resp_info(resp)
                            LOGGER.warning(
                                "Unleash Client feature fetch failed due to unexpected HTTP status code: %s",
                                resp.status,
                            )
                            raise Exception(  # pylint: disable=broad-exception-raised
                                "Unleash Client feature fetch failed!"
                            )

                        fetched_etag = resp.headers.get("etag", "")

                        if resp.status == 304:
                            return FetchResult(None, fetched_etag, not_modified=True)

                        return FetchResult(await resp.text(), fetched_etag)
                except RETRYABLE_ERRORS:
                    if last_attempt:
                        raise
        except Exception as exc:
            LOGGER.exception(
                "Unleash Client feature fetch failed due to exception: %s", exc
            )

        return FetchResult(None, "")

    async def register(self, payload: Dict[str, Any]) -> bool:
        """
        Register this client with the server.

        Returns True on 200 or 202, False on any other status and on a general
        ``ClientError``. Re-raises the two errors aiohttp uses for a url it
        cannot make a request against at all, which is what makes
        ``initialize_client()`` fail loudly on a malformed URL instead of
        starting a client that can never reach the server.

        :param payload: as built by
                        :func:`UnleashClient.payloads.build_register_payload`.
        """
        config = self._config
        try:
            LOGGER.info("Registering unleash client with unleash @ %s", config.url)
            LOGGER.info("Registration request information: %s", payload)

            session = await self._get_session()
            # No retry loop, matching the sync register: only fetch_features
            # mounts the retry adapter.
            async with session.post(
                normalized_url(config.url, REGISTER_URL),
                data=json.dumps(payload),
                headers=self._headers.base(),
                timeout=self._timeout(),
                **config.custom_options,
            ) as resp:
                if resp.status not in {200, 202}:
                    await _log_resp_info(resp)
                    LOGGER.warning(
                        "Unleash Client registration failed due to unexpected HTTP status code: %s",
                        resp.status,
                    )
                    return False

                LOGGER.info("Unleash Client successfully registered!")

                return True
        # Ahead of the ClientError clause below: both subclass it, and Python
        # matches the first clause that fits.
        except FATAL_URL_ERRORS as exc:
            LOGGER.exception(
                "Unleash Client registration failed fatally due to exception: %s", exc
            )
            raise exc
        except aiohttp.ClientError as exc:
            LOGGER.exception(
                "Unleash Client registration failed due to exception: %s", exc
            )

        return False

    async def send_metrics(self, payload: Dict[str, Any]) -> bool:
        """
        Send one metrics bucket.

        Returns True only on 202; every other status is a failure, which is what
        the caller's impact-metrics restore path keys off. Catches only
        ``ClientError``, so a bad key in ``custom_options`` still surfaces as a
        ``TypeError`` to the caller rather than being reported as a failed send.

        :param payload: the metrics request body.
        """
        config = self._config
        try:
            LOGGER.info("Sending messages to with unleash @ %s", config.url)
            LOGGER.info("unleash metrics information: %s", payload)

            session = await self._get_session()
            async with session.post(
                normalized_url(config.url, METRICS_URL),
                data=json.dumps(payload),
                headers=self._headers.metrics(),
                timeout=self._timeout(),
                **config.custom_options,
            ) as resp:
                if resp.status != 202:
                    await _log_resp_info(resp)
                    LOGGER.warning(
                        "Unleash Client metrics submission due to unexpected HTTP status code: %s",
                        resp.status,
                    )
                    return False

                LOGGER.info("Unleash Client metrics successfully sent!")

                return True
        except aiohttp.ClientError as exc:
            LOGGER.warning(
                "Unleash Client metrics submission failed due to exception: %s", exc
            )

        return False
