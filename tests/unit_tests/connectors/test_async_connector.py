import asyncio
import json
from typing import Callable

import pytest_asyncio
from pytest import mark
from yggdrasil_engine.engine import UnleashEngine

from tests.utilities.events import WAIT_TIMEOUT, EventRecorder
from tests.utilities.fake_unleash_server import FakeUnleash
from tests.utilities.mocks.mock_features import MOCK_FEATURE_RESPONSE
from tests.utilities.testing_constants import APP_NAME, ETAG_VALUE
from UnleashClient.async_transport import AsyncTransport
from UnleashClient.config import UnleashConfig
from UnleashClient.connectors.async_connector import AsyncPollingConnector
from UnleashClient.constants import ETAG, FEATURES_URL
from UnleashClient.events import EventDispatcher, UnleashEventType
from UnleashClient.headers import HeaderFactory
from UnleashClient.store import FeatureStore

API_PREFIX = "/api"
FEATURES_PATH = API_PREFIX + FEATURES_URL

INTERVAL = 0.01
NEVER = 3600


@pytest_asyncio.fixture
async def server():
    fake = FakeUnleash()
    await fake.start(API_PREFIX)
    try:
        yield fake
    finally:
        await fake.close()


@pytest_asyncio.fixture
async def build_connector(server: FakeUnleash):
    built = []

    def _build_connector(
        store: FeatureStore, refresh_interval: float = INTERVAL
    ) -> AsyncPollingConnector:
        config = UnleashConfig(server.base_url, APP_NAME, request_retries=0)
        transport = AsyncTransport(config, HeaderFactory(config))
        connector = AsyncPollingConnector(
            store=store, transport=transport, refresh_interval=refresh_interval
        )
        built.append((connector, transport))
        return connector

    try:
        yield _build_connector
    finally:
        for connector, transport in built:
            await connector.stop()
            await transport.aclose()


async def until(predicate: Callable[[], bool]) -> None:
    async def poll() -> None:
        while not predicate():
            await asyncio.sleep(INTERVAL)

    await asyncio.wait_for(poll(), WAIT_TIMEOUT)


def is_enabled(engine: UnleashEngine, flag: str) -> bool:
    return bool(engine.is_enabled(flag, {}).is_enabled)


@mark.asyncio
async def test_start_makes_cached_state_evaluable_before_any_fetch(
    server, build_connector, cache_empty
):
    cache_empty.set(FEATURES_URL, json.dumps(MOCK_FEATURE_RESPONSE))
    engine = UnleashEngine()
    connector = build_connector(
        store=FeatureStore(engine=engine, cache=cache_empty), refresh_interval=NEVER
    )

    await connector.start()

    assert is_enabled(engine, "testFlag")
    assert server.calls("GET", FEATURES_PATH) == []


@mark.asyncio
async def test_polling_applies_fetched_state_and_caches_its_etag(
    server, build_connector, cache_empty
):
    server.on(
        "GET",
        FEATURES_PATH,
        payload=MOCK_FEATURE_RESPONSE,
        headers={"etag": ETAG_VALUE},
        repeat=True,
    )
    engine = UnleashEngine()
    connector = build_connector(store=FeatureStore(engine=engine, cache=cache_empty))

    await connector.start()

    await until(lambda: is_enabled(engine, "testFlag"))
    assert cache_empty.get(ETAG) == ETAG_VALUE


@mark.asyncio
async def test_polling_sends_the_cached_etag(server, build_connector, cache_empty):
    server.on(
        "GET",
        FEATURES_PATH,
        payload=MOCK_FEATURE_RESPONSE,
        headers={"etag": ETAG_VALUE},
    )
    server.on("GET", FEATURES_PATH, status=304, repeat=True)
    connector = build_connector(
        store=FeatureStore(engine=UnleashEngine(), cache=cache_empty)
    )

    await connector.start()

    await until(lambda: len(server.calls("GET", FEATURES_PATH)) >= 2)
    first, second = server.calls("GET", FEATURES_PATH)[:2]
    assert "If-None-Match" not in first.headers
    assert second.headers["If-None-Match"] == ETAG_VALUE


@mark.asyncio
async def test_failed_poll_keeps_the_last_applied_state(
    server, build_connector, cache_empty
):
    server.on("GET", FEATURES_PATH, payload=MOCK_FEATURE_RESPONSE)
    server.on("GET", FEATURES_PATH, status=500, repeat=True)
    engine = UnleashEngine()
    connector = build_connector(store=FeatureStore(engine=engine, cache=cache_empty))

    await connector.start()

    await until(lambda: len(server.calls("GET", FEATURES_PATH)) >= 3)
    assert is_enabled(engine, "testFlag")


@mark.asyncio
async def test_polling_emits_fetched_on_every_fetch_and_ready_once(
    server,
    build_connector,
    cache_empty,
    dispatcher: EventDispatcher,
    recorder: EventRecorder,
):
    server.on("GET", FEATURES_PATH, payload=MOCK_FEATURE_RESPONSE, repeat=True)
    connector = build_connector(
        store=FeatureStore(engine=UnleashEngine(), cache=cache_empty, events=dispatcher)
    )

    await connector.start()
    await until(lambda: len(recorder.of_type(UnleashEventType.FETCHED)) >= 2)
    await connector.stop()
    dispatcher.close(timeout=WAIT_TIMEOUT)

    assert len(recorder.of_type(UnleashEventType.READY)) == 1


@mark.asyncio
async def test_stop_interrupts_a_fetch_in_flight(server, build_connector, cache_empty):
    server.on("GET", FEATURES_PATH, payload=MOCK_FEATURE_RESPONSE, hang=True)
    engine = UnleashEngine()
    connector = build_connector(store=FeatureStore(engine=engine, cache=cache_empty))

    await connector.start()
    await until(lambda: len(server.calls("GET", FEATURES_PATH)) == 1)
    await asyncio.wait_for(connector.stop(), WAIT_TIMEOUT)
    await server.close()

    assert not is_enabled(engine, "testFlag")
    assert len(server.calls("GET", FEATURES_PATH)) == 1


@mark.asyncio
async def test_stop_is_safe_when_never_started(build_connector, cache_empty):
    connector = build_connector(
        store=FeatureStore(engine=UnleashEngine(), cache=cache_empty)
    )

    await connector.stop()
