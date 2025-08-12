import uuid
from typing import Callable, Optional

from yggdrasil_engine.engine import UnleashEngine

from UnleashClient.api.delta import get_feature_deltas
from UnleashClient.cache import BaseCache
from UnleashClient.constants import ETAG
from UnleashClient.events import UnleashEventType, UnleashFetchedEvent
from UnleashClient.utils import LOGGER


def fetch_and_apply_delta(
    url: str,
    app_name: str,
    instance_id: str,
    headers: dict,
    custom_options: dict,
    cache: BaseCache,
    request_timeout: int,
    request_retries: int,
    engine: UnleashEngine,
    event_callback: Optional[Callable] = None,
    ready_callback: Optional[Callable] = None,
) -> None:
    """
    Fetch delta payload and apply to engine with engine.take_state(raw_json).
    Fires READY on first hydration (hydration event inside delta stream) and FETCHED on each successful delta.
    """
    (delta_payload, etag) = get_feature_deltas(
        url,
        app_name,
        instance_id,
        headers,
        custom_options,
        request_timeout,
        request_retries,
        cache.get(ETAG),
    )

    if etag:
        cache.set(ETAG, etag)

    if not delta_payload:
        LOGGER.debug("No delta returned from server, nothing to apply.")
        return

    try:
        engine.take_state(delta_payload)

        if event_callback:
            event = UnleashFetchedEvent(
                event_type=UnleashEventType.FETCHED,
                event_id=uuid.uuid4(),
                raw_features=delta_payload,
            )
            event_callback(event)

        # First hydration event as ready signal
        if ready_callback and '"type":"hydration"' in delta_payload:
            ready_callback()
    except Exception as exc:
        LOGGER.warning("Failed to apply delta: %s", exc)
