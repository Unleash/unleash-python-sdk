import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any, Callable, Dict, Optional

from UnleashClient.events import (
    BaseEvent,
    UnleashEvent,
    UnleashEventType,
    UnleashReadyEvent,
)

try:
    from typing import Literal, TypedDict
except ImportError:
    from typing_extensions import Literal, TypedDict  # type: ignore

from UnleashClient.constants import DISABLED_VARIATION
from UnleashClient.utils import LOGGER

_BASE_CONTEXT_FIELDS = [
    "userId",
    "sessionId",
    "environment",
    "appName",
    "currentTime",
    "remoteAddress",
    "properties",
]


class RunState(IntEnum):
    UNINITIALIZED = 0
    INITIALIZED = 1
    SHUTDOWN = 2


class ExperimentalMode(TypedDict, total=False):
    type: Literal["streaming", "polling"]


def build_ready_callback(
    event_callback: Optional[Callable[[BaseEvent], None]] = None,
) -> Optional[Callable]:
    """
    Builds a callback function that can be used to notify when the Unleash client is ready.
    """

    if not event_callback:
        return None

    already_fired = False

    def ready_callback() -> None:
        """
        Callback function to notify that the Unleash client is ready.
        This will only call the event_callback once.
        """
        nonlocal already_fired
        if already_fired:
            return
        if event_callback:
            event = UnleashReadyEvent(
                event_type=UnleashEventType.READY,
                event_id=uuid.uuid4(),
            )
            already_fired = True
            event_callback(event)

    return ready_callback


class Evaluator:
    def __init__(
        self,
        engine,
        cache,
        static_context: Dict[str, Any],
        verbose_log_level: int,
        event_callback: Optional[Callable[[BaseEvent], None]],
    ) -> None:
        self.engine = engine
        self.cache = cache
        self.hydrated = self.cache.bootstrapped
        self.unleash_static_context = static_context
        self.unleash_event_callback = event_callback
        self.unleash_verbose_log_level = verbose_log_level

    @staticmethod
    def _get_fallback_value(
        fallback_function: Callable, feature_name: str, context: dict
    ) -> bool:
        if fallback_function:
            fallback_value = fallback_function(feature_name, context)
        else:
            fallback_value = False

        return fallback_value

    def mark_hydrated(self) -> None:
        self.hydrated = True

    # pylint: disable=broad-except
    def is_enabled(
        self,
        feature_name: str,
        context: Optional[dict] = None,
        fallback_function: Callable = None,
    ) -> bool:
        context = self._safe_context(context)
        feature_enabled = self.engine.is_enabled(feature_name, context)

        if feature_enabled is None:
            feature_enabled = self._get_fallback_value(
                fallback_function, feature_name, context
            )

        self.engine.count_toggle(feature_name, feature_enabled)
        try:
            if (
                self.unleash_event_callback
                and self.engine.should_emit_impression_event(feature_name)
            ):
                event = UnleashEvent(
                    event_type=UnleashEventType.FEATURE_FLAG,
                    event_id=uuid.uuid4(),
                    context=context,
                    enabled=feature_enabled,
                    feature_name=feature_name,
                )

                self.unleash_event_callback(event)
        except Exception as excep:
            LOGGER.log(
                self.unleash_verbose_log_level,
                "Error in event callback: %s",
                excep,
            )

        return feature_enabled

    # pylint: disable=broad-except
    def get_variant(self, feature_name: str, context: Optional[dict] = None) -> dict:
        context = self._safe_context(context)
        variant = self._resolve_variant(feature_name, context)

        if not variant:
            if not self.hydrated:
                LOGGER.log(
                    self.unleash_verbose_log_level,
                    "Attempted to get feature flag/variation %s, but client wasn't initialized!",
                    feature_name,
                )
            variant = DISABLED_VARIATION

        self.engine.count_variant(feature_name, variant["name"])
        self.engine.count_toggle(feature_name, variant["feature_enabled"])

        if self.unleash_event_callback and self.engine.should_emit_impression_event(
            feature_name
        ):
            try:
                event = UnleashEvent(
                    event_type=UnleashEventType.VARIANT,
                    event_id=uuid.uuid4(),
                    context=context,
                    enabled=bool(variant["enabled"]),
                    feature_name=feature_name,
                    variant=str(variant["name"]),
                )

                self.unleash_event_callback(event)
            except Exception as excep:
                LOGGER.log(
                    self.unleash_verbose_log_level,
                    "Error in event callback: %s",
                    excep,
                )

        return variant

    def feature_definitions(self) -> dict:
        toggles = self.engine.list_known_toggles()
        return {
            toggle.name: {"type": toggle.type, "project": toggle.project}
            for toggle in toggles
        }

    def _safe_context(self, context) -> dict:
        new_context: Dict[str, Any] = self.unleash_static_context.copy()
        new_context.update(context or {})

        if "currentTime" not in new_context:
            new_context["currentTime"] = datetime.now(timezone.utc).isoformat()

        safe_properties = self._extract_properties(new_context)
        safe_properties = {
            k: self._safe_context_value(v) for k, v in safe_properties.items()
        }
        safe_context = {
            k: self._safe_context_value(v)
            for k, v in new_context.items()
            if k != "properties"
        }

        safe_context["properties"] = safe_properties

        return safe_context

    def _extract_properties(self, context: dict) -> dict:
        properties = context.get("properties", {})
        extracted_fields = {
            k: v for k, v in context.items() if k not in _BASE_CONTEXT_FIELDS
        }
        extracted_fields.update(properties)
        return extracted_fields

    def _safe_context_value(self, value):
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, (int, float)):
            return str(value)
        return str(value)

    def _resolve_variant(self, feature_name: str, context: dict) -> dict:
        """
        Resolves a feature variant.
        """
        variant = self.engine.get_variant(feature_name, context)
        if variant:
            return {k: v for k, v in asdict(variant).items() if v is not None}
        return None
