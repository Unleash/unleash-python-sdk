import asyncio
import json
from dataclasses import asdict
from typing import Callable

import pytest
import pytest_asyncio

from tests.utilities.events import WAIT_TIMEOUT, EventRecorder
from tests.utilities.fake_unleash_server import FakeUnleash
from tests.utilities.mocks.mock_features import (
    MOCK_FEATURE_RESPONSE,
    MOCK_FEATURE_RESPONSE_PROJECT,
)
from tests.utilities.testing_constants import APP_NAME, URL
from UnleashClient import INSTANCES, UnleashClient
from UnleashClient._async_metrics import _AsyncMetricsReporter
from UnleashClient._metrics import _MetricsReporter
from UnleashClient.cache import FileCache
from UnleashClient.clients.async_unleash_client import AsyncUnleashClient
from UnleashClient.constants import (
    ETAG,
    FEATURES_URL,
    METRICS_URL,
    REGISTER_URL,
)
from UnleashClient.errors import MultipleInstancesNotAllowedError
from UnleashClient.events import UnleashEventType
from UnleashClient.utils import InstanceAllowType


@pytest.fixture(autouse=True)
def before_each():
    INSTANCES._reset()


def build_async_client(tmpdir, **kwargs) -> AsyncUnleashClient:
    """
    The async client builds a real FileCache when it isn't given one, so tests
    keep it out of fcache's shared default directory.
    """
    kwargs.setdefault("cache_directory", str(tmpdir))
    return AsyncUnleashClient(**kwargs)


def known_toggles(engine) -> list:
    return sorted(toggle.name for toggle in engine.list_known_toggles())


def test_async_client_builds_the_shared_config(tmpdir):
    client = build_async_client(
        tmpdir, url="http://localhost:4242/api/", app_name=APP_NAME
    )

    assert client._config.url == URL
    assert client._config.app_name == APP_NAME
    assert client._config.refresh_interval == 15
    assert client._config.mode == "polling"


def test_both_clients_build_the_same_config(tmpdir):
    kwargs = dict(
        url="http://localhost:4242/api/",
        app_name=APP_NAME,
        environment="unit",
        instance_id="123",
        refresh_interval=1,
        refresh_jitter=2,
        metrics_interval=3,
        metrics_jitter=4,
        disable_metrics=True,
        disable_registration=True,
        custom_headers={"Authorization": "project:environment.hash"},
        custom_options={"verify": False},
        request_timeout=9,
        request_retries=2,
        project_name="ivan",
        verbose_log_level=40,
        experimental_mode={"type": "streaming"},
        sdk_flavor="openfeature",
        sdk_flavor_version="1.2.3",
    )

    sync_client = UnleashClient(
        cache=FileCache(APP_NAME, directory=str(tmpdir)), **kwargs
    )
    try:
        async_client = build_async_client(tmpdir, **kwargs)

        sync_config = asdict(sync_client._config)
        async_config = asdict(async_client._config)
        sync_config.pop("connection_id")
        async_config.pop("connection_id")

        assert sync_config == async_config
    finally:
        sync_client.destroy()


def test_async_client_builds_the_shared_headers(tmpdir):
    client = build_async_client(tmpdir, url=URL, app_name=APP_NAME, instance_id="123")

    headers = client._headers.base()

    assert headers["unleash-appname"] == APP_NAME
    assert headers["unleash-instanceid"] == "123"


def test_both_clients_build_the_same_headers(tmpdir):
    kwargs = dict(
        url=URL,
        app_name=APP_NAME,
        instance_id="123",
        refresh_interval=1,
        metrics_interval=3,
        custom_headers={"Authorization": "project:environment.hash"},
    )

    sync_client = UnleashClient(
        cache=FileCache(APP_NAME, directory=str(tmpdir)),
        disable_metrics=True,
        disable_registration=True,
        **kwargs,
    )
    try:
        async_client = build_async_client(tmpdir, **kwargs)

        for build in ("base", "polling", "metrics", "streaming"):
            sync_headers = getattr(sync_client._headers, build)()
            async_headers = getattr(async_client._headers, build)()
            # A fresh uuid per config, so it can never match.
            sync_headers.pop("unleash-connection-id")
            async_headers.pop("unleash-connection-id")

            assert sync_headers == async_headers
    finally:
        sync_client.destroy()


def test_async_client_enriches_context_over_its_own_config(tmpdir):
    client = build_async_client(tmpdir, url=URL, app_name=APP_NAME, environment="unit")

    context = client._enricher.build({"myContext": "1234"})

    assert context["appName"] == APP_NAME
    assert context["environment"] == "unit"
    assert context["properties"]["myContext"] == "1234"


def test_both_clients_enrich_context_identically(tmpdir):
    kwargs = dict(url=URL, app_name=APP_NAME, environment="unit")
    # currentTime is supplied so the two clients don't each generate their own.
    context = {
        "userId": 7,
        "myContext": "1234",
        "currentTime": "1834-02-20T00:00:00+00:00",
    }

    sync_client = UnleashClient(
        cache=FileCache(APP_NAME, directory=str(tmpdir)),
        disable_metrics=True,
        disable_registration=True,
        **kwargs,
    )
    try:
        async_client = build_async_client(tmpdir, **kwargs)

        assert sync_client._enricher.build(context) == async_client._enricher.build(
            context
        )
    finally:
        sync_client.destroy()


def test_async_client_uses_the_cache_it_was_given(tmpdir):
    cache = FileCache(APP_NAME, directory=str(tmpdir))

    client = build_async_client(tmpdir, url=URL, app_name=APP_NAME, cache=cache)

    assert client._cache is cache


def test_async_client_builds_a_feature_store_over_its_engine_and_cache(tmpdir):
    cache = FileCache(APP_NAME, directory=str(tmpdir))
    cache.set(FEATURES_URL, json.dumps(MOCK_FEATURE_RESPONSE))

    client = build_async_client(tmpdir, url=URL, app_name=APP_NAME, cache=cache)
    client._store.load_from_cache()

    assert client._engine.is_enabled("testFlag", {}).is_enabled


def test_both_clients_load_the_same_state(tmpdir):
    sync_cache = FileCache("sync", directory=str(tmpdir))
    async_cache = FileCache("async", directory=str(tmpdir))
    for cache in (sync_cache, async_cache):
        cache.set(FEATURES_URL, json.dumps(MOCK_FEATURE_RESPONSE))

    sync_client = UnleashClient(
        URL,
        APP_NAME,
        cache=sync_cache,
        disable_metrics=True,
        disable_registration=True,
    )
    try:
        async_client = build_async_client(
            tmpdir, url=URL, app_name=APP_NAME, cache=async_cache
        )

        sync_client._store.load_from_cache()
        async_client._store.load_from_cache()

        assert known_toggles(sync_client._engine) == known_toggles(async_client._engine)
        assert known_toggles(async_client._engine)
    finally:
        sync_client.destroy()


def test_async_client_builds_an_evaluator_over_its_engine_and_config(tmpdir):
    cache = FileCache(APP_NAME, directory=str(tmpdir))
    cache.set(FEATURES_URL, json.dumps(MOCK_FEATURE_RESPONSE))

    client = build_async_client(
        tmpdir, url=URL, app_name=APP_NAME, environment="unit", cache=cache
    )
    client._store.load_from_cache()

    assert client._evaluator.is_enabled("testFlag") is True
    assert (
        client._evaluator.get_variant("testVariations", {"userId": "2"}).variant["name"]
        == "VarA"
    )
    assert "testFlag" in client._evaluator.feature_definitions()


def test_the_async_clients_evaluator_enriches_over_its_own_config(tmpdir):
    client = build_async_client(tmpdir, url=URL, app_name=APP_NAME, environment="unit")

    def fallback(feature_name, context):
        return context["appName"] == APP_NAME and context["environment"] == "unit"

    assert client._evaluator.is_enabled("notAFlag", fallback_function=fallback) is True


def test_both_clients_evaluate_identically(tmpdir):
    sync_cache = FileCache("sync", directory=str(tmpdir))
    async_cache = FileCache("async", directory=str(tmpdir))
    for cache in (sync_cache, async_cache):
        cache.set(FEATURES_URL, json.dumps(MOCK_FEATURE_RESPONSE))

    sync_client = UnleashClient(
        URL,
        APP_NAME,
        cache=sync_cache,
        disable_metrics=True,
        disable_registration=True,
    )
    try:
        async_client = build_async_client(
            tmpdir, url=URL, app_name=APP_NAME, cache=async_cache
        )

        sync_client._store.load_from_cache()
        async_client._store.load_from_cache()

        context = {"userId": "2"}
        # testFlag2 is a 50% gradualRolloutRandom, so the two clients disagree
        # on it however identically they evaluate.
        for feature_name in (
            "testFlag",
            "testConstraintFlag",
            "testVariations",
            "notAFlag",
        ):
            assert sync_client._evaluator.is_enabled(feature_name, context) == (
                async_client._evaluator.is_enabled(feature_name, context)
            )
            assert sync_client._evaluator.get_variant(feature_name, context) == (
                async_client._evaluator.get_variant(feature_name, context)
            )

        assert sync_client._evaluator.feature_definitions() == (
            async_client._evaluator.feature_definitions()
        )
    finally:
        sync_client.destroy()


def test_the_async_client_gets_its_own_evaluator(tmpdir):
    sync_client = UnleashClient(
        URL, APP_NAME, disable_metrics=True, disable_registration=True
    )
    try:
        async_client = build_async_client(tmpdir, url=URL, app_name=APP_NAME)

        assert async_client._evaluator is not sync_client._evaluator
        assert async_client._evaluator._config is async_client._config
        assert async_client._evaluator._engine is async_client._engine
    finally:
        sync_client.destroy()


def test_async_client_exposes_impact_metrics(tmpdir):
    client = build_async_client(tmpdir, url=URL, app_name=APP_NAME)

    client.impact_metrics.define_counter("purchases", "Number of purchases")
    client.impact_metrics.increment_counter("purchases", 3)

    (collected,) = client._engine.collect_impact_metrics()
    assert collected["name"] == "purchases"


def test_both_clients_build_the_same_impact_metrics(tmpdir):
    kwargs = dict(url=URL, app_name=APP_NAME, environment="unit")

    sync_client = UnleashClient(
        cache=FileCache(APP_NAME, directory=str(tmpdir)),
        disable_metrics=True,
        disable_registration=True,
        **kwargs,
    )
    try:
        async_client = build_async_client(tmpdir, **kwargs)

        # Both label from config.impact_metrics_environment, which applies the header
        # override, rather than from `environment` directly.
        assert (
            async_client.impact_metrics._base_labels
            == sync_client.impact_metrics._base_labels
        )
    finally:
        sync_client.destroy()


def test_async_client_builds_a_metrics_reporter_over_its_own_collaborators(tmpdir):
    client = build_async_client(tmpdir, url=URL, app_name=APP_NAME)

    assert client._metrics._config is client._config
    assert client._metrics._transport is client._transport
    assert client._metrics._engine is client._engine
    assert client._metrics._impact_metrics is client.impact_metrics


def test_the_async_client_gets_the_async_reporter(tmpdir):
    # The flush runs on the client's event loop, so the requests-backed reporter would
    # block it for the length of every metrics POST.
    client = build_async_client(tmpdir, url=URL, app_name=APP_NAME)

    assert isinstance(client._metrics, _AsyncMetricsReporter)
    assert not isinstance(client._metrics, _MetricsReporter)


def duplicate_warnings(caplog) -> list:
    return [r.msg for r in caplog.records if "You already have" in str(r.msg)]


def test_a_second_async_client_on_the_same_config_warns(tmpdir, caplog):
    build_async_client(tmpdir, url=URL, app_name=APP_NAME)

    build_async_client(tmpdir, url=URL, app_name=APP_NAME)

    assert len(duplicate_warnings(caplog)) == 1
    assert "You already have 1 instance(s)" in duplicate_warnings(caplog)[0]


def test_a_second_async_client_on_the_same_config_can_be_blocked(tmpdir):
    build_async_client(
        tmpdir,
        url=URL,
        app_name=APP_NAME,
        multiple_instance_mode=InstanceAllowType.BLOCK,
    )

    with pytest.raises(
        MultipleInstancesNotAllowedError, match="You already have 1 instance"
    ):
        build_async_client(
            tmpdir,
            url=URL,
            app_name=APP_NAME,
            multiple_instance_mode=InstanceAllowType.BLOCK,
        )


def test_async_clients_on_different_configs_do_not_warn(tmpdir, caplog):
    build_async_client(tmpdir, url=URL, app_name=APP_NAME)

    build_async_client(tmpdir, url=URL, app_name=APP_NAME, instance_id="second")

    assert duplicate_warnings(caplog) == []


def test_the_two_flavors_share_one_registry(tmpdir, caplog):
    sync_client = UnleashClient(
        url=URL, app_name=APP_NAME, cache=FileCache(APP_NAME, directory=str(tmpdir))
    )
    try:
        build_async_client(tmpdir, url=URL, app_name=APP_NAME)

        assert len(duplicate_warnings(caplog)) == 1
    finally:
        sync_client.destroy()


def test_the_async_client_silently_allows_duplicates_on_request(tmpdir, caplog):
    build_async_client(tmpdir, url=URL, app_name=APP_NAME)

    build_async_client(
        tmpdir,
        url=URL,
        app_name=APP_NAME,
        multiple_instance_mode=InstanceAllowType.SILENTLY_ALLOW,
    )

    assert duplicate_warnings(caplog) == []


API_PREFIX = "/api"
FEATURES_PATH = API_PREFIX + FEATURES_URL
REGISTER_PATH = API_PREFIX + REGISTER_URL
METRICS_PATH = API_PREFIX + METRICS_URL


@pytest_asyncio.fixture
async def server():
    fake = FakeUnleash()
    await fake.start(API_PREFIX)
    fake.on("POST", REGISTER_PATH, status=202, repeat=True)
    fake.on("POST", METRICS_PATH, status=202, repeat=True)
    try:
        yield fake
    finally:
        await fake.close()


@pytest_asyncio.fixture
async def build_running_client(tmpdir, server: FakeUnleash):
    built = []

    def _build(**kwargs) -> AsyncUnleashClient:
        kwargs.setdefault("url", server.base_url)
        kwargs.setdefault("app_name", APP_NAME)
        kwargs.setdefault("request_retries", 0)
        kwargs.setdefault("disable_metrics", True)
        client = build_async_client(tmpdir, **kwargs)
        built.append(client)
        return client

    try:
        yield _build
    finally:
        for client in built:
            await client.destroy()


async def until(predicate: Callable[[], bool]) -> None:
    async def poll() -> None:
        while not predicate():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(poll(), WAIT_TIMEOUT)


@pytest.mark.asyncio
async def test_initializing_registers_with_the_server(server, build_running_client):
    client = build_running_client(refresh_interval=3600)

    await client.initialize_client()

    (registration,) = server.calls("POST", REGISTER_PATH)
    assert json.loads(registration.body)["appName"] == APP_NAME
    assert client.is_initialized


@pytest.mark.asyncio
async def test_initializing_does_not_register_when_registration_is_disabled(
    server, build_running_client
):
    client = build_running_client(refresh_interval=3600, disable_registration=True)

    await client.initialize_client()

    assert server.calls("POST", REGISTER_PATH) == []


@pytest.mark.asyncio
async def test_the_client_polls_features_from_the_server(server, build_running_client):
    server.on("GET", FEATURES_PATH, payload=MOCK_FEATURE_RESPONSE, repeat=True)
    client = build_running_client(refresh_interval=0.01)

    await client.initialize_client()

    await until(lambda: len(server.calls("GET", FEATURES_PATH)) >= 1)


@pytest.mark.asyncio
async def test_the_client_polls_even_when_asked_not_to_fetch_toggles(
    server, build_running_client
):
    server.on("GET", FEATURES_PATH, payload=MOCK_FEATURE_RESPONSE, repeat=True)
    client = build_running_client(refresh_interval=0.01)

    await client.initialize_client(fetch_toggles=False)

    await until(lambda: len(server.calls("GET", FEATURES_PATH)) >= 1)


@pytest.mark.asyncio
async def test_the_first_poll_ignores_a_previously_cached_etag(
    tmpdir, server, build_running_client
):
    server.on("GET", FEATURES_PATH, payload=MOCK_FEATURE_RESPONSE, repeat=True)
    cache = FileCache(APP_NAME, directory=str(tmpdir))
    cache.set(ETAG, "W/stale")
    client = build_running_client(refresh_interval=0.01, cache=cache)

    await client.initialize_client()

    await until(lambda: len(server.calls("GET", FEATURES_PATH)) >= 1)
    assert "If-None-Match" not in server.calls("GET", FEATURES_PATH)[0].headers


@pytest.mark.asyncio
async def test_initializing_twice_warns_and_registers_once(
    server, build_running_client
):
    client = build_running_client(refresh_interval=3600)
    await client.initialize_client()

    with pytest.warns(UserWarning, match="already been initialized"):
        await client.initialize_client()

    assert len(server.calls("POST", REGISTER_PATH)) == 1


@pytest.mark.asyncio
async def test_initializing_a_destroyed_client_warns_and_does_nothing(
    server, build_running_client
):
    client = build_running_client(refresh_interval=3600)
    await client.destroy()

    with pytest.warns(UserWarning, match="already been initialized"):
        await client.initialize_client()

    assert server.calls("POST", REGISTER_PATH) == []
    assert not client.is_initialized


@pytest.mark.asyncio
async def test_destroy_stops_polling(server, build_running_client):
    server.on("GET", FEATURES_PATH, payload=MOCK_FEATURE_RESPONSE, repeat=True)
    client = build_running_client(refresh_interval=0.01)
    await client.initialize_client()
    await until(lambda: len(server.calls("GET", FEATURES_PATH)) >= 1)

    await client.destroy()
    polls = len(server.calls("GET", FEATURES_PATH))
    await asyncio.sleep(0.05)

    assert len(server.calls("GET", FEATURES_PATH)) == polls
    assert not client.is_initialized


@pytest.mark.asyncio
async def test_destroy_sends_the_remaining_metrics(server, build_running_client):
    client = build_running_client(
        refresh_interval=3600, metrics_interval=3600, disable_metrics=False
    )
    await client.initialize_client()
    client.impact_metrics.define_counter("purchases", "Number of purchases")
    client.impact_metrics.increment_counter("purchases", 3)

    await client.destroy()

    (metrics,) = server.calls("POST", METRICS_PATH)
    (sent,) = json.loads(metrics.body)["impactMetrics"]
    assert sent["name"] == "purchases"


@pytest.mark.asyncio
async def test_destroy_can_be_called_more_than_once(server, build_running_client):
    client = build_running_client(refresh_interval=3600)
    await client.initialize_client()

    await client.destroy()
    await client.destroy()


@pytest.mark.asyncio
async def test_destroy_before_initializing_is_harmless(build_running_client):
    client = build_running_client()

    await client.destroy()


@pytest.mark.asyncio
async def test_destroy_during_registration_leaves_nothing_polling(
    server, build_running_client
):
    server.on("GET", FEATURES_PATH, payload=MOCK_FEATURE_RESPONSE, repeat=True)
    client = build_running_client(refresh_interval=0.01)
    client._transport.register = lambda payload: asyncio.sleep(0.05)

    initializing = asyncio.ensure_future(client.initialize_client())
    await asyncio.sleep(0)
    await client.destroy()
    await initializing
    await asyncio.sleep(0.05)

    assert server.calls("GET", FEATURES_PATH) == []
    assert not client.is_initialized


@pytest.mark.asyncio
async def test_the_context_manager_initializes_and_destroys(
    server, build_running_client
):
    server.on("GET", FEATURES_PATH, payload=MOCK_FEATURE_RESPONSE, repeat=True)
    client = build_running_client(refresh_interval=0.01)

    async with client as entered:
        assert entered is client
        await until(lambda: len(server.calls("GET", FEATURES_PATH)) >= 1)

    polls = len(server.calls("GET", FEATURES_PATH))
    await asyncio.sleep(0.05)
    assert len(server.calls("GET", FEATURES_PATH)) == polls
    assert len(server.calls("POST", REGISTER_PATH)) == 1


@pytest.mark.asyncio
async def test_is_enabled_resolves_toggles_from_the_cached_state(
    tmpdir, build_running_client
):
    cache = FileCache(APP_NAME, directory=str(tmpdir))
    cache.set(FEATURES_URL, json.dumps(MOCK_FEATURE_RESPONSE))
    client = build_running_client(refresh_interval=3600, cache=cache)

    await client.initialize_client()

    assert client.is_enabled("testFlag") is True
    assert client.is_enabled("testConstraintFlag") is False


@pytest.mark.asyncio
async def test_is_enabled_is_false_for_an_unknown_toggle(build_running_client):
    client = build_running_client(refresh_interval=3600)

    await client.initialize_client()

    assert client.is_enabled("notAFlag") is False


@pytest.mark.asyncio
async def test_is_enabled_answers_unknown_toggles_with_the_fallback(
    build_running_client,
):
    client = build_running_client(refresh_interval=3600)

    await client.initialize_client()

    assert (
        client.is_enabled(
            "notAFlag",
            {"userId": "42"},
            fallback_function=lambda feature_name, context: context["userId"] == "42",
        )
        is True
    )


@pytest.mark.asyncio
async def test_is_enabled_emits_impression_events(tmpdir, build_running_client):
    cache = FileCache(APP_NAME, directory=str(tmpdir))
    cache.set(FEATURES_URL, json.dumps(MOCK_FEATURE_RESPONSE))
    recorder = EventRecorder()
    client = build_running_client(
        refresh_interval=3600, cache=cache, event_callback=recorder
    )

    await client.initialize_client()
    client.is_enabled("testFlag", {"userId": "42"})

    (event,) = recorder.wait_for(UnleashEventType.FEATURE_FLAG)
    assert event.feature_name == "testFlag"
    assert event.enabled is True
    assert event.context["userId"] == "42"


@pytest.mark.asyncio
async def test_get_variant_resolves_variants_from_the_cached_state(
    tmpdir, build_running_client
):
    cache = FileCache(APP_NAME, directory=str(tmpdir))
    cache.set(FEATURES_URL, json.dumps(MOCK_FEATURE_RESPONSE))
    client = build_running_client(refresh_interval=3600, cache=cache)

    await client.initialize_client()

    variant = client.get_variant("testVariations", {"userId": "2"})
    assert variant["name"] == "VarA"
    assert variant["enabled"]
    assert variant["feature_enabled"]


@pytest.mark.asyncio
async def test_get_variant_is_disabled_for_an_unknown_toggle(build_running_client):
    client = build_running_client(refresh_interval=3600)

    await client.initialize_client()

    variant = client.get_variant("notAFlag")
    assert variant["name"] == "disabled"
    assert not variant["enabled"]
    assert not variant["feature_enabled"]


@pytest.mark.asyncio
async def test_get_variant_emits_impression_events(tmpdir, build_running_client):
    cache = FileCache(APP_NAME, directory=str(tmpdir))
    cache.set(FEATURES_URL, json.dumps(MOCK_FEATURE_RESPONSE))
    recorder = EventRecorder()
    client = build_running_client(
        refresh_interval=3600, cache=cache, event_callback=recorder
    )

    await client.initialize_client()
    client.get_variant("testVariations", {"userId": "2"})

    (event,) = recorder.wait_for(UnleashEventType.VARIANT)
    assert event.feature_name == "testVariations"
    assert event.enabled is True
    assert event.variant == "VarA"
    assert event.context["userId"] == "2"


@pytest.mark.asyncio
async def test_feature_definitions_reports_the_toggles_in_the_cached_state(
    tmpdir, build_running_client
):
    cache = FileCache(APP_NAME, directory=str(tmpdir))
    cache.set(FEATURES_URL, json.dumps(MOCK_FEATURE_RESPONSE_PROJECT))
    client = build_running_client(refresh_interval=3600, cache=cache)

    await client.initialize_client()

    assert client.feature_definitions() == {
        "ivan-project": {"type": "release", "project": "default"}
    }


@pytest.mark.asyncio
async def test_feature_definitions_is_empty_without_any_state(build_running_client):
    client = build_running_client(refresh_interval=3600)

    await client.initialize_client()

    assert client.feature_definitions() == {}
