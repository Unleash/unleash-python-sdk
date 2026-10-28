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
from UnleashClient._event_dispatcher import _EventDispatcher
from UnleashClient._feature_store import _FeatureStore
from UnleashClient._headers import _HeaderFactory
from UnleashClient._scheduler import _Scheduler
from UnleashClient._transport import _Transport
from UnleashClient.config import (
    HttpOptions,
    IdentityOptions,
    PollingOptions,
    UnleashConfig,
)
from UnleashClient.connectors import PollingConnector
from UnleashClient.constants import ETAG, FEATURES_URL
from UnleashClient.events import UnleashEventType

FULL_FEATURE_URL = URL + FEATURES_URL


def build_transport(**kwargs) -> _Transport:
    defaults = {
        "identity": IdentityOptions(instance_id=INSTANCE_ID),
        "http": HttpOptions(
            headers=CUSTOM_HEADERS,
            options=CUSTOM_OPTIONS,
            timeout=REQUEST_TIMEOUT,
            retries=REQUEST_RETRIES,
        ),
    }
    defaults.update(kwargs)
    config = UnleashConfig(URL, APP_NAME, **defaults)
    return _Transport(config, _HeaderFactory(config))


@responses.activate
def test_polling_connector_fetch_and_load(cache_empty):
    engine = UnleashEngine()
    scheduler = _Scheduler()
    responses.add(
        responses.GET,
        FULL_FEATURE_URL,
        json=MOCK_FEATURE_RESPONSE,
        status=200,
        headers={"etag": ETAG_VALUE},
    )
    temp_cache = cache_empty

    connector = PollingConnector(
        store=_FeatureStore(engine=engine, cache=temp_cache),
        scheduler=scheduler,
        transport=build_transport(),
        options=PollingOptions(),
    )

    connector._fetch_and_load()

    assert engine.is_enabled("testFlag", {}).is_enabled
    assert temp_cache.get(ETAG) == ETAG_VALUE


@responses.activate
def test_polling_connector_fetch_and_load_project(cache_empty):
    engine = UnleashEngine()
    scheduler = _Scheduler()
    responses.add(
        responses.GET, PROJECT_URL, json=MOCK_FEATURE_RESPONSE_PROJECT, status=200
    )
    temp_cache = cache_empty

    connector = PollingConnector(
        store=_FeatureStore(engine=engine, cache=temp_cache),
        scheduler=scheduler,
        transport=build_transport(),
        options=PollingOptions(project_name=PROJECT_NAME),
    )

    connector._fetch_and_load()

    assert engine.is_enabled("ivan-project", {}).is_enabled


@responses.activate
def test_polling_connector_fetch_and_load_failure(cache_empty):
    engine = UnleashEngine()
    scheduler = _Scheduler()
    responses.add(
        responses.GET, FULL_FEATURE_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )
    temp_cache = cache_empty

    connector = PollingConnector(
        store=_FeatureStore(engine=engine, cache=temp_cache),
        scheduler=scheduler,
        transport=build_transport(),
        options=PollingOptions(),
    )

    connector._fetch_and_load()

    responses.reset()
    responses.add(responses.GET, FULL_FEATURE_URL, json={}, status=500)

    connector._fetch_and_load()

    assert engine.is_enabled("testFlag", {}).is_enabled


@responses.activate
def test_polling_connector_emits_fetched_and_ready(
    cache_empty, dispatcher: _EventDispatcher, recorder: EventRecorder
):
    engine = UnleashEngine()
    scheduler = _Scheduler()
    responses.add(
        responses.GET,
        FULL_FEATURE_URL,
        json=MOCK_FEATURE_RESPONSE,
        status=200,
        headers={"etag": ETAG_VALUE},
    )

    connector = PollingConnector(
        store=_FeatureStore(engine=engine, cache=cache_empty, events=dispatcher),
        scheduler=scheduler,
        transport=build_transport(),
        # Huge refresh interval to avoid any polling during the test. That
        # way we avoid having to call _fetch_and_load() directly and can test the start/stop behavior.
        options=PollingOptions(interval=10),
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
    scheduler = _Scheduler()
    responses.add(
        responses.GET, FULL_FEATURE_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )

    connector = PollingConnector(
        store=_FeatureStore(engine=engine, cache=cache_empty, events=dispatcher),
        scheduler=scheduler,
        transport=build_transport(),
        options=PollingOptions(),
    )

    # Every poll emits READY from load_from_cache(), then FETCHED.
    connector._fetch_and_load()
    connector._fetch_and_load()

    # close() drops whatever is still queued, so wait for delivery first
    assert recorder.wait_for(UnleashEventType.FETCHED, count=2)
    dispatcher.close(timeout=WAIT_TIMEOUT)

    assert len(recorder.of_type(UnleashEventType.READY)) == 1


@responses.activate
def test_polling_connector_start_stop(cache_empty):
    engine = UnleashEngine()
    scheduler = _Scheduler()
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
        store=_FeatureStore(engine=engine, cache=temp_cache),
        scheduler=scheduler,
        transport=build_transport(),
        options=PollingOptions(interval=1),
    )

    connector.start()
    assert connector.job is not None

    connector.stop()
    assert connector.job is None

    scheduler.shutdown()
