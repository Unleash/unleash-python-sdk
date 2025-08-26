from apscheduler.schedulers.background import BackgroundScheduler
from yggdrasil_engine.engine import UnleashEngine

from tests.utilities.mocks.mock_features import MOCK_FEATURE_RESPONSE
from UnleashClient.connectors import OfflineConnector
from UnleashClient.constants import FEATURES_URL


def test_offline_connector_load_features(cache_empty):
    engine = UnleashEngine()
    scheduler = BackgroundScheduler()
    temp_cache = cache_empty

    temp_cache.set(FEATURES_URL, MOCK_FEATURE_RESPONSE)

    connector = OfflineConnector(
        engine=engine,
        cache=temp_cache,
        scheduler=scheduler,
    )

    connector.load_features()

    assert engine.is_enabled("testFlag", {})


def test_offline_connector_load_features_empty_cache(cache_empty):
    engine = UnleashEngine()
    scheduler = BackgroundScheduler()
    temp_cache = cache_empty

    connector = OfflineConnector(
        engine=engine,
        cache=temp_cache,
        scheduler=scheduler,
    )

    connector.load_features()

    assert not engine.is_enabled("testFlag", {})


def test_offline_connector_start_stop(cache_empty):
    engine = UnleashEngine()
    scheduler = BackgroundScheduler()
    scheduler.start()

    temp_cache = cache_empty
    temp_cache.set(FEATURES_URL, MOCK_FEATURE_RESPONSE)

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


def test_offline_connector_ready_callback(cache_empty):
    engine = UnleashEngine()
    scheduler = BackgroundScheduler()
    temp_cache = cache_empty
    temp_cache.set(FEATURES_URL, MOCK_FEATURE_RESPONSE)

    callback_called = False

    def ready_callback():
        nonlocal callback_called
        callback_called = True

    connector = OfflineConnector(
        engine=engine,
        cache=temp_cache,
        scheduler=scheduler,
        ready_callback=ready_callback,
    )

    connector.load_features()

    assert callback_called
