from abc import ABC, abstractmethod
from typing import Optional

from UnleashClient._async_scheduler import _AsyncScheduler
from UnleashClient.async_transport import AsyncTransport
from UnleashClient.store import FeatureStore


class AsyncBaseConnector(ABC):
    def __init__(self, store: FeatureStore) -> None:
        """
        :param store: Applies feature state to the engine and the cache, and
                      emits the events that follow.
        """
        self._store = store

    @abstractmethod
    async def start(self) -> None:
        pass

    @abstractmethod
    async def stop(self) -> None:
        pass


class AsyncPollingConnector(AsyncBaseConnector):
    """
    Keeps feature state fresh by fetching it on a fixed interval. Starting loads
    the cached state and schedules the fetch, without waiting for it.

    Example::

        connector = AsyncPollingConnector(
            store=store,
            transport=transport,
            refresh_interval=15,
        )
        await connector.start()

        await connector.stop()
    """

    def __init__(
        self,
        store: FeatureStore,
        transport: AsyncTransport,
        refresh_interval: float = 15,
        refresh_jitter: Optional[float] = None,
    ) -> None:
        """
        :param store: Applies feature state to the engine and the cache.
        :param transport: Performs the fetch against the Unleash server.
        :param refresh_interval: Seconds between fetches.
        :param refresh_jitter: Maximum seconds to randomly offset each fetch by, or
                               None for no jitter.
        """
        super().__init__(store)
        self._transport: AsyncTransport = transport
        self._refresh_interval = refresh_interval
        self._refresh_jitter = refresh_jitter
        self._scheduler: _AsyncScheduler = _AsyncScheduler()

    async def _fetch_and_load(self) -> None:
        result = await self._transport.fetch_features(etag=self._store.cached_etag)

        self._store.apply_fetched(raw_state=result.raw_state, etag=result.etag)

    async def start(self) -> None:
        """
        Loads the cached feature state, then fetches every ``refresh_interval``
        seconds. The first fetch runs one interval after this returns.
        """
        self._store.load_from_cache()

        self._scheduler.every(
            interval_seconds=self._refresh_interval,
            jitter_seconds=self._refresh_jitter,
            fn=self._fetch_and_load,
        )
        self._scheduler.start()

    async def stop(self) -> None:
        """
        Stops fetching, and returns once a fetch in flight has been interrupted.
        Safe to call when :meth:`start` was never called.
        """
        await self._scheduler.shutdown()
