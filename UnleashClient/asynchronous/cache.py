import abc
import json
from pathlib import Path
from typing import Any, Optional

import aiofiles
import niquests as requests

from ..constants import FEATURES_URL, REQUEST_TIMEOUT
from ..vendor.fcache import FileCache as _FileCache


class AsyncBaseCache(abc.ABC):
    """
    Abstract base class for async caches used for UnleashClient.

    If implementing your own bootstrapping methods:

    - Add your custom bootstrap method.
    - You must set the `bootstrapped` attribute to True after configuration is set.
    """

    bootstrapped = False

    @abc.abstractmethod
    async def set(self, key: str, value: Any) -> None:
        pass

    @abc.abstractmethod
    async def mset(self, data: dict) -> None:
        pass

    @abc.abstractmethod
    async def get(self, key: str, default: Optional[Any] = None) -> Any:
        pass

    @abc.abstractmethod
    async def exists(self, key: str) -> bool:
        pass

    @abc.abstractmethod
    async def destroy(self) -> None:
        pass


class AsyncFileCache(AsyncBaseCache):
    """
    The async cache for AsyncUnleashClient. Uses a custom async-compatible file cache.

    You can boostrap the AsyncFileCache with initial configuration to improve resiliency on startup.  To do so:

    - Create a new AsyncFileCache instance.
    - Bootstrap the AsyncFileCache.
    - Pass your AsyncFileCache instance to AsyncUnleashClient at initialization along with `boostrap=true`.

    You can bootstrap from a dictionary, a json file, or from a URL.  In all cases, configuration should match the Unleash `/api/client/features <https://docs.getunleash.io/api/client/features>`_ endpoint.

    Example:

    .. code-block:: python

        from pathlib import Path
        from UnleashClient.asynchronous.cache import AsyncFileCache
        from UnleashClient.asynchronous import AsyncUnleashClient

        async def main():
            my_cache = AsyncFileCache("HAMSTER_API")
            await my_cache.bootstrap_from_file(Path("/path/to/boostrap.json"))
            unleash_client = AsyncUnleashClient(
                "https://my.unleash.server.com",
                "HAMSTER_API",
                cache=my_cache
            )

    :param name: Name of cache.
    :param directory: Location to create cache.  If empty, will use filecache default.
    """

    def __init__(
        self,
        name: str,
        directory: Optional[str] = None,
        request_timeout: int = REQUEST_TIMEOUT,
    ) -> None:
        self._cache = _FileCache(name, app_cache_dir=directory)
        self.request_timeout = request_timeout

    async def bootstrap_from_dict(self, initial_config: dict) -> None:
        """
        Loads initial Unleash configuration from a dictionary.

        Note: Pre-seeded configuration will only be used if UnleashClient is initialized with `bootstrap=true`.

        :param initial_config: Dictionary that contains initial configuration.
        """
        await self.set(FEATURES_URL, json.dumps(initial_config))
        self.bootstrapped = True

    async def bootstrap_from_file(self, initial_config_file: Path) -> None:
        """
        Loads initial Unleash configuration from a file asynchronously.

        Note: Pre-seeded configuration will only be used if UnleashClient is initialized with `bootstrap=true`.

        :param initial_configuration_file: Path to document containing initial configuration.  Must be JSON.
        """
        async with aiofiles.open(
            initial_config_file, "r", encoding="utf8"
        ) as bootstrap_file:
            content = await bootstrap_file.read()
            await self.set(FEATURES_URL, content)
            self.bootstrapped = True

    async def bootstrap_from_url(
        self,
        initial_config_url: str,
        headers: Optional[dict] = None,
        request_timeout: Optional[int] = None,
    ) -> None:
        """
        Loads initial Unleash configuration from a url asynchronously.

        Note: Pre-seeded configuration will only be used if UnleashClient is initialized with `bootstrap=true`.

        :param initial_configuration_url: Url that returns document containing initial configuration.  Must return JSON.
        :param headers: Headers to use when GETing the initial configuration URL.
        """
        timeout = request_timeout if request_timeout else self.request_timeout
        async with requests.AsyncSession() as session:
            response = await session.get(
                initial_config_url, headers=headers, timeout=timeout
            )
        await self.set(FEATURES_URL, response.text)
        self.bootstrapped = True

    async def set(self, key: str, value: Any) -> None:
        self._cache[key] = value
        self._cache.sync()

    async def mset(self, data: dict) -> None:
        self._cache.update(data)
        self._cache.sync()

    async def get(self, key: str, default: Optional[Any] = None) -> Any:
        return self._cache.get(key, default)

    async def exists(self, key: str) -> bool:
        return key in self._cache

    async def destroy(self) -> None:
        return self._cache.delete()
