import json

from yggdrasil_engine.engine import UnleashEngine

from ..asynchronous.cache import AsyncBaseCache
from ..constants import ETAG, FEATURES_URL
from ..utils import LOGGER


async def load_features(
    cache: AsyncBaseCache,
    feature_toggles: str,
    etag: str,
    updated: bool = True,
) -> None:
    """
    Loads feature toggles into cache and engine asynchronously.

    :param cache: Cache instance
    :param feature_toggles: JSON string of feature toggles
    :param etag: ETag from response
    :param updated: Whether features were updated
    """
    if updated and feature_toggles:
        await cache.set(FEATURES_URL, feature_toggles)
        LOGGER.info("Feature toggles loaded successfully")

    if etag:
        await cache.set(ETAG, etag)


async def check_cache(cache: AsyncBaseCache, engine: UnleashEngine) -> bool:
    """
    Checks cache for feature toggles and loads them into engine asynchronously.

    :param cache: Cache instance
    :param engine: Engine instance
    :return: True if features loaded from cache, False otherwise
    """
    cached_features = await cache.get(FEATURES_URL)

    if cached_features:
        try:
            feature_obj = json.loads(cached_features)
            engine.take_state(feature_obj)
            LOGGER.info("Loaded features from cache")
            return True
        except Exception as exc:
            LOGGER.warning("Failed to load features from cache: %s", exc)

    return False
