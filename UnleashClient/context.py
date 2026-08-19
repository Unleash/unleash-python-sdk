"""Evaluation context enrichment, shared by the sync and async Unleash clients."""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from UnleashClient.config import UnleashConfig

BASE_CONTEXT_FIELDS = [
    "userId",
    "sessionId",
    "environment",
    "appName",
    "currentTime",
    "remoteAddress",
    "properties",
]


def _safe_value(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


class ContextEnricher:
    """
    Turns a caller-supplied context into the shape the engine expects.

    The config's static context is read on every call, so reassigning
    ``config.static_context`` (which ``UnleashClient.unleash_static_context``
    does) takes effect immediately.
    """

    def __init__(self, config: UnleashConfig) -> None:
        self._config: UnleashConfig = config

    def build(self, context: Optional[dict] = None) -> dict:
        new_context: Dict[str, Any] = self._config.static_context.copy()
        new_context.update(context or {})

        if "currentTime" not in new_context:
            new_context["currentTime"] = datetime.now(timezone.utc).isoformat()

        safe_properties = self._extract_properties(new_context)
        safe_properties = {k: _safe_value(v) for k, v in safe_properties.items()}
        safe_context: Dict[str, Any] = {
            k: _safe_value(v) for k, v in new_context.items() if k != "properties"
        }

        safe_context["properties"] = safe_properties

        return safe_context

    def _extract_properties(self, context: dict) -> dict:
        properties = context.get("properties", {})
        extracted_fields = {
            k: v for k, v in context.items() if k not in BASE_CONTEXT_FIELDS
        }
        extracted_fields.update(properties)
        return extracted_fields
