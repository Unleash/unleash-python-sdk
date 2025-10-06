import responses
from apscheduler.schedulers.background import BackgroundScheduler
from yggdrasil_engine.engine import UnleashEngine

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
from UnleashClient.constants import (
    CLIENT_SPEC_VERSION,
    ETAG,
    FEATURES_URL,
)

FULL_FEATURE_URL = URL + FEATURES_URL


@responses.activate
def test_polling_connector_fetch_and_load(cache_empty):
    engine = UnleashEngine()
    scheduler = BackgroundScheduler()
    responses.add(
        responses.GET,
        FULL_FEATURE_URL,
        json=MOCK_FEATURE_RESPONSE,
        status=200,
        headers={"etag": ETAG_VALUE},
    )
    temp_cache = cache_empty

    connector = PollingConnector(
        engine=engine,
        cache=temp_cache,
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

    assert engine.is_enabled("testFlag", {})
    assert temp_cache.get(ETAG) == ETAG_VALUE


@responses.activate
def test_polling_connector_sends_spec_version_header(cache_empty):
    """Test that the polling connector sends the spec version header automatically"""
    engine = UnleashEngine()
    scheduler = BackgroundScheduler()
    responses.add(
        responses.GET,
        FULL_FEATURE_URL,
        json=MOCK_FEATURE_RESPONSE,
        status=200,
        headers={"etag": ETAG_VALUE},
    )
    temp_cache = cache_empty

    connector = PollingConnector(
        engine=engine,
        cache=temp_cache,
        scheduler=scheduler,
        url=URL,
        app_name=APP_NAME,
        instance_id=INSTANCE_ID,
        custom_options=CUSTOM_OPTIONS,
        request_timeout=REQUEST_TIMEOUT,
        request_retries=REQUEST_RETRIES,
    )

    connector._fetch_and_load()

    assert len(responses.calls) == 1
    request = responses.calls[0].request
    assert "Unleash-Client-Spec" in request.headers
    assert request.headers["Unleash-Client-Spec"] == CLIENT_SPEC_VERSION


@responses.activate
def test_polling_connector_fetch_and_load_project(cache_empty):
    engine = UnleashEngine()
    scheduler = BackgroundScheduler()
    responses.add(
        responses.GET, PROJECT_URL, json=MOCK_FEATURE_RESPONSE_PROJECT, status=200
    )
    temp_cache = cache_empty

    connector = PollingConnector(
        engine=engine,
        cache=temp_cache,
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

    assert engine.is_enabled("ivan-project", {})


@responses.activate
def test_polling_connector_fetch_and_load_failure(cache_empty):
    engine = UnleashEngine()
    scheduler = BackgroundScheduler()
    responses.add(
        responses.GET, FULL_FEATURE_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )
    temp_cache = cache_empty

    connector = PollingConnector(
        engine=engine,
        cache=temp_cache,
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

    assert engine.is_enabled("testFlag", {})


@responses.activate
def test_polling_connector_start_stop(cache_empty):
    engine = UnleashEngine()
    scheduler = BackgroundScheduler()
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
        engine=engine,
        cache=temp_cache,
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
