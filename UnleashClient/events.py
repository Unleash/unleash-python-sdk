from dataclasses import dataclass
from enum import Enum
from json import loads
from typing import Optional
from uuid import UUID


class UnleashEventType(Enum):
    """
    Indicates what kind of event was triggered.
    """

    FEATURE_FLAG = "feature_flag"
    VARIANT = "variant"
    FETCHED = "fetched"
    READY = "ready"
    FETCH_COMPLETED = "fetch_completed"


class FetchStatus(Enum):
    """
    How a feature fetch ended.
    """

    CHANGED = "changed"
    NOT_CHANGED = "not_changed"
    FAILED = "failed"


@dataclass
class BaseEvent:
    """
    Base event type for all events in the Unleash client.
    """

    event_type: UnleashEventType
    event_id: UUID


@dataclass
class UnleashEvent(BaseEvent):
    """
    Dataclass capturing information from an Unleash feature flag or variant check.
    """

    context: dict
    enabled: bool
    feature_name: str
    variant: Optional[str] = ""


@dataclass
class UnleashReadyEvent(BaseEvent):
    """
    Event indicating that the Unleash client is ready.
    """

    pass


@dataclass
class UnleashFetchedEvent(BaseEvent):
    """
    Event indicating that the Unleash client has fetched feature flags.
    """

    raw_features: str

    @property
    def features(self) -> dict:
        if not hasattr(self, "_parsed_payload"):
            self._parsed_payload = loads(self.raw_features)["features"]
        return self._parsed_payload


@dataclass
class UnleashFetchCompletedEvent(BaseEvent):
    """
    Event emitted after every feature fetch, whether it brought new state, nothing
    new, or failed. ``http_status_code`` is None when no response arrived, for
    example on a timeout or a refused connection. It is sent as soon as the
    fetch ends, before the fetched state is applied.
    """

    status: FetchStatus
    http_status_code: Optional[int] = None
