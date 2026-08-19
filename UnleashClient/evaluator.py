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


class VariantResult(NamedTuple):
    """
    The outcome of one variant lookup.

    ``variant`` is the dict the clients return to their callers; ``is_found`` is
    the engine's answer to whether it knew the toggle at all.  The second field
    exists because ``UnleashClient.get_variant`` logs on a miss, but only when
    the client itself is bootstrapped or initialized -- run state the evaluator
    does not have.
    """

    variant: Dict[str, Any]
    is_found: bool


class Evaluator:
    """
    Answers flag questions: enriches the context, asks the engine, and emits the
    impression event the engine asks for.

    This is an uncolored object.  Evaluation is an in-process FFI call into
    Yggdrasil, so both clients share this class and both keep ``is_enabled`` and
    ``get_variant`` synchronous.

    The config is read on every call rather than captured, because
    ``unleash_verbose_log_level`` is public and writable.

    Registering custom strategies is not handled here: the clients do that
    against the engine directly, at initialization.
    """

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
        :param config: Read for the verbose log level.
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
        """
        Resolves a feature toggle.

        The engine never raises and never needs the client to have been
        initialized: an unknown toggle, a failed evaluation and a fallback that
        raises all come back as disabled.
        """
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
    ) -> VariantResult:
        """
        Resolves a feature toggle's variant.

        Returns the variant with its None fields dropped, alongside whether the
        engine knew the toggle.  Callers that want to report a miss decide that
        for themselves; nothing is logged here.
        """
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

        # This can probably become a to_dict method of the Variant type.
        variant = {k: v for k, v in asdict(result.variant).items() if v is not None}
        return VariantResult(variant=variant, is_found=result.is_found)

    def feature_definitions(self) -> dict:
        """
        Every feature definition the engine currently holds, keyed by name.

        The state may have come from the server, from a bootstrap or from the
        cache; the engine does not distinguish.
        """
        toggles = self._engine.list_known_toggles()
        return {
            toggle.name: {"type": toggle.type, "project": toggle.project}
            for toggle in toggles
        }
