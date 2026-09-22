"""Flag evaluation, shared by the sync and async Unleash clients."""

import uuid
from dataclasses import asdict
from typing import Any, Callable, Dict, NamedTuple, Optional

from yggdrasil_engine.engine import UnleashEngine

from UnleashClient.config import UnleashConfig
from UnleashClient.context import ContextEnricher
from UnleashClient.events import (
    EventDispatcher,
    UnleashEvent,
    UnleashEventType,
)
from UnleashClient.utils import LOGGER


class _VariantResult(NamedTuple):
    """The variant a lookup resolved to, and whether the engine knew the toggle."""

    variant: Dict[str, Any]
    is_found: bool


class _Evaluator:
    """Answers flag questions and emits the impression events they call for."""

    def __init__(
        self,
        engine: UnleashEngine,
        enricher: ContextEnricher,
        config: UnleashConfig,
        events: Optional[EventDispatcher] = None,
    ) -> None:
        """
        :param engine: Feature evaluation engine instance (UnleashEngine).
        :param enricher: Builds the context the engine is asked with.
        :param config: The configuration the client was built with.
        :param events: Optional dispatcher that delivers events to the user's callback.
        """
        self._engine: UnleashEngine = engine
        self._enricher: ContextEnricher = enricher
        self._config: UnleashConfig = config
        self._events: Optional[EventDispatcher] = events

    # pylint: disable=broad-except
    def is_enabled(
        self,
        feature_name: str,
        context: Optional[dict] = None,
        fallback_function: Callable = None,
    ) -> bool:
        """Resolves a feature toggle."""
        context = self._enricher.build(context)
        result = self._engine.is_enabled(
            feature_name, context, fallback_function=fallback_function
        )

        try:
            if self._events and result.requires_impression_event_emission:
                self._events.emit_event(
                    UnleashEvent(
                        event_type=UnleashEventType.FEATURE_FLAG,
                        event_id=uuid.uuid4(),
                        context=context,
                        enabled=result.is_enabled,
                        feature_name=feature_name,
                    )
                )
        except Exception as excep:
            LOGGER.log(
                self._config.verbose_log_level,
                "Error emitting impression event: %s",
                excep,
            )

        return result.is_enabled

    # pylint: disable=broad-except
    def get_variant(
        self, feature_name: str, context: Optional[dict] = None
    ) -> _VariantResult:
        """Resolves a feature toggle's variant."""
        context = self._enricher.build(context)
        result = self._engine.get_variant(feature_name, context)

        try:
            if self._events and result.requires_impression_event_emission:
                self._events.emit_event(
                    UnleashEvent(
                        event_type=UnleashEventType.VARIANT,
                        event_id=uuid.uuid4(),
                        context=context,
                        enabled=bool(result.variant.enabled),
                        feature_name=feature_name,
                        variant=str(result.variant.name),
                    )
                )
        except Exception as excep:
            LOGGER.log(
                self._config.verbose_log_level,
                "Error emitting impression event: %s",
                excep,
            )

        variant = {k: v for k, v in asdict(result.variant).items() if v is not None}
        return _VariantResult(variant=variant, is_found=result.is_found)

    def feature_definitions(self) -> dict:
        """Every feature definition the engine currently holds, keyed by name."""
        toggles = self._engine.list_known_toggles()
        return {
            toggle.name: {"type": toggle.type, "project": toggle.project}
            for toggle in toggles
        }
