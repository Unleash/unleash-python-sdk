from typing import Optional

from yggdrasil_engine.engine import UnleashEngine

from ...api.asynchronous import get_feature_toggles
from ...asynchronous.cache import AsyncBaseCache
from ...asynchronous.loader import load_features
from ...constants import ETAG
from ...utils import LOGGER


async def fetch_and_load_features(
    url: str,
    app_name: str,
    instance_id: str,
    headers: dict,
    custom_options: dict,
    request_timeout: int,
    request_retries: int,
    cache: AsyncBaseCache,
    engine: UnleashEngine,
    project: Optional[str] = None,
) -> None:
    """
    Fetches feature toggles from Unleash server and loads them into cache and engine asynchronously.

    :param url: Unleash server URL
    :param app_name: Application name
    :param instance_id: Instance ID
    :param headers: Request headers
    :param custom_options: Custom request options
    :param request_timeout: Request timeout
    :param request_retries: Number of retries
    :param cache: Cache instance
    :param engine: Engine instance
    :param project: Project name
    """
    try:
        cached_etag = await cache.get(ETAG, "")

        feature_toggles, etag = await get_feature_toggles(
            url=url,
            app_name=app_name,
            instance_id=instance_id,
            headers=headers,
            custom_options=custom_options,
            request_timeout=request_timeout,
            request_retries=request_retries,
            project=project,
            cached_etag=cached_etag,
        )

        if feature_toggles:
            # Features were updated
            engine.take_state(feature_toggles)
            await load_features(cache, feature_toggles, etag, updated=True)
        elif etag:
            # Not modified (304), update etag only
            await load_features(cache, "", etag, updated=False)

    except Exception as exc:
        LOGGER.exception("Failed to fetch and load features: %s", exc)
