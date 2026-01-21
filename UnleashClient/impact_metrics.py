from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from yggdrasil_engine.engine import UnleashEngine


@dataclass
class MetricFlagContext:
    """Context for resolving feature flag values as metric labels."""

    flag_names: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)


class ImpactMetrics:
    """
    Provides methods to define and record metrics (counters, gauges, histograms)
    with optional feature flag context that gets resolved to labels.
    """

    def __init__(self, engine: UnleashEngine, app_name: str, environment: str):
        self._engine = engine
        self._app_name = app_name
        self._environment = environment

    def define_counter(self, name: str, help_text: str) -> None:
        self._engine.define_counter(name, help_text)

    def increment_counter(
        self,
        name: str,
        value: int = 1,
        flag_context: Optional[MetricFlagContext] = None,
    ) -> None:
        labels = self._resolve_labels(flag_context)
        self._engine.inc_counter(name, value, labels)

    def define_gauge(self, name: str, help_text: str) -> None:
        self._engine.define_gauge(name, help_text)

    def update_gauge(
        self,
        name: str,
        value: int,
        flag_context: Optional[MetricFlagContext] = None,
    ) -> None:
        labels = self._resolve_labels(flag_context)
        self._engine.set_gauge(name, value, labels)

    def define_histogram(
        self, name: str, help_text: str, buckets: Optional[List[float]] = None
    ) -> None:
        self._engine.define_histogram(name, help_text, buckets)

    def observe_histogram(
        self,
        name: str,
        value: float,
        flag_context: Optional[MetricFlagContext] = None,
    ) -> None:
        labels = self._resolve_labels(flag_context)
        self._engine.observe_histogram(name, value, labels)

    def _resolve_labels(
        self, flag_context: Optional[MetricFlagContext]
    ) -> Optional[Dict[str, str]]:
        if flag_context is None:
            return None

        labels: Dict[str, str] = {
            "appName": self._app_name,
            "environment": self._environment,
        }

        for flag_name in flag_context.flag_names:
            variant = self._engine.get_variant(flag_name, flag_context.context)
            if variant and variant.enabled:
                labels[flag_name] = variant.name
            elif variant and variant.feature_enabled:
                labels[flag_name] = "enabled"
            else:
                labels[flag_name] = "disabled"

        return labels
