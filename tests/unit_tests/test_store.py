import json
from typing import Any, Optional

import pytest
from yggdrasil_engine.engine import UnleashEngine

from tests.utilities.events import WAIT_TIMEOUT, EventRecorder
from tests.utilities.mocks.mock_features import (
    MOCK_FEATURE_DELTA_RESPONSE,
    MOCK_FEATURE_RESPONSE,
    MOCK_FEATURE_RESPONSE_PROJECT,
)
from tests.utilities.testing_constants import ETAG_VALUE
from UnleashClient.cache import BaseCache
from UnleashClient.constants import ETAG, FEATURES_URL
from UnleashClient.events import EventDispatcher, UnleashEventType
from UnleashClient.store import FeatureStore

FEATURES = json.dumps(MOCK_FEATURE_RESPONSE)
OTHER_FEATURES = json.dumps(MOCK_FEATURE_RESPONSE_PROJECT)
DELTA = json.dumps(MOCK_FEATURE_DELTA_RESPONSE)


class RoundTrippingCache(BaseCache):
    """
    Hands back something other than what was stored, so tests can tell whether
    the engine was fed the argument or the cache.
    """

    def __init__(self, on_read: str):
        self._on_read = on_read
        self.written: dict = {}

    def set(self, key: str, value: Any):
        self.written[key] = value

    def mset(self, data: dict):
        self.written.update(data)

    def get(self, key: str, default: Optional[Any] = None):
        if key == FEATURES_URL:
            return self._on_read
        return self.written.get(key, default)

    def exists(self, key: str):
        return key in self.written

    def destroy(self):
        self.written.clear()


class FailingDispatcher:
    """A dispatcher whose delivery is broken."""

    def emit_event(self, event):
        raise RuntimeError("dispatcher is broken")


def test_load_from_cache_applies_the_cached_state(cache_empty):
    engine = UnleashEngine()
    cache_empty.set(FEATURES_URL, FEATURES)

    FeatureStore(engine, cache_empty).load_from_cache()

    assert engine.is_enabled("testFlag", {}).is_enabled


def test_load_from_cache_emits_ready(cache_empty, dispatcher, recorder):
    cache_empty.set(FEATURES_URL, FEATURES)

    FeatureStore(UnleashEngine(), cache_empty, dispatcher).load_from_cache()

    assert recorder.wait_for(UnleashEventType.READY, count=1)
    dispatcher.close(timeout=WAIT_TIMEOUT)

    assert len(recorder.of_type(UnleashEventType.READY)) == 1


def test_load_from_cache_on_an_empty_cache_neither_raises_nor_emits(
    cache_empty, dispatcher: EventDispatcher, recorder: EventRecorder
):
    engine = UnleashEngine()

    FeatureStore(engine, cache_empty, dispatcher).load_from_cache()
    dispatcher.close(timeout=WAIT_TIMEOUT)

    assert engine.list_known_toggles() == []
    assert recorder.of_type(UnleashEventType.READY) == []


def test_load_from_cache_swallows_an_unparseable_body(
    cache_empty, dispatcher, recorder
):
    engine = UnleashEngine()
    cache_empty.set(FEATURES_URL, "not json")

    FeatureStore(engine, cache_empty, dispatcher).load_from_cache()
    dispatcher.close(timeout=WAIT_TIMEOUT)

    assert engine.list_known_toggles() == []
    assert recorder.of_type(UnleashEventType.READY) == []


def test_load_from_cache_without_a_dispatcher_still_applies(cache_empty):
    engine = UnleashEngine()
    cache_empty.set(FEATURES_URL, FEATURES)

    FeatureStore(engine, cache_empty).load_from_cache()

    assert engine.is_enabled("testFlag", {}).is_enabled


def test_apply_fetched_caches_the_payload_and_the_etag(cache_empty):
    engine = UnleashEngine()

    FeatureStore(engine, cache_empty).apply_fetched(FEATURES, ETAG_VALUE)

    assert cache_empty.get(FEATURES_URL) == FEATURES
    assert cache_empty.get(ETAG) == ETAG_VALUE
    assert engine.is_enabled("testFlag", {}).is_enabled


def test_apply_fetched_without_state_keeps_the_cached_provisioning(cache_empty):
    engine = UnleashEngine()
    cache_empty.set(FEATURES_URL, FEATURES)

    # What a 304 looks like coming out of the API layer.
    FeatureStore(engine, cache_empty).apply_fetched(None, ETAG_VALUE)

    assert cache_empty.get(FEATURES_URL) == FEATURES
    assert engine.is_enabled("testFlag", {}).is_enabled


def test_apply_fetched_without_state_emits_ready_but_not_fetched(
    cache_empty, dispatcher, recorder
):
    cache_empty.set(FEATURES_URL, FEATURES)

    FeatureStore(UnleashEngine(), cache_empty, dispatcher).apply_fetched(None)

    assert recorder.wait_for(UnleashEventType.READY, count=1)
    dispatcher.close(timeout=WAIT_TIMEOUT)

    assert len(recorder.of_type(UnleashEventType.READY)) == 1
    assert recorder.of_type(UnleashEventType.FETCHED) == []


def test_apply_fetched_with_a_falsy_etag_keeps_the_cached_one(cache_empty):
    cache_empty.set(ETAG, ETAG_VALUE)

    FeatureStore(UnleashEngine(), cache_empty).apply_fetched(FEATURES, "")

    assert cache_empty.get(ETAG) == ETAG_VALUE


def test_apply_fetched_emits_ready_before_fetched(cache_empty, dispatcher, recorder):
    FeatureStore(UnleashEngine(), cache_empty, dispatcher).apply_fetched(FEATURES)

    assert recorder.wait_for(UnleashEventType.READY, count=1)
    assert recorder.wait_for(UnleashEventType.FETCHED, count=1)
    dispatcher.close(timeout=WAIT_TIMEOUT)

    assert [event.event_type for event in recorder.events] == [
        UnleashEventType.READY,
        UnleashEventType.FETCHED,
    ]


def test_apply_fetched_carries_the_raw_response_on_the_event(
    cache_empty, dispatcher, recorder
):
    FeatureStore(UnleashEngine(), cache_empty, dispatcher).apply_fetched(FEATURES)

    assert recorder.wait_for(UnleashEventType.FETCHED, count=1)
    dispatcher.close(timeout=WAIT_TIMEOUT)

    fetched = recorder.of_type(UnleashEventType.FETCHED)[0]

    assert fetched.raw_features == FEATURES
    assert fetched.features[0]["name"] == "testFlag"


def test_apply_fetched_with_an_unparseable_payload_still_emits_fetched_then_ready(
    cache_empty, dispatcher, recorder
):
    engine = UnleashEngine()

    FeatureStore(engine, cache_empty, dispatcher).apply_fetched("not json")

    assert recorder.wait_for(UnleashEventType.FETCHED, count=1)
    assert recorder.wait_for(UnleashEventType.READY, count=1)
    dispatcher.close(timeout=WAIT_TIMEOUT)

    # The load swallowed the failure and emitted nothing, so the READY the user
    # sees is the one that follows FETCHED.
    assert engine.list_known_toggles() == []
    assert [event.event_type for event in recorder.events] == [
        UnleashEventType.FETCHED,
        UnleashEventType.READY,
    ]


def test_apply_fetched_emits_ready_once_across_polls(cache_empty, dispatcher, recorder):
    store = FeatureStore(UnleashEngine(), cache_empty, dispatcher)

    store.apply_fetched(FEATURES)
    store.apply_fetched(FEATURES)

    assert recorder.wait_for(UnleashEventType.READY, count=1)
    assert recorder.wait_for(UnleashEventType.FETCHED, count=2)
    dispatcher.close(timeout=WAIT_TIMEOUT)

    assert len(recorder.of_type(UnleashEventType.READY)) == 1
    assert len(recorder.of_type(UnleashEventType.FETCHED)) == 2


def test_apply_fetched_feeds_the_engine_from_the_cache():
    engine = UnleashEngine()
    cache = RoundTrippingCache(on_read=OTHER_FEATURES)

    FeatureStore(engine, cache).apply_fetched(FEATURES)

    assert cache.written[FEATURES_URL] == FEATURES
    assert engine.is_enabled("ivan-project", {}).is_enabled
    assert not engine.is_enabled("testFlag", {}).is_enabled


def test_apply_streamed_applies_the_payload_and_caches_the_engine_state(
    cache_empty, dispatcher, recorder
):
    engine = UnleashEngine()

    FeatureStore(engine, cache_empty, dispatcher).apply_streamed(
        FEATURES, emit_ready=True
    )

    assert recorder.wait_for(UnleashEventType.READY, count=1)
    dispatcher.close(timeout=WAIT_TIMEOUT)

    assert engine.is_enabled("testFlag", {}).is_enabled
    assert cache_empty.get(FEATURES_URL) == engine.get_state()
    assert len(recorder.of_type(UnleashEventType.READY)) == 1
    assert recorder.of_type(UnleashEventType.FETCHED) == []


def test_apply_streamed_caches_the_merged_state_not_the_delta(cache_empty):
    store = FeatureStore(UnleashEngine(), cache_empty)

    store.apply_streamed(FEATURES, emit_ready=True)
    store.apply_streamed(DELTA)

    assert cache_empty.get(FEATURES_URL) != DELTA

    # A cold engine reading that cache back sees the flags from both payloads.
    recovered = UnleashEngine()
    FeatureStore(recovered, cache_empty).load_from_cache()

    assert recovered.is_enabled("deltaFlag", {}).is_enabled
    assert recovered.is_enabled("testFlag", {}).is_enabled


def test_apply_streamed_does_not_emit_unless_asked(cache_empty, dispatcher, recorder):
    FeatureStore(UnleashEngine(), cache_empty, dispatcher).apply_streamed(FEATURES)
    dispatcher.close(timeout=WAIT_TIMEOUT)

    assert recorder.events == []


def test_apply_streamed_raises_on_a_bad_payload(cache_empty):
    store = FeatureStore(UnleashEngine(), cache_empty)

    with pytest.raises(Exception):
        store.apply_streamed("not json")

    assert cache_empty.get(FEATURES_URL) is None


def test_cached_etag_returns_the_cached_value(cache_empty):
    cache_empty.set(ETAG, ETAG_VALUE)

    assert FeatureStore(UnleashEngine(), cache_empty).cached_etag == ETAG_VALUE


def test_cached_etag_is_empty_when_the_cache_has_no_etag():
    cache = RoundTrippingCache(on_read=FEATURES)

    assert FeatureStore(UnleashEngine(), cache).cached_etag == ""


def test_a_failing_dispatcher_does_not_break_the_state_path(cache_empty):
    engine = UnleashEngine()

    FeatureStore(engine, cache_empty, FailingDispatcher()).apply_fetched(FEATURES)

    assert engine.is_enabled("testFlag", {}).is_enabled
