from dataclasses import asdict

import pytest

from tests.utilities.testing_constants import APP_NAME, URL
from UnleashClient import INSTANCES, UnleashClient
from UnleashClient.cache import FileCache
from UnleashClient.clients.async_unleash_client import AsyncUnleashClient


@pytest.fixture(autouse=True)
def before_each():
    INSTANCES._reset()


def test_async_client_builds_the_shared_config():
    client = AsyncUnleashClient("http://localhost:4242/api/", APP_NAME)

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
        async_client = AsyncUnleashClient(**kwargs)

        sync_config = asdict(sync_client._config)
        async_config = asdict(async_client._config)
        sync_config.pop("connection_id")
        async_config.pop("connection_id")

        assert sync_config == async_config
    finally:
        sync_client.destroy()


def test_async_client_enriches_context_over_its_own_config():
    client = AsyncUnleashClient(URL, APP_NAME, environment="unit")

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
        async_client = AsyncUnleashClient(**kwargs)

        assert sync_client._enricher.build(context) == async_client._enricher.build(
            context
        )
    finally:
        sync_client.destroy()
