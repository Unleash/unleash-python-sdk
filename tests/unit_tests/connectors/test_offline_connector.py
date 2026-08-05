import json

from apscheduler.schedulers.background import BackgroundScheduler
from yggdrasil_engine.engine import UnleashEngine

from tests.utilities.events import WAIT_TIMEOUT, EventRecorder
from tests.utilities.mocks.mock_features import MOCK_FEATURE_RESPONSE
from UnleashClient.connectors import OfflineConnector
from UnleashClient.constants import FEATURES_URL
from UnleashClient.events import EventDispatcher, UnleashEventType


def test_offline_connector_load_features(cache_empty):
    engine = UnleashEngine()
    scheduler = BackgroundScheduler()
    temp_cache = cache_empty

    temp_cache.set(FEATURES_URL, json.dumps(MOCK_FEATURE_RESPONSE))

    connector = OfflineConnector(
        engine=engine,
        cache=temp_cache,
        scheduler=scheduler,
    )

    connector.load_features()
    assert engine.is_enabled("testFlag", {})


def test_offline_connector_start_stop(cache_empty):
    engine = UnleashEngine()
    scheduler = BackgroundScheduler()
    scheduler.start()

    temp_cache = cache_empty
    temp_cache.set(FEATURES_URL, json.dumps(MOCK_FEATURE_RESPONSE))

    connector = OfflineConnector(
        engine=engine,
        cache=temp_cache,
        scheduler=scheduler,
        refresh_interval=1,
    )

    connector.start()
    assert connector.job is not None

    connector.stop()
    assert connector.job is None

    scheduler.shutdown()


def test_offline_connector_emits_ready_event(
    cache_empty, dispatcher: EventDispatcher, recorder: EventRecorder
):
    engine = UnleashEngine()
    scheduler = BackgroundScheduler()
    temp_cache = cache_empty
    temp_cache.set(FEATURES_URL, json.dumps(MOCK_FEATURE_RESPONSE))

    connector = OfflineConnector(
        engine=engine,
        cache=temp_cache,
        scheduler=scheduler,
        events=dispatcher,
    )

    connector.start()
    assert dispatcher.flush(timeout=WAIT_TIMEOUT)
    connector.stop()

    # start() emits once via load_features() and once directly; the dispatcher
    # collapses those into a single delivery.
    assert len(recorder.of_type(UnleashEventType.READY)) == 1


def test_offline_connector_without_a_dispatcher_does_not_emit(cache_empty):
    engine = UnleashEngine()
    scheduler = BackgroundScheduler()
    temp_cache = cache_empty
    temp_cache.set(FEATURES_URL, json.dumps(MOCK_FEATURE_RESPONSE))

    connector = OfflineConnector(
        engine=engine,
        cache=temp_cache,
        scheduler=scheduler,
    )

    connector.start()
    assert connector._events is None
    assert engine.is_enabled("testFlag", {})
    connector.stop()
