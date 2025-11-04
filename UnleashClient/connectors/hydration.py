from typing import Callable, Optional

from yggdrasil_engine.engine import UnleashEngine

from UnleashClient.cache import BaseCache
from UnleashClient.constants import FEATURES_URL
from UnleashClient.utils import LOGGER


def hydrate_engine(
    cache: BaseCache, engine: UnleashEngine, ready_callback: Optional[Callable] = None
):
    feature_provisioning = cache.get(FEATURES_URL)
    if not feature_provisioning:
        LOGGER.warning(
            "Unleash client does not have cached features. "
            "Please make sure client can communicate with Unleash server!"
        )
        return

    try:
        warnings = engine.take_state(feature_provisioning)
        if ready_callback:
            ready_callback()
        if warnings:
            LOGGER.warning(
                "Some features were not able to be parsed correctly, they may not evaluate as expected"
            )
            LOGGER.warning(warnings)
    except Exception as e:
        LOGGER.error(f"Error loading features: {e}")
        LOGGER.debug(f"Full feature response body from server: {feature_provisioning}")
