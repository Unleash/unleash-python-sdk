import json
import threading
import time
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path

import pytest
import responses
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from blinker import Signal, signal

from tests.utilities.mocks.mock_all_features import MOCK_ALL_FEATURES
from tests.utilities.mocks.mock_features import (
    MOCK_FEATURE_ENABLED_NO_VARIANTS_RESPONSE,
    MOCK_FEATURE_RESPONSE,
    MOCK_FEATURE_RESPONSE_PROJECT,
    MOCK_FEATURE_WITH_CUSTOM_CONTEXT_REQUIREMENTS,
    MOCK_FEATURE_WITH_DATE_AFTER_CONSTRAINT,
    MOCK_FEATURE_WITH_DEPENDENCIES_RESPONSE,
    MOCK_FEATURE_WITH_NUMERIC_CONSTRAINT,
)
from tests.utilities.testing_constants import (
    APP_NAME,
    CUSTOM_HEADERS,
    CUSTOM_OPTIONS,
    DISABLE_METRICS,
    DISABLE_REGISTRATION,
    ENVIRONMENT,
    ETAG_VALUE,
    INSTANCE_ID,
    METRICS_INTERVAL,
    METRICS_JITTER,
    PROJECT_NAME,
    PROJECT_URL,
    REFRESH_INTERVAL,
    REFRESH_JITTER,
    REQUEST_RETRIES,
    REQUEST_TIMEOUT,
    URL,
)
from UnleashClient import INSTANCES, UnleashClient
from UnleashClient.cache import FileCache
from UnleashClient.constants import (
    CLIENT_SPEC_VERSION,
    FEATURES_URL,
    METRICS_URL,
    REGISTER_URL,
)
from UnleashClient.events import BaseEvent, UnleashEvent, UnleashEventType
from UnleashClient.utils import InstanceAllowType


class EnvironmentStrategy:
    def load_provisioning(self, parameters) -> list:
        return [x.strip() for x in parameters["environments"].split(",")]

    def apply(self, parameters: dict, context: dict = None) -> bool:
        """
        Turn on if environemnt is a match.

        :return:
        """
        default_value = False
        parsed_provisioning = self.load_provisioning(parameters)

        if "environment" in context.keys():
            default_value = context["environment"] in parsed_provisioning

        return default_value


def build_event_handlers():
    send_data = Signal()
    ready_signal = threading.Event()
    fetch_signal = threading.Event()

    @send_data.connect
    def handle_event(sender, **kw):
        if kw["data"].event_type == UnleashEventType.READY:
            ready_signal.set()
        if kw["data"].event_type == UnleashEventType.FETCHED:
            fetch_signal.set()

    def event_handler(event: BaseEvent):
        send_data.send("anonymous", data=event)

    return event_handler, ready_signal, fetch_signal


@pytest.fixture(autouse=True)
def before_each():
    INSTANCES._reset()


@pytest.fixture
def cache(tmpdir):
    return FileCache(APP_NAME, directory=tmpdir.dirname)


@pytest.fixture()
def readyable_unleash_client(cache):
    send_data = Signal()
    ready_signal = threading.Event()
    fetch_signal = threading.Event()

    @send_data.connect
    def handle_event(sender, **kw):
        if kw["data"].event_type == UnleashEventType.READY:
            ready_signal.set()
        if kw["data"].event_type == UnleashEventType.FETCHED:
            fetch_signal.set()

    def event_handler(event: BaseEvent):
        send_data.send("anonymous", data=event)

    unleash_client = UnleashClient(
        URL,
        APP_NAME,
        refresh_interval=REFRESH_INTERVAL,
        metrics_interval=METRICS_INTERVAL,
        cache=cache,
        event_callback=event_handler,
    )
    yield unleash_client, ready_signal, fetch_signal
    unleash_client.destroy()


@pytest.fixture()
def readyable_unleash_client_project(cache):
    send_data = Signal()
    ready_signal = threading.Event()
    fetch_signal = threading.Event()

    @send_data.connect
    def handle_event(sender, **kw):
        if kw["data"].event_type == UnleashEventType.READY:
            ready_signal.set()
        if kw["data"].event_type == UnleashEventType.FETCHED:
            fetch_signal.set()

    def event_handler(event: BaseEvent):
        send_data.send("anonymous", data=event)

    unleash_client = UnleashClient(
        URL,
        APP_NAME,
        refresh_interval=REFRESH_INTERVAL,
        metrics_interval=METRICS_INTERVAL,
        cache=cache,
        project_name=PROJECT_NAME,
        event_callback=event_handler,
    )
    yield unleash_client, ready_signal, fetch_signal
    unleash_client.destroy()


@pytest.fixture()
def readyable_unleash_client_nodestroy(cache):
    send_data = Signal()
    ready_signal = threading.Event()
    fetch_signal = threading.Event()

    @send_data.connect
    def handle_event(sender, **kw):
        if kw["data"].event_type == UnleashEventType.READY:
            ready_signal.set()
        if kw["data"].event_type == UnleashEventType.FETCHED:
            fetch_signal.set()

    def event_handler(event: BaseEvent):
        send_data.send("anonymous", data=event)

    unleash_client = UnleashClient(
        URL,
        APP_NAME,
        refresh_interval=REFRESH_INTERVAL,
        metrics_interval=METRICS_INTERVAL,
        cache=cache,
        event_callback=event_handler,
    )
    yield unleash_client, ready_signal, fetch_signal


@pytest.fixture()
def readyable_unleash_client_toggle_only(cache):
    send_data = Signal()
    ready_signal = threading.Event()
    fetch_signal = threading.Event()

    @send_data.connect
    def handle_event(sender, **kw):
        if kw["data"].event_type == UnleashEventType.READY:
            ready_signal.set()
        if kw["data"].event_type == UnleashEventType.FETCHED:
            fetch_signal.set()

    def event_handler(event: BaseEvent):
        send_data.send("anonymous", data=event)

    unleash_client = UnleashClient(
        URL,
        APP_NAME,
        refresh_interval=REFRESH_INTERVAL,
        metrics_interval=METRICS_INTERVAL,
        disable_registration=True,
        disable_metrics=True,
        cache=cache,
        event_callback=event_handler,
    )
    yield unleash_client, ready_signal, fetch_signal
    unleash_client.destroy()


@pytest.fixture()
def unleash_client_bootstrap_dependencies():
    cache = FileCache("MOCK_CACHE")
    cache.bootstrap_from_dict(MOCK_FEATURE_WITH_DEPENDENCIES_RESPONSE)
    unleash_client = UnleashClient(
        url=URL,
        app_name=APP_NAME,
        disable_metrics=True,
        disable_registration=True,
        cache=cache,
        environment="default",
    )
    unleash_client.initialize_client(fetch_toggles=False)
    yield unleash_client


def test_UC_initialize_default():
    client = UnleashClient(URL, APP_NAME)
    assert client.unleash_url == URL
    assert client.unleash_app_name == APP_NAME
    assert client.unleash_metrics_interval == 60
    client.destroy()


def test_UC_initialize_full():
    client = UnleashClient(
        URL,
        APP_NAME,
        ENVIRONMENT,
        INSTANCE_ID,
        REFRESH_INTERVAL,
        REFRESH_JITTER,
        METRICS_INTERVAL,
        METRICS_JITTER,
        DISABLE_METRICS,
        DISABLE_REGISTRATION,
        CUSTOM_HEADERS,
        CUSTOM_OPTIONS,
        REQUEST_TIMEOUT,
        REQUEST_RETRIES,
    )
    assert client.unleash_instance_id == INSTANCE_ID
    assert client.unleash_refresh_interval == REFRESH_INTERVAL
    assert client.unleash_refresh_jitter == REFRESH_JITTER
    assert client.unleash_metrics_interval == METRICS_INTERVAL
    assert client.unleash_metrics_jitter == METRICS_JITTER
    assert client.unleash_disable_metrics == DISABLE_METRICS
    assert client.unleash_disable_registration == DISABLE_REGISTRATION
    assert client.unleash_custom_headers == CUSTOM_HEADERS
    assert client.unleash_custom_options == CUSTOM_OPTIONS
    client.destroy()


def test_UC_type_violation():
    client = UnleashClient(URL, APP_NAME, refresh_interval="60")
    assert client.unleash_url == URL
    assert client.unleash_app_name == APP_NAME
    assert client.unleash_refresh_interval == "60"
    client.destroy()


@responses.activate
def test_uc_lifecycle(readyable_unleash_client):
    unleash_client, ready_signal, fetch_signal = readyable_unleash_client
    # Set up API
    responses.add(responses.POST, URL + REGISTER_URL, json={}, status=202)
    responses.add(
        responses.GET,
        URL + FEATURES_URL,
        json=MOCK_FEATURE_RESPONSE,
        status=200,
        headers={"etag": ETAG_VALUE},
    )
    responses.add(responses.POST, URL + METRICS_URL, json={}, status=202)

    # Create Unleash client and check initial load
    unleash_client.initialize_client()
    ready_signal.wait()
    assert unleash_client.is_initialized
    assert len(unleash_client.feature_definitions()) >= 4

    # Simulate caching
    responses.add(
        responses.GET,
        URL + FEATURES_URL,
        json={},
        status=304,
        headers={"etag": ETAG_VALUE},
    )

    # Simulate server provisioning change
    responses.add(
        responses.GET,
        URL + FEATURES_URL,
        json=MOCK_ALL_FEATURES,
        status=200,
        headers={"etag": "W/somethingelse"},
    )
    fetch_signal.clear()
    fetch_signal.wait(timeout=REFRESH_INTERVAL * 3)
    assert len(unleash_client.feature_definitions()) >= 9


@responses.activate
def test_uc_is_enabled_basic(readyable_unleash_client):
    unleash_client, ready_signal, _ = readyable_unleash_client
    # Set up API
    responses.add(responses.POST, URL + REGISTER_URL, json={}, status=202)
    responses.add(
        responses.GET, URL + FEATURES_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )
    responses.add(responses.POST, URL + METRICS_URL, json={}, status=202)

    # Create Unleash client and check initial load
    unleash_client.initialize_client()
    ready_signal.wait(timeout=1)

    assert unleash_client.is_enabled("testFlag")


@responses.activate
def test_consistent_results(readyable_unleash_client):
    unleash_client, _, _ = readyable_unleash_client
    responses.add(responses.POST, URL + REGISTER_URL, json={}, status=202)
    responses.add(
        responses.GET, URL + FEATURES_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )
    responses.add(responses.POST, URL + METRICS_URL, json={}, status=202)
    unleash_client.initialize_client()

    results = [unleash_client.is_enabled("testFlag2") for i in range(1000)]
    true_count = results.count(True)
    false_count = results.count(False)

    # Due to murmur hash variations on smaller datasets, we allow a 10% discrepancy
    discrepancy = 100  # 10% of 1000
    assert (
        500 - discrepancy <= true_count <= 500 + discrepancy
    ), "True count is outside acceptable range"
    assert (
        500 - discrepancy <= false_count <= 500 + discrepancy
    ), "False count is outside acceptable range"


@responses.activate
def test_uc_project(readyable_unleash_client_project):
    unleash_client, ready_signal, _ = readyable_unleash_client_project

    # Set up API
    responses.add(responses.POST, URL + REGISTER_URL, json={}, status=202)
    responses.add(
        responses.GET, PROJECT_URL, json=MOCK_FEATURE_RESPONSE_PROJECT, status=200
    )
    responses.add(responses.POST, URL + METRICS_URL, json={}, status=202)

    # Create Unleash client and check initial load
    unleash_client.initialize_client()
    ready_signal.wait(timeout=1)
    assert unleash_client.is_enabled("ivan-project")


@responses.activate
def test_uc_fallbackfunction(readyable_unleash_client, mocker):
    unleash_client, ready_signal, _ = readyable_unleash_client

    def good_fallback(feature_name: str, context: dict) -> bool:
        return True

    def bad_fallback(feature_name: str, context: dict) -> bool:
        return False

    def context_fallback(feature_name: str, context: dict) -> bool:
        return context["wat"]

    # Set up API
    responses.add(responses.POST, URL + REGISTER_URL, json={}, status=202)
    responses.add(
        responses.GET, URL + FEATURES_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )
    responses.add(responses.POST, URL + METRICS_URL, json={}, status=202)
    fallback_spy = mocker.Mock(wraps=good_fallback)

    # Create Unleash client and check initial load
    unleash_client.initialize_client()
    ready_signal.wait(timeout=1)
    # Non-existent feature flag, fallback_function
    assert unleash_client.is_enabled("notFoundTestFlag", fallback_function=fallback_spy)
    assert fallback_spy.call_count == 1
    fallback_spy.reset_mock()

    # Non-existent feature flag, default value, fallback_function
    assert not unleash_client.is_enabled(
        "notFoundTestFlag", fallback_function=bad_fallback
    )
    assert fallback_spy.call_count == 0

    # Existent feature flag, fallback_function
    assert unleash_client.is_enabled("testFlag", fallback_function=good_fallback)
    assert fallback_spy.call_count == 0


@responses.activate
def test_uc_dirty_cache(readyable_unleash_client_nodestroy):
    unleash_client, ready_signal, _ = readyable_unleash_client_nodestroy
    # Set up API
    responses.add(responses.POST, URL + REGISTER_URL, json={}, status=202)
    responses.add(
        responses.GET, URL + FEATURES_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )
    responses.add(responses.POST, URL + METRICS_URL, json={}, status=202)

    # Create Unleash client and check initial load
    unleash_client.initialize_client()
    ready_signal.wait(timeout=1)
    assert unleash_client.is_enabled("testFlag")
    unleash_client.unleash_scheduler.shutdown()

    # Check that everything works if previous cache exists.
    unleash_client.initialize_client()
    ready_signal.wait(timeout=1)
    assert unleash_client.is_enabled("testFlag")


@responses.activate
def test_uc_is_enabled_with_context():
    event_handler, ready_signal, _ = build_event_handlers()

    # Set up API
    responses.add(responses.POST, URL + REGISTER_URL, json={}, status=202)
    responses.add(
        responses.GET, URL + FEATURES_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )
    responses.add(responses.POST, URL + METRICS_URL, json={}, status=202)

    custom_strategies_dict = {"custom-context": EnvironmentStrategy()}

    unleash_client = UnleashClient(
        URL,
        APP_NAME,
        environment="prod",
        custom_strategies=custom_strategies_dict,
        event_callback=event_handler,
    )
    # Create Unleash client and check initial load
    unleash_client.initialize_client()

    ready_signal.wait(timeout=1)
    assert unleash_client.is_enabled("testContextFlag")
    unleash_client.destroy()


@responses.activate
def test_uc_is_enabled_error_states(readyable_unleash_client):
    unleash_client, ready_signal, _ = readyable_unleash_client
    # Set up API
    responses.add(responses.POST, URL + REGISTER_URL, json={}, status=202)
    responses.add(
        responses.GET, URL + FEATURES_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )
    responses.add(responses.POST, URL + METRICS_URL, json={}, status=202)

    # Create Unleash client and check initial load
    unleash_client.initialize_client()
    ready_signal.wait(timeout=1)
    assert not unleash_client.is_enabled("ThisFlagDoesn'tExist")
    assert unleash_client.is_enabled(
        "ThisFlagDoesn'tExist", fallback_function=lambda x, y: True
    )


@responses.activate
def test_uc_context_manager(readyable_unleash_client_nodestroy):
    unleash_client, _, _ = readyable_unleash_client_nodestroy
    responses.add(responses.POST, URL + REGISTER_URL, json={}, status=202)
    responses.add(
        responses.GET, URL + FEATURES_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )
    responses.add(responses.POST, URL + METRICS_URL, json={}, status=202)

    with unleash_client as unleash_client:
        assert unleash_client.is_initialized
        assert unleash_client.is_enabled("testFlag")

    # Context Manager use case is usualy short-lived so even with a METRICS_INTERVAL of 2 seconds metrics can get lost.  Verify that metrics are sent on destroy.
    metrics_request = [
        call for call in responses.calls if METRICS_URL in call.request.url
    ][0].request
    metrics_body = json.loads(metrics_request.body)
    assert metrics_body["bucket"]["toggles"]["testFlag"]["yes"] == 1


@responses.activate
def test_uc_not_initialized_isenabled():
    unleash_client = UnleashClient(URL, APP_NAME)
    assert not unleash_client.is_enabled("ThisFlagDoesn'tExist")
    assert unleash_client.is_enabled(
        "ThisFlagDoesn'tExist", fallback_function=lambda x, y: True
    )
    unleash_client.destroy()


def test_uc_dependency(unleash_client_bootstrap_dependencies):
    unleash_client = unleash_client_bootstrap_dependencies
    assert unleash_client.is_enabled("Child")
    assert not unleash_client.is_enabled("WithDisabledDependency")
    assert unleash_client.is_enabled("ComplexExample")
    assert not unleash_client.is_enabled("UnlistedDependency")
    assert not unleash_client.is_enabled("TransitiveDependency")


@responses.activate
def test_uc_get_variant():
    # Set up API
    responses.add(responses.POST, URL + REGISTER_URL, json={}, status=202)
    responses.add(
        responses.GET, URL + FEATURES_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )
    responses.add(responses.POST, URL + METRICS_URL, json={}, status=202)

    event_handler, ready_signal, _ = build_event_handlers()

    unleash_client = UnleashClient(URL, APP_NAME, event_callback=event_handler)
    # Create Unleash client and check initial load
    unleash_client.initialize_client()

    ready_signal.wait(timeout=1)
    # If feature flag is on.
    variant = unleash_client.get_variant("testVariations", context={"userId": "2"})
    assert variant["name"] == "VarA"
    assert variant["enabled"]
    assert variant["feature_enabled"]

    # If feature flag is not.
    variant = unleash_client.get_variant("testVariations", context={"userId": "3"})
    assert variant["name"] == "disabled"
    assert not variant["enabled"]
    assert not variant["feature_enabled"]

    unleash_client.destroy()


@responses.activate
def test_uc_get_variant_feature_enabled_no_variants():
    cache = FileCache("MOCK_CACHE")
    cache.bootstrap_from_dict(MOCK_FEATURE_ENABLED_NO_VARIANTS_RESPONSE)
    unleash_client = UnleashClient(
        url=URL,
        app_name=APP_NAME,
        disable_metrics=True,
        disable_registration=True,
        cache=cache,
        environment="default",
    )
    unleash_client.initialize_client(fetch_toggles=False)

    # If feature is enabled but has no variants, should return disabled variant with feature_enabled=True
    variant = unleash_client.get_variant("EnabledNoVariants")
    assert variant["name"] == "disabled"
    assert not variant["enabled"]
    assert variant["feature_enabled"]

    unleash_client.destroy()


@responses.activate
def test_uc_not_initialized_getvariant():
    unleash_client = UnleashClient(URL, APP_NAME)
    variant = unleash_client.get_variant("ThisFlagDoesn'tExist")
    assert not variant["enabled"]
    assert variant["name"] == "disabled"
    assert not variant["feature_enabled"]
    unleash_client.destroy()


@responses.activate
def test_uc_metrics(readyable_unleash_client):
    unleash_client, ready_signal, _ = readyable_unleash_client
    # Set up API
    responses.add(responses.POST, URL + REGISTER_URL, json={}, status=202)
    responses.add(
        responses.GET, URL + FEATURES_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )
    responses.add(responses.POST, URL + METRICS_URL, json={}, status=202)

    # Create Unleash client and check initial load
    unleash_client.initialize_client()
    ready_signal.wait(timeout=1)
    assert unleash_client.is_enabled("testFlag")

    metrics = unleash_client.engine.get_metrics()["toggles"]
    assert metrics["testFlag"]["yes"] == 1


@responses.activate
def test_uc_registers_metrics_for_nonexistent_features(readyable_unleash_client):
    unleash_client, ready_signal, _ = readyable_unleash_client
    # Set up API
    responses.add(responses.POST, URL + REGISTER_URL, json={}, status=202)
    responses.add(
        responses.GET, URL + FEATURES_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )

    # Create Unleash client and check initial load
    unleash_client.initialize_client()
    ready_signal.wait(timeout=1)

    # Check a flag that doesn't exist
    unleash_client.is_enabled("nonexistent-flag")

    # Verify that the metrics are serialized
    metrics = unleash_client.engine.get_metrics()["toggles"]
    assert metrics["nonexistent-flag"]["no"] == 1


@responses.activate
def test_uc_metrics_dependencies(readyable_unleash_client):
    unleash_client, ready_signal, _ = readyable_unleash_client
    responses.add(responses.POST, URL + REGISTER_URL, json={}, status=202)
    responses.add(
        responses.GET,
        URL + FEATURES_URL,
        json=MOCK_FEATURE_WITH_DEPENDENCIES_RESPONSE,
        status=200,
    )

    unleash_client.initialize_client()
    ready_signal.wait(timeout=1)
    assert unleash_client.is_enabled("Child")

    metrics = unleash_client.engine.get_metrics()["toggles"]
    assert metrics["Child"]["yes"] == 1
    assert "Parent" not in metrics


@responses.activate
def test_uc_registers_variant_metrics_for_nonexistent_features(
    readyable_unleash_client,
):
    unleash_client, ready_signal, _ = readyable_unleash_client
    # Set up API
    responses.add(responses.POST, URL + REGISTER_URL, json={}, status=202)
    responses.add(
        responses.GET, URL + FEATURES_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )

    # Create Unleash client and check initial load
    unleash_client.initialize_client()
    ready_signal.wait(timeout=1)

    # Check a flag that doesn't exist
    unleash_client.get_variant("nonexistent-flag")

    metrics = unleash_client.engine.get_metrics()["toggles"]
    assert metrics["nonexistent-flag"]["no"] == 1
    assert metrics["nonexistent-flag"]["variants"]["disabled"] == 1


@responses.activate
def test_uc_doesnt_count_metrics_for_dependency_parents(readyable_unleash_client):
    unleash_client, ready_signal, _ = readyable_unleash_client
    # Set up API
    responses.add(responses.POST, URL + REGISTER_URL, json={}, status=202)
    responses.add(
        responses.GET,
        URL + FEATURES_URL,
        json=MOCK_FEATURE_WITH_DEPENDENCIES_RESPONSE,
        status=200,
    )

    # Create Unleash client and check initial load
    unleash_client.initialize_client()
    ready_signal.wait(timeout=1)

    child = "ChildWithVariant"
    parent = "Parent"
    # Check a flag that depends on a parent
    unleash_client.is_enabled(child)
    unleash_client.get_variant(child)

    # Verify that the parent doesn't have any metrics registered
    metrics = unleash_client.engine.get_metrics()["toggles"]
    assert metrics[child]["yes"] == 2
    assert metrics[child]["variants"]["childVariant"] == 1
    assert parent not in metrics


@responses.activate
def test_uc_counts_metrics_for_child_even_if_parent_is_disabled(
    readyable_unleash_client,
):
    unleash_client, ready_signal, _ = readyable_unleash_client
    # Set up API
    responses.add(responses.POST, URL + REGISTER_URL, json={}, status=202)
    responses.add(
        responses.GET,
        URL + FEATURES_URL,
        json=MOCK_FEATURE_WITH_DEPENDENCIES_RESPONSE,
        status=200,
    )

    # Create Unleash client and check initial load
    unleash_client.initialize_client()
    ready_signal.wait(timeout=1)

    child = "WithDisabledDependency"
    parent = "Disabled"
    # Check a flag that depends on a disabled parent
    unleash_client.is_enabled(child)
    unleash_client.get_variant(child)

    # Verify that the parent doesn't have any metrics registered
    metrics = unleash_client.engine.get_metrics()["toggles"]
    assert metrics[child]["no"] == 2
    assert metrics[child]["variants"]["disabled"] == 1
    assert parent not in metrics


@responses.activate
def test_uc_disabled_registration(readyable_unleash_client_toggle_only):
    unleash_client, ready_signal, _ = readyable_unleash_client_toggle_only
    # Set up APIs
    responses.add(responses.POST, URL + REGISTER_URL, json={}, status=401)
    responses.add(
        responses.GET, URL + FEATURES_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )
    responses.add(responses.POST, URL + METRICS_URL, json={}, status=401)

    unleash_client.initialize_client()
    unleash_client.is_enabled("testFlag")
    ready_signal.wait(timeout=1)
    assert unleash_client.is_enabled("testFlag")

    for api_call in responses.calls:
        assert "/api/client/features" in api_call.request.url


@responses.activate
def test_uc_server_error(readyable_unleash_client):
    unleash_client, ready_signal, _ = readyable_unleash_client
    # Verify that Unleash Client will still fall back gracefully if SERVER ANGRY RAWR, and then recover gracefully.
    # Set up APIs
    responses.add(responses.POST, URL + REGISTER_URL, json={}, status=401)
    responses.add(responses.GET, URL + FEATURES_URL, status=500)
    responses.add(responses.POST, URL + METRICS_URL, json={}, status=401)

    unleash_client.initialize_client()
    assert not unleash_client.is_enabled("testFlag")

    responses.remove(responses.GET, URL + FEATURES_URL)
    responses.add(
        responses.GET, URL + FEATURES_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )
    ready_signal.wait(REFRESH_INTERVAL * 2)
    assert unleash_client.is_enabled("testFlag")


def test_uc_with_invalid_url():
    unleash_client = UnleashClient("thisisnotavalidurl", APP_NAME)

    with pytest.raises(ValueError):
        unleash_client.initialize_client()
    unleash_client.destroy()


def test_uc_with_network_error():
    unleash_client = UnleashClient(
        "https://this-will-never-try-to-dns-resolve.invalid/",
        APP_NAME,
        disable_metrics=True,
        disable_registration=True,
        request_timeout=1,
    )
    unleash_client.initialize_client()

    assert unleash_client.is_enabled
    unleash_client.destroy()


@responses.activate
def test_uc_multiple_initializations(readyable_unleash_client):
    unleash_client, ready_signal, _ = readyable_unleash_client
    # Set up API
    responses.add(responses.POST, URL + REGISTER_URL, json={}, status=202)
    responses.add(
        responses.GET,
        URL + FEATURES_URL,
        json=MOCK_FEATURE_RESPONSE,
        status=200,
        headers={"etag": ETAG_VALUE},
    )
    responses.add(responses.POST, URL + METRICS_URL, json={}, status=202)

    # Create Unleash client and check initial load
    unleash_client.initialize_client()
    ready_signal.wait(timeout=1)
    assert unleash_client.is_initialized
    assert len(unleash_client.feature_definitions()) >= 4

    with warnings.catch_warnings(record=True) as w:
        # Try and initialize client again.
        unleash_client.initialize_client()

    assert len(w) == 1
    assert "initialize" in str(w[0].message)


@responses.activate
def test_uc_cache_bootstrap_dict(cache):
    # Set up API
    responses.add(responses.POST, URL + REGISTER_URL, json={}, status=202)
    responses.add(
        responses.GET,
        URL + FEATURES_URL,
        json=MOCK_FEATURE_RESPONSE,
        status=200,
        headers={"etag": ETAG_VALUE},
    )
    responses.add(responses.POST, URL + METRICS_URL, json={}, status=202)

    # Set up cache
    cache.bootstrap_from_dict(initial_config=MOCK_FEATURE_RESPONSE_PROJECT)
    event_handler, ready_signal, _ = build_event_handlers()

    # Check bootstrapping
    unleash_client = UnleashClient(
        URL,
        APP_NAME,
        refresh_interval=REFRESH_INTERVAL,
        metrics_interval=METRICS_INTERVAL,
        cache=cache,
        event_callback=event_handler,
    )
    assert len(unleash_client.feature_definitions()) == 1
    assert unleash_client.is_enabled("ivan-project")

    # Create Unleash client and check initial load
    unleash_client.initialize_client()
    ready_signal.wait(timeout=1)
    assert unleash_client.is_initialized
    assert len(unleash_client.feature_definitions()) >= 4
    assert unleash_client.is_enabled("testFlag")


@responses.activate
def test_uc_cache_bootstrap_file(cache):
    # Set up cache
    test_file = Path(
        Path(__file__).parent.resolve(),
        "..",
        "utilities",
        "mocks",
        "mock_bootstrap.json",
    )
    cache.bootstrap_from_file(initial_config_file=test_file)

    # Check bootstrapping
    unleash_client = UnleashClient(
        URL,
        APP_NAME,
        refresh_interval=REFRESH_INTERVAL,
        metrics_interval=METRICS_INTERVAL,
        cache=cache,
    )
    assert len(unleash_client.feature_definitions()) >= 1
    assert unleash_client.is_enabled("ivan-project")


@responses.activate
def test_uc_cache_bootstrap_url(cache):
    # Set up API
    responses.add(
        responses.GET,
        URL + FEATURES_URL,
        json=MOCK_FEATURE_RESPONSE,
        status=200,
        headers={"etag": ETAG_VALUE},
    )

    # Set up cache
    cache.bootstrap_from_url(initial_config_url=URL + FEATURES_URL)

    # Check bootstrapping
    unleash_client = UnleashClient(
        URL,
        APP_NAME,
        refresh_interval=REFRESH_INTERVAL,
        metrics_interval=METRICS_INTERVAL,
        cache=cache,
    )
    assert len(unleash_client.feature_definitions()) >= 4
    assert unleash_client.is_enabled("testFlag")


@responses.activate
def test_uc_custom_scheduler():
    # Set up API
    responses.add(
        responses.GET,
        URL + FEATURES_URL,
        json=MOCK_FEATURE_RESPONSE,
        status=200,
        headers={"etag": ETAG_VALUE},
    )

    # Set up UnleashClient
    custom_executors = {"hamster_executor": ThreadPoolExecutor()}

    custom_scheduler = BackgroundScheduler(executors=custom_executors)

    event_handler, ready_signal, fetch_signal = build_event_handlers()

    unleash_client = UnleashClient(
        URL,
        APP_NAME,
        refresh_interval=REFRESH_INTERVAL,
        disable_metrics=True,
        disable_registration=True,
        scheduler=custom_scheduler,
        scheduler_executor="hamster_executor",
        event_callback=event_handler,
    )

    # Create Unleash client and check initial load
    unleash_client.initialize_client()
    ready_signal.wait(timeout=1)
    assert unleash_client.is_initialized
    assert len(unleash_client.feature_definitions()) >= 4

    # Simulate caching
    responses.add(
        responses.GET,
        URL + FEATURES_URL,
        json={},
        status=304,
        headers={"etag": ETAG_VALUE},
    )

    # Simulate server provisioning change
    responses.add(
        responses.GET,
        URL + FEATURES_URL,
        json=MOCK_ALL_FEATURES,
        status=200,
        headers={"etag": "W/somethingelse"},
    )
    fetch_signal.wait(timeout=REFRESH_INTERVAL * 3)
    assert len(unleash_client.feature_definitions()) >= 9
    unleash_client.destroy()


def test_multiple_instances_blocks_client_instantiation():
    client1 = None
    client2 = None
    with pytest.raises(Exception):
        client1 = UnleashClient(
            URL, APP_NAME, multiple_instance_mode=InstanceAllowType.BLOCK
        )
        client2 = UnleashClient(
            URL, APP_NAME, multiple_instance_mode=InstanceAllowType.BLOCK
        )
    if client1:
        client1.destroy()
    if client2:
        client2.destroy()


def test_multiple_instances_with_allow_multiple_warns(caplog):
    client1 = UnleashClient(
        URL, APP_NAME, multiple_instance_mode=InstanceAllowType.WARN
    )
    client2 = UnleashClient(
        URL, APP_NAME, multiple_instance_mode=InstanceAllowType.WARN
    )
    assert any(["You already have 1 instance" in r.msg for r in caplog.records])
    client1.destroy()
    client2.destroy()


def test_multiple_instances_tracks_current_instance_count(caplog):
    client1 = UnleashClient(URL, APP_NAME)
    client2 = UnleashClient(
        URL, APP_NAME, multiple_instance_mode=InstanceAllowType.WARN
    )
    client3 = UnleashClient(
        URL, APP_NAME, multiple_instance_mode=InstanceAllowType.WARN
    )
    assert any(["You already have 1 instance" in r.msg for r in caplog.records])
    assert any(["You already have 2 instance(s)" in r.msg for r in caplog.records])
    client1.destroy()
    client2.destroy()
    client3.destroy()


def test_multiple_instances_no_warnings_or_errors_with_different_client_configs(caplog):
    client1 = UnleashClient(URL, "some-probably-unique-app-name")
    client2 = UnleashClient(
        URL,
        "some-probably-unique-app-name",
        instance_id="some-unique-instance-id",
        refresh_interval="60",
    )
    client3 = UnleashClient(
        URL, "some-probably-unique-but-different-app-name", refresh_interval="60"
    )
    assert not any(
        ["Multiple instances has been disabled" in r.msg for r in caplog.records]
    )
    client1.destroy()
    client2.destroy()
    client3.destroy()


def test_multiple_instances_are_unique_on_api_key(caplog):
    client1 = UnleashClient(
        URL,
        "some-probably-unique-app-name",
        custom_headers={"Authorization": "penguins"},
    )
    client2 = UnleashClient(
        URL,
        "some-probably-unique-app-name",
        custom_headers={"Authorization": "hamsters"},
    )
    assert not any(
        ["Multiple instances has been disabled" in r.msg for r in caplog.records]
    )
    client1.destroy()
    client2.destroy()


@responses.activate
def test_signals_feature_flag(cache):
    # Set up API
    responses.add(
        responses.GET, URL + FEATURES_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )
    flag_event = None
    variant_event = None

    # Set up signals
    send_data = signal("send-data")
    ready_signal = threading.Event()

    @send_data.connect
    def receive_data(sender, **kw):
        #  variant_event
        if kw["data"].event_type == UnleashEventType.FEATURE_FLAG:
            nonlocal flag_event
            flag_event = kw["data"]
        elif kw["data"].event_type == UnleashEventType.VARIANT:
            nonlocal variant_event
            variant_event = kw["data"]
        elif kw["data"].event_type == UnleashEventType.READY:
            ready_signal.set()

    def example_callback(event: UnleashEvent):
        send_data.send("anonymous", data=event)

    # Set up Unleash
    unleash_client = UnleashClient(
        URL,
        APP_NAME,
        refresh_interval=REFRESH_INTERVAL,
        disable_registration=True,
        disable_metrics=True,
        cache=cache,
        event_callback=example_callback,
    )

    # Create Unleash client and check initial load
    unleash_client.initialize_client()
    ready_signal.wait(timeout=1)

    assert unleash_client.is_enabled("testFlag")
    variant = unleash_client.get_variant("testVariations", context={"userId": "2"})
    assert variant["name"] == "VarA"

    assert flag_event.feature_name == "testFlag"
    assert flag_event.enabled

    assert variant_event.feature_name == "testVariations"
    assert variant_event.enabled
    assert variant_event.variant == "VarA"
    unleash_client.destroy()


@responses.activate
def test_fetch_signal(cache):
    # Set up API
    responses.add(responses.POST, URL + REGISTER_URL, json={}, status=202)
    responses.add(
        responses.GET, URL + FEATURES_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )
    responses.add(responses.POST, URL + METRICS_URL, json={}, status=202)
    trapped_event = None

    # Set up signals
    send_data = signal("send-data")
    fetch_signal = threading.Event()

    @send_data.connect
    def receive_data(sender, **kw):

        if kw["data"].event_type == UnleashEventType.FETCHED:
            nonlocal trapped_event
            trapped_event = kw["data"]
            fetch_signal.set()

    def example_callback(event: UnleashEvent):
        send_data.send("anonymous", data=event)

    # Set up Unleash
    unleash_client = UnleashClient(
        URL,
        APP_NAME,
        refresh_interval=REFRESH_INTERVAL,
        metrics_interval=METRICS_INTERVAL,
        cache=cache,
        event_callback=example_callback,
    )

    # Create Unleash client and check initial load
    unleash_client.initialize_client()
    fetch_signal.wait(timeout=1)

    assert trapped_event.features[0]["name"] == "testFlag"


@responses.activate
def test_ready_signal(cache):
    responses.add(
        responses.GET, URL + FEATURES_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )
    trapped_events = 0

    # Set up signals
    send_data = signal("send-data")
    ready_signal = threading.Event()

    @send_data.connect
    def receive_data(sender, **kw):
        if kw["data"].event_type == UnleashEventType.READY:
            nonlocal trapped_events
            trapped_events += 1
            ready_signal.set()

    def example_callback(event: UnleashEvent):
        send_data.send("anonymous", data=event)

    unleash_client = UnleashClient(
        URL,
        APP_NAME,
        refresh_interval=1,  # minimum interval is 1 second
        disable_metrics=True,
        disable_registration=True,
        cache=cache,
        event_callback=example_callback,
    )

    unleash_client.initialize_client()
    ready_signal.wait(timeout=1)

    assert trapped_events == 1
    unleash_client.destroy()


def test_ready_signal_works_with_bootstrapping():
    cache = FileCache("MOCK_CACHE")
    cache.bootstrap_from_dict(MOCK_FEATURE_WITH_DEPENDENCIES_RESPONSE)

    trapped_events = 0

    # Set up signals
    send_data = signal("send-data")
    ready_signal = threading.Event()

    @send_data.connect
    def receive_data(sender, **kw):
        if kw["data"].event_type == UnleashEventType.READY:
            nonlocal trapped_events
            trapped_events += 1

    def example_callback(event: UnleashEvent):
        send_data.send("anonymous", data=event)

    unleash_client = UnleashClient(
        url=URL,
        app_name=APP_NAME,
        cache=cache,
        disable_metrics=True,
        disable_registration=True,
        event_callback=example_callback,
    )

    unleash_client.initialize_client(fetch_toggles=False)
    ready_signal.wait(timeout=1)

    assert trapped_events == 1

    unleash_client.destroy()


def test_context_handles_numerics():
    cache = FileCache("MOCK_CACHE")
    cache.bootstrap_from_dict(MOCK_FEATURE_WITH_NUMERIC_CONSTRAINT)

    unleash_client = UnleashClient(
        url=URL,
        app_name=APP_NAME,
        disable_metrics=True,
        disable_registration=True,
        cache=cache,
        environment="default",
    )

    context = {"userId": 99999}

    assert unleash_client.is_enabled("NumericConstraint", context)
    unleash_client.destroy()


def test_context_handles_datetimes():
    cache = FileCache("MOCK_CACHE")
    cache.bootstrap_from_dict(MOCK_FEATURE_RESPONSE)

    unleash_client = UnleashClient(
        url=URL,
        app_name=APP_NAME,
        disable_metrics=True,
        disable_registration=True,
        cache=cache,
        environment="default",
    )

    current_time = datetime.fromisoformat("1834-02-20").replace(tzinfo=timezone.utc)
    context = {"currentTime": current_time}

    assert unleash_client.is_enabled("testConstraintFlag", context)
    unleash_client.destroy()


def test_context_adds_current_time_if_not_set():
    cache = FileCache("MOCK_CACHE")
    cache.bootstrap_from_dict(MOCK_FEATURE_WITH_DATE_AFTER_CONSTRAINT)

    unleash_client = UnleashClient(
        url=URL,
        app_name=APP_NAME,
        disable_metrics=True,
        disable_registration=True,
        cache=cache,
        environment="default",
    )

    assert unleash_client.is_enabled("DateConstraint")
    unleash_client.destroy()


def test_context_moves_properties_fields_to_properties():
    unleash_client = UnleashClient(
        URL,
        APP_NAME,
        disable_metrics=True,
        disable_registration=True,
    )

    context = {"myContext": "1234"}

    assert "myContext" in unleash_client._safe_context(context)["properties"]
    unleash_client.destroy()


def test_existing_properties_are_retained_when_custom_context_properties_are_in_the_root():
    unleash_client = UnleashClient(
        URL,
        APP_NAME,
        disable_metrics=True,
        disable_registration=True,
    )

    context = {"myContext": "1234", "properties": {"yourContext": "1234"}}

    assert "myContext" in unleash_client._safe_context(context)["properties"]
    assert "yourContext" in unleash_client._safe_context(context)["properties"]
    unleash_client.destroy()


def test_base_context_properties_are_retained_in_root():
    unleash_client = UnleashClient(
        URL,
        APP_NAME,
        disable_metrics=True,
        disable_registration=True,
    )

    context = {"userId": "1234"}

    assert "userId" in unleash_client._safe_context(context)
    unleash_client.destroy()


def test_is_enabled_works_with_properties_field_in_the_context_root():
    cache = FileCache("MOCK_CACHE")
    cache.bootstrap_from_dict(MOCK_FEATURE_WITH_CUSTOM_CONTEXT_REQUIREMENTS)
    unleash_client = UnleashClient(
        URL,
        APP_NAME,
        disable_metrics=True,
        cache=cache,
        disable_registration=True,
    )

    context = {"myContext": "1234"}
    assert unleash_client.is_enabled("customContextToggle", context)
    unleash_client.destroy()


def test_uuids_are_valid_context_properties():
    unleash_client = UnleashClient(
        URL,
        APP_NAME,
        disable_metrics=True,
        disable_registration=True,
    )

    context = {"userId": uuid.uuid4()}

    try:
        unleash_client.is_enabled("testFlag", context)
    except Exception as e:
        assert (
            False
        ), f"An exception was raised when passing a UUID as a context property: {e}"
    unleash_client.destroy()


@responses.activate
def test_identification_headers_sent_and_consistent(readyable_unleash_client):
    unleash_client, _, _ = readyable_unleash_client
    responses.add(responses.POST, URL + REGISTER_URL, json={}, status=202)
    responses.add(
        responses.GET, URL + FEATURES_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )
    responses.add(responses.POST, URL + METRICS_URL, json={}, status=202)
    unleash_client.initialize_client()

    connection_id = responses.calls[0].request.headers["UNLEASH-CONNECTION-ID"]
    app_name = responses.calls[0].request.headers["UNLEASH-APPNAME"]
    sdk = responses.calls[0].request.headers["UNLEASH-SDK"]

    for api_call in responses.calls:
        assert api_call.request.headers["UNLEASH-CONNECTION-ID"] == connection_id
        assert api_call.request.headers["UNLEASH-APPNAME"] == app_name
        assert api_call.request.headers["UNLEASH-SDK"] == sdk


@responses.activate
def test_identification_headers_unique_connection_id():
    responses.add(responses.POST, URL + REGISTER_URL, json={}, status=202)
    responses.add(
        responses.GET, URL + FEATURES_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )
    responses.add(responses.POST, URL + METRICS_URL, json={}, status=202)

    unleash_client = UnleashClient(
        URL, APP_NAME, disable_metrics=True, disable_registration=True
    )
    unleash_client.initialize_client()
    connection_id_first_client = responses.calls[0].request.headers[
        "UNLEASH-CONNECTION-ID"
    ]

    other_unleash_client = UnleashClient(
        URL, APP_NAME, disable_metrics=True, disable_registration=True
    )
    other_unleash_client.initialize_client()

    connection_id_second_client = responses.calls[1].request.headers[
        "UNLEASH-CONNECTION-ID"
    ]
    assert connection_id_first_client != connection_id_second_client


@responses.activate
def test_identification_values_are_passed_in():
    responses.add(responses.POST, URL + REGISTER_URL, json={}, status=202)
    responses.add(
        responses.GET, URL + FEATURES_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )
    responses.add(responses.POST, URL + METRICS_URL, json={}, status=202)
    event_handler, ready_signal, _ = build_event_handlers()

    refresh_interval = 1
    metrics_interval = 1
    unleash_client = UnleashClient(
        URL,
        APP_NAME,
        refresh_interval=refresh_interval,
        metrics_interval=metrics_interval,
        event_callback=event_handler,
    )

    expected_refresh_interval = str(refresh_interval * 1000)
    expected_metrics_interval = str(metrics_interval * 1000)

    unleash_client.initialize_client()
    register_request = responses.calls[0].request
    register_body = json.loads(register_request.body)

    assert "connectionId" in register_body, "Key missing: connectionId"
    try:
        uuid.UUID(register_body["connectionId"])
    except ValueError:
        assert False, "Invalid UUID format in connectionId"

    assert (
        "UNLEASH-CONNECTION-ID" in register_request.headers
    ), "Header missing: UNLEASH-CONNECTION-ID"
    try:
        uuid.UUID(register_request.headers["UNLEASH-CONNECTION-ID"])
    except ValueError:
        assert False, "Invalid UUID format in UNLEASH-CONNECTION-ID"

    unleash_client.is_enabled("registerMetricsFlag")

    features_request = responses.calls[1].request

    assert features_request.headers["UNLEASH-INTERVAL"] == expected_refresh_interval

    assert (
        "UNLEASH-CONNECTION-ID" in features_request.headers
    ), "Header missing: UNLEASH-CONNECTION-ID"

    try:
        uuid.UUID(features_request.headers["UNLEASH-CONNECTION-ID"])
    except ValueError:
        assert False, "Invalid UUID format in UNLEASH-CONNECTION-ID"

    time.sleep(1.5)
    metrics_request = [
        call for call in responses.calls if METRICS_URL in call.request.url
    ][0].request
    metrics_body = json.loads(metrics_request.body)

    assert metrics_request.headers["UNLEASH-INTERVAL"] == expected_metrics_interval

    assert "connectionId" in metrics_body, "Key missing: connectionId"
    try:
        uuid.UUID(metrics_body["connectionId"])
    except ValueError:
        assert False, "Invalid UUID format in connectionId"

    assert (
        "UNLEASH-CONNECTION-ID" in metrics_request.headers
    ), "Header missing: UNLEASH-CONNECTION-ID"
    try:
        uuid.UUID(metrics_request.headers["UNLEASH-CONNECTION-ID"])
    except ValueError:
        assert False, "Invalid UUID format in UNLEASH-CONNECTION-ID"


@responses.activate
def test_uc_polling_connector_sends_spec_version_header(readyable_unleash_client):
    """Test that the client sends spec version header when using polling connector"""
    unleash_client, ready_signal, _ = readyable_unleash_client

    # Set up API
    responses.add(responses.POST, URL + REGISTER_URL, json={}, status=202)
    responses.add(
        responses.GET, URL + FEATURES_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )
    responses.add(responses.POST, URL + METRICS_URL, json={}, status=202)

    # Initialize client (which should use polling by default)
    unleash_client.initialize_client()
    ready_signal.wait(timeout=1)

    # Find the features request (should be the GET request to FEATURES_URL)
    features_requests = [
        call
        for call in responses.calls
        if call.request.method == "GET" and FEATURES_URL in call.request.url
    ]

    assert len(features_requests) >= 1, "No features request found"
    features_request = features_requests[0].request

    # Verify the spec version header is present
    assert (
        "Unleash-Client-Spec" in features_request.headers
    ), "Spec version header missing"
    assert features_request.headers["Unleash-Client-Spec"] == CLIENT_SPEC_VERSION


def test_uc_bootstrap_initializes_offline_connector():
    """Test that UnleashClient initializes OfflineConnector when bootstrapped."""
    cache = FileCache("MOCK_CACHE")
    cache.bootstrap_from_dict(MOCK_FEATURE_RESPONSE)

    unleash_client = UnleashClient(
        URL,
        APP_NAME,
        cache=cache,
        disable_metrics=True,
        disable_registration=True,
    )

    assert unleash_client.unleash_bootstrapped
    assert unleash_client.is_enabled("testFlag")

    unleash_client.destroy()
