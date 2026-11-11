import functools
import json

import aiohttp
import pytest
import pytest_asyncio
from pytest import mark

from tests.utilities.fake_unleash_server import FakeUnleash
from tests.utilities.testing_constants import APP_NAME, ETAG_VALUE, URL
from UnleashClient import INSTANCES, AiohttpTransport, Method, Request, Response
from UnleashClient.clients.async_unleash_client import AsyncUnleashClient
from UnleashClient.config import HttpOptions, MetricsOptions, PollingOptions
from UnleashClient.constants import FEATURES_URL, METRICS_URL, REGISTER_URL
from UnleashClient.utils import InstanceAllowType

API_PREFIX = "/api"
FEATURES = {
    "version": 1,
    "features": [
        {
            "name": "testFlag",
            "enabled": True,
            "strategies": [{"name": "default", "parameters": {}}],
        }
    ],
}


@pytest.fixture(autouse=True)
def before_each():
    INSTANCES._reset()


def build_client(tmp_path, transport, url=URL, **kwargs) -> AsyncUnleashClient:
    kwargs.setdefault("mode", PollingOptions(interval=3600))
    return AsyncUnleashClient(
        url,
        APP_NAME,
        api_key="project:environment.hash",
        cache_directory=str(tmp_path),
        transport=transport,
        **kwargs,
    )


class FakeAsyncTransport:
    def __init__(self, headers=None) -> None:
        self._headers = headers or {}
        self.requests = []

    async def execute(self, request: Request) -> Response:
        self.requests.append(request)
        if request.method == "GET":
            body = json.dumps(FEATURES).encode()
            return Response(status=200, headers=self._headers, body=body)
        return Response(status=202, headers={}, body=b"")


@mark.asyncio
async def test_the_client_sends_every_request_through_the_transport(tmp_path):
    transport = FakeAsyncTransport()

    async with build_client(tmp_path, transport) as client:
        assert client.is_enabled("testFlag")

    sent = [(request.method, request.url) for request in transport.requests]
    assert ("POST", URL + REGISTER_URL) in sent
    assert ("GET", URL + FEATURES_URL) in sent
    # the final metrics send on destroy()
    assert ("POST", URL + METRICS_URL) in sent
    assert all(
        request.headers["Authorization"] == "project:environment.hash"
        for request in transport.requests
    )


@mark.asyncio
async def test_an_etag_in_a_plain_dict_is_sent_back_on_the_next_fetch(tmp_path):
    transport = FakeAsyncTransport(headers={"ETag": ETAG_VALUE})

    async with build_client(
        tmp_path,
        transport,
        metrics=MetricsOptions(disabled=True, disable_registration=True),
    ) as client:
        await client._connector._fetch_and_load()

    first, second = transport.requests
    assert "If-None-Match" not in first.headers
    assert second.headers["If-None-Match"] == ETAG_VALUE


@pytest_asyncio.fixture
async def server():
    fake = FakeUnleash()
    await fake.start(API_PREFIX)
    fake.on("GET", API_PREFIX + FEATURES_URL, payload=FEATURES, repeat=True)
    try:
        yield fake
    finally:
        await fake.close()


@mark.asyncio
async def test_the_client_never_closes_a_session_passed_in(tmp_path, server):
    async with aiohttp.ClientSession() as session:
        async with build_client(
            tmp_path,
            AiohttpTransport(session),
            url=server.base_url,
            metrics=MetricsOptions(disabled=True, disable_registration=True),
        ) as client:
            assert client.is_enabled("testFlag")

        assert not session.closed


@mark.asyncio
async def test_the_client_never_closes_a_transport_passed_in(tmp_path, server):
    transport = AiohttpTransport()

    async with build_client(
        tmp_path,
        transport,
        url=server.base_url,
        metrics=MetricsOptions(disabled=True, disable_registration=True),
    ):
        pass

    try:
        response = await transport.execute(
            Request(method=Method.GET, url=server.base_url + FEATURES_URL, headers={})
        )
    finally:
        await transport.aclose()
    assert response.status == 200


@mark.asyncio
async def test_a_session_closed_too_early_is_a_failed_fetch(tmp_path, server):
    session = aiohttp.ClientSession()
    await session.close()

    async with build_client(
        tmp_path,
        AiohttpTransport(session),
        url=server.base_url,
        metrics=MetricsOptions(disabled=True, disable_registration=True),
    ) as client:
        assert not client.is_enabled("testFlag")

    assert server.requests == []


def test_http_and_transport_together_raise(tmp_path):
    with pytest.raises(ValueError, match="either http or transport"):
        build_client(tmp_path, FakeAsyncTransport(), http=HttpOptions(timeout=5))


class SyncTransport:
    def execute(self, request):
        raise AssertionError("never sent")


@mark.asyncio
@pytest.mark.parametrize(
    "make_transport,message",
    (
        (aiohttp.ClientSession, "AiohttpTransport\\(session\\)"),
        (object, "execute"),
        (SyncTransport, "not async"),
    ),
    ids=("a-bare-session", "no-execute", "sync-execute"),
)
async def test_a_transport_that_cannot_work_raises(tmp_path, make_transport, message):
    transport = make_transport()
    try:
        with pytest.raises(TypeError, match=message):
            build_client(tmp_path, transport)
    finally:
        if isinstance(transport, aiohttp.ClientSession):
            await transport.close()


def traced(execute):
    """A sync decorator, like a tracing one, that returns the coroutine."""

    @functools.wraps(execute)
    def wrapper(self, request):
        return execute(self, request)

    return wrapper


def run_async(execute):
    """An async decorator around a sync method."""

    @functools.wraps(execute)
    async def wrapper(self, request):
        return execute(self, request)

    return wrapper


class TracedTransport(FakeAsyncTransport):
    @traced
    async def execute(self, request: Request) -> Response:
        return await super().execute(request)


class SyncMadeAsyncTransport(FakeAsyncTransport):
    @run_async
    def execute(self, request: Request) -> Response:
        self.requests.append(request)
        body = json.dumps(FEATURES).encode()
        return Response(status=200, headers={}, body=body)


@mark.asyncio
@pytest.mark.parametrize(
    "make_transport",
    (TracedTransport, SyncMadeAsyncTransport),
    ids=("sync-decorator-on-async-execute", "async-decorator-on-sync-execute"),
)
async def test_a_decorated_async_execute_is_accepted(tmp_path, make_transport):
    transport = make_transport()

    async with build_client(
        tmp_path,
        transport,
        metrics=MetricsOptions(disabled=True, disable_registration=True),
    ) as client:
        assert client.is_enabled("testFlag")

    assert transport.requests


def test_a_rejected_transport_does_not_register_the_instance(tmp_path):
    with pytest.raises(ValueError):
        build_client(tmp_path, FakeAsyncTransport(), http=HttpOptions())

    # BLOCK would raise if the rejected client had been registered
    build_client(
        tmp_path,
        FakeAsyncTransport(),
        multiple_instance_mode=InstanceAllowType.BLOCK,
    )


# the examples in examples/


@mark.asyncio
async def test_the_fake_async_transport_example_works(tmp_path):
    from examples import fake_async_transport  # noqa: PLC0415

    await fake_async_transport.test_new_checkout_is_on(tmp_path)


@mark.asyncio
async def test_the_httpx_async_example_works(tmp_path):
    httpx = pytest.importorskip("httpx")
    from examples.httpx_async_transport import HttpxAsyncTransport  # noqa: PLC0415

    sent = []

    def server(request):
        sent.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=FEATURES, headers={"ETag": ETAG_VALUE})
        return httpx.Response(202)

    async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as http_client:
        async with build_client(
            tmp_path,
            HttpxAsyncTransport(http_client),
            mode=PollingOptions(interval=3600, project_name="checkout"),
        ) as client:
            assert client.is_enabled("testFlag")
            await client._connector._fetch_and_load()

    register = next(r for r in sent if r.url.path.endswith("/register"))
    assert json.loads(register.content)["appName"] == APP_NAME
    fetches = [r for r in sent if r.method == "GET"]
    assert fetches[0].url.params["project"] == "checkout"
    assert fetches[1].headers["If-None-Match"] == ETAG_VALUE
