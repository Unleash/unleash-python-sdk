import responses
from yggdrasil_engine.engine import UnleashEngine

from tests.utilities.events import WAIT_TIMEOUT, EventRecorder
from tests.utilities.mocks.mock_features import (
    MOCK_FEATURE_RESPONSE,
    MOCK_FEATURE_RESPONSE_PROJECT,
)
from tests.utilities.testing_constants import (
    APP_NAME,
    CUSTOM_HEADERS,
    CUSTOM_OPTIONS,
    ETAG_VALUE,
    INSTANCE_ID,
    PROJECT_NAME,
    PROJECT_URL,
    REQUEST_RETRIES,
    REQUEST_TIMEOUT,
    URL,
)
from UnleashClient.connectors import PollingConnector
from UnleashClient.constants import ETAG, FEATURES_URL
from UnleashClient.events import EventDispatcher, UnleashEventType
from UnleashClient.scheduler import Scheduler
from UnleashClient.store import FeatureStore

FULL_FEATURE_URL = URL + FEATURES_URL


@responses.activate
def test_polling_connector_fetch_and_load(cache_empty):
    engine = UnleashEngine()
    scheduler = Scheduler()
    responses.add(
        responses.GET,
        FULL_FEATURE_URL,
        json=MOCK_FEATURE_RESPONSE,
        status=200,
        headers={"etag": ETAG_VALUE},
    )
    temp_cache = cache_empty

    connector = PollingConnector(
        store=FeatureStore(engine=engine, cache=temp_cache),
        scheduler=scheduler,
        url=URL,
        app_name=APP_NAME,
        instance_id=INSTANCE_ID,
        headers=CUSTOM_HEADERS,
        custom_options=CUSTOM_OPTIONS,
        request_timeout=REQUEST_TIMEOUT,
        request_retries=REQUEST_RETRIES,
    )

    connector._fetch_and_load()

    assert engine.is_enabled("testFlag", {}).is_enabled
    assert temp_cache.get(ETAG) == ETAG_VALUE


@responses.activate
def test_polling_connector_fetch_and_load_project(cache_empty):
    engine = UnleashEngine()
    scheduler = Scheduler()
    responses.add(
        responses.GET, PROJECT_URL, json=MOCK_FEATURE_RESPONSE_PROJECT, status=200
    )
    temp_cache = cache_empty

    connector = PollingConnector(
        store=FeatureStore(engine=engine, cache=temp_cache),
        scheduler=scheduler,
        url=URL,
        app_name=APP_NAME,
        instance_id=INSTANCE_ID,
        headers=CUSTOM_HEADERS,
        custom_options=CUSTOM_OPTIONS,
        request_timeout=REQUEST_TIMEOUT,
        request_retries=REQUEST_RETRIES,
        project=PROJECT_NAME,
    )

    connector._fetch_and_load()

    assert engine.is_enabled("ivan-project", {}).is_enabled


@responses.activate
def test_polling_connector_fetch_and_load_failure(cache_empty):
    engine = UnleashEngine()
    scheduler = Scheduler()
    responses.add(
        responses.GET, FULL_FEATURE_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )
    temp_cache = cache_empty

    connector = PollingConnector(
        store=FeatureStore(engine=engine, cache=temp_cache),
        scheduler=scheduler,
        url=URL,
        app_name=APP_NAME,
        instance_id=INSTANCE_ID,
        headers=CUSTOM_HEADERS,
        custom_options=CUSTOM_OPTIONS,
        request_timeout=REQUEST_TIMEOUT,
        request_retries=REQUEST_RETRIES,
    )

    connector._fetch_and_load()

    responses.reset()
    responses.add(responses.GET, FULL_FEATURE_URL, json={}, status=500)

    connector._fetch_and_load()

    assert engine.is_enabled("testFlag", {}).is_enabled


@responses.activate
def test_polling_connector_emits_fetched_and_ready(
    cache_empty, dispatcher: EventDispatcher, recorder: EventRecorder
):
    engine = UnleashEngine()
    scheduler = Scheduler()
    responses.add(
        responses.GET,
        FULL_FEATURE_URL,
        json=MOCK_FEATURE_RESPONSE,
        status=200,
        headers={"etag": ETAG_VALUE},
    )

    connector = PollingConnector(
        store=FeatureStore(engine=engine, cache=cache_empty, events=dispatcher),
        scheduler=scheduler,
        url=URL,
        app_name=APP_NAME,
        instance_id=INSTANCE_ID,
        headers=CUSTOM_HEADERS,
        custom_options=CUSTOM_OPTIONS,
        request_timeout=REQUEST_TIMEOUT,
        request_retries=REQUEST_RETRIES,
        # Huge refresh interval to avoid any polling during the test. That
        # way we avoid having to call _fetch_and_load() directly and can test the start/stop behavior.
        refresh_interval=10,
    )

    connector.start()
    connector.stop()  # Immediately stop, so _get_and_load() is called only once and we can assert the events emitted.

    assert recorder.wait_for(UnleashEventType.READY, count=1)
    assert recorder.wait_for(UnleashEventType.FETCHED, count=1)
    dispatcher.close(timeout=WAIT_TIMEOUT)


@responses.activate
def test_polling_connector_emits_ready_once_across_polls(
    cache_empty, dispatcher, recorder
):
    engine = UnleashEngine()
    scheduler = Scheduler()
    responses.add(
        responses.GET, FULL_FEATURE_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )

    connector = PollingConnector(
        store=FeatureStore(engine=engine, cache=cache_empty, events=dispatcher),
        scheduler=scheduler,
        url=URL,
        app_name=APP_NAME,
        instance_id=INSTANCE_ID,
        headers=CUSTOM_HEADERS,
        custom_options=CUSTOM_OPTIONS,
        request_timeout=REQUEST_TIMEOUT,
        request_retries=REQUEST_RETRIES,
    )

    # Every poll emits READY twice, once from load_from_cache() and once directly.
    connector._fetch_and_load()
    connector._fetch_and_load()
    dispatcher.close(timeout=WAIT_TIMEOUT)

    assert len(recorder.of_type(UnleashEventType.READY)) == 1
    assert len(recorder.of_type(UnleashEventType.FETCHED)) == 2


@responses.activate
def test_polling_connector_start_stop(cache_empty):
    engine = UnleashEngine()
    scheduler = Scheduler()
    scheduler.start()

    responses.add(
        responses.GET,
        FULL_FEATURE_URL,
        json=MOCK_FEATURE_RESPONSE,
        status=200,
        headers={"etag": ETAG_VALUE},
    )
    temp_cache = cache_empty

    connector = PollingConnector(
        store=FeatureStore(engine=engine, cache=temp_cache),
        scheduler=scheduler,
        url=URL,
        app_name=APP_NAME,
        instance_id=INSTANCE_ID,
        headers=CUSTOM_HEADERS,
        custom_options=CUSTOM_OPTIONS,
        request_timeout=REQUEST_TIMEOUT,
        request_retries=REQUEST_RETRIES,
        refresh_interval=1,
    )

    connector.start()
    assert connector.job is not None

    connector.stop()
    assert connector.job is None

    scheduler.shutdown()
