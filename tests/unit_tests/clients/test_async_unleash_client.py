import json
from dataclasses import asdict

import pytest

from tests.utilities.mocks.mock_features import MOCK_FEATURE_RESPONSE
from tests.utilities.testing_constants import APP_NAME, URL
from UnleashClient import INSTANCES, UnleashClient
from UnleashClient.cache import FileCache
from UnleashClient.clients.async_unleash_client import AsyncUnleashClient
from UnleashClient.constants import FEATURES_URL


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


def test_both_clients_build_the_same_kind_of_scheduler(tmpdir):
    sync_client = UnleashClient(
        URL, APP_NAME, disable_metrics=True, disable_registration=True
    )
    try:
        async_client = build_async_client(tmpdir, url=URL, app_name=APP_NAME)

        assert type(async_client._scheduler) is type(sync_client._scheduler)
    finally:
        sync_client.destroy()


def test_the_async_client_gets_its_own_scheduler(tmpdir):
    sync_client = UnleashClient(
        URL, APP_NAME, disable_metrics=True, disable_registration=True
    )
    try:
        async_client = build_async_client(tmpdir, url=URL, app_name=APP_NAME)

        assert async_client._scheduler is not sync_client._scheduler
        assert async_client._scheduler.scheduler is not sync_client._scheduler.scheduler
        assert (
            async_client._scheduler.executor_name
            != sync_client._scheduler.executor_name
        )
    finally:
        sync_client.destroy()


def test_the_async_client_can_register_and_cancel_a_job(tmpdir):
    client = build_async_client(tmpdir, url=URL, app_name=APP_NAME)

    job = client._scheduler.every(
        interval_seconds=15, jitter_seconds=None, fn=client._store.load_from_cache
    )
    client._scheduler.cancel(job)

    assert job is not None
    assert client._scheduler.scheduler.get_jobs() == []


def test_constructing_the_async_client_does_not_start_the_scheduler(tmpdir):
    # No event loop is running here, and none is needed: the scheduler is built in
    # __init__ but only started by initialize_client().
    client = build_async_client(tmpdir, url=URL, app_name=APP_NAME)

    assert not client._scheduler.scheduler.running


def test_async_client_builds_a_transport_over_its_config_and_headers(tmpdir):
    client = build_async_client(tmpdir, url=URL, app_name=APP_NAME)

    assert client._transport._config is client._config
    assert client._transport._headers is client._headers


def test_constructing_the_async_client_opens_no_session(tmpdir):
    # No event loop is running here, and none is needed: aiohttp resolves the
    # loop when a ClientSession is built, so the transport has to defer that to
    # the first request.
    client = build_async_client(tmpdir, url=URL, app_name=APP_NAME)

    assert client._transport._session is None
