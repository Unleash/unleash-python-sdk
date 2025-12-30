from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from threading import RLock
from typing import Any, Dict, List, Optional, Protocol


class MetricType(str, Enum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


MetricLabels = Dict[str, str]


@dataclass
class MetricOptions:
    name: str
    help: str
    label_names: List[str] = field(default_factory=list)


@dataclass
class NumericMetricSample:
    labels: MetricLabels
    value: int

    def to_dict(self) -> Dict[str, Any]:
        return {"labels": self.labels, "value": self.value}


@dataclass
class CollectedMetric:
    name: str
    help: str
    type: MetricType
    samples: List[NumericMetricSample]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "help": self.help,
            "type": self.type.value,
            "samples": [s.to_dict() for s in self.samples],
        }


def _get_label_key(labels: Optional[MetricLabels]) -> str:
    if not labels:
        return ""
    return ",".join(f"{k}={v}" for k, v in sorted(labels.items()))


def _parse_label_key(key: str) -> MetricLabels:
    if not key:
        return {}
    labels: MetricLabels = {}
    for pair in key.split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            labels[k] = v
    return labels


class Counter(Protocol):
    def inc(self, value: int = 1, labels: Optional[MetricLabels] = None) -> None: ...


class CounterImpl:
    def __init__(self, opts: MetricOptions) -> None:
        self._opts = opts
        self._values: Dict[str, int] = {}
        self._lock = RLock()

    def inc(self, value: int = 1, labels: Optional[MetricLabels] = None) -> None:
        key = _get_label_key(labels)
        with self._lock:
            current = self._values.get(key, 0)
            self._values[key] = current + value

    def collect(self) -> CollectedMetric:
        samples: List[NumericMetricSample] = []

        with self._lock:
            for key in list(self._values.keys()):
                value = self._values.pop(key)
                samples.append(
                    NumericMetricSample(labels=_parse_label_key(key), value=value)
                )

        if not samples:
            samples.append(NumericMetricSample(labels={}, value=0))

        return CollectedMetric(
            name=self._opts.name,
            help=self._opts.help,
            type=MetricType.COUNTER,
            samples=samples,
        )
