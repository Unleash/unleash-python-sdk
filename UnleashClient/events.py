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
    """New feature state arrived."""

    NOT_CHANGED = "not_changed"
    """The server had nothing new since the last fetch."""

    UNAUTHORIZED = "unauthorized"
    """The server rejected the token: missing, unknown or the wrong type.
    Won't recover on its own."""

    RATE_LIMITED = "rate_limited"
    """The server is throttling this client. Back off."""

    UNAVAILABLE = "unavailable"
    """The server or the network is down: a server error after retries, a
    timeout or no response at all. Transient."""

    INVALID_RESPONSE = "invalid_response"
    """A response arrived that the client can't use, for example an empty
    body or an unexpected status. Something between the client and the
    server may be answering in its place."""


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
    new, or failed. It is sent as soon as the fetch ends, before the fetched
    state is applied.
    """

    status: FetchStatus
