import asyncio
import json
from typing import Callable

import aiohttp
import pytest
import pytest_asyncio
from pytest import mark, param

from tests.utilities.fake_unleash_server import FakeUnleash
from tests.utilities.mocks.mock_features import (
    MOCK_FEATURE_RESPONSE,
    MOCK_FEATURE_RESPONSE_PROJECT,
)
from tests.utilities.mocks.mock_metrics import MOCK_METRICS_REQUEST
from tests.utilities.testing_constants import (
    APP_NAME,
    ETAG_VALUE,
    INSTANCE_ID,
    PROJECT_NAME,
    URL,
)
from UnleashClient._aiohttp_transport import AiohttpTransport
from UnleashClient._async_unleash_api_client import _AsyncUnleashApiClient
from UnleashClient._headers import _HeaderFactory
from UnleashClient.config import (
    IdentityOptions,
    MetricsOptions,
    PollingOptions,
    UnleashConfig,
)
from UnleashClient.constants import (
    CLIENT_SPEC_VERSION,
    FEATURES_URL,
    METRICS_URL,
    REGISTER_URL,
)
from UnleashClient.errors import AlreadyClosedError
from UnleashClient.events import FetchStatus, UnleashEventType
from UnleashClient.transport import Method, Request, Response

API_PREFIX = "/api"
FEATURES_PATH = API_PREFIX + FEATURES_URL
REGISTER_PATH = API_PREFIX + REGISTER_URL
METRICS_PATH = API_PREFIX + METRICS_URL


@pytest_asyncio.fixture
async def server():
    """A real Unleash server on an ephemeral port, stopped on teardown."""
    fake = FakeUnleash()
    await fake.start(API_PREFIX)
    try:
        yield fake
    finally:
        await fake.close()


@pytest_asyncio.fixture
async def build_api_client(server: FakeUnleash):
    """
    Factory pointed at the fake server. Keyword arguments override the defaults
    on the config. Every API client it builds is closed on teardown.
    """
    built = []

    def _build_api_client(events=None, **kwargs) -> _AsyncUnleashApiClient:
        defaults = {
            "url": server.base_url,
            "app_name": APP_NAME,
            "identity": IdentityOptions(instance_id=INSTANCE_ID),
        }
        defaults.update(kwargs)
        config = UnleashConfig(**defaults)
        api_client = _AsyncUnleashApiClient(config, _HeaderFactory(config), events)
        built.append(api_client)
        return api_client

    try:
        yield _build_api_client
    finally:
        for api_client in built:
            await api_client.aclose()


@pytest_asyncio.fixture
async def api_client(
    build_api_client: Callable[..., _AsyncUnleashApiClient],
) -> _AsyncUnleashApiClient:
    """The API client the tests that need no config override share."""
    return build_api_client()


@mark.asyncio
@mark.parametrize(
    "response,status,call_count,expected",
    (
        param(
            MOCK_FEATURE_RESPONSE,
            200,
            1,
            lambda result: json.loads(result)["version"] == 1,
            id="success",
        ),
        param(MOCK_FEATURE_RESPONSE, 202, 1, lambda result: not result, id="failure"),
        param({}, 500, 4, lambda result: not result, id="failure"),
    ),
)
async def test_fetch_features(
    server, api_client, response, status, call_count, expected
):
    server.on(
        "GET",
        FEATURES_PATH,
        status=status,
        payload=response,
        headers={"etag": ETAG_VALUE},
        repeat=True,
    )

    result = await api_client.fetch_features(options=PollingOptions())

    assert len(server.calls("GET", FEATURES_PATH)) == call_count
    assert expected(result.raw_state)


@mark.asyncio
async def test_fetch_features_sends_the_project_as_a_query_parameter(
    server, build_api_client
):
    api_client = build_api_client()
    server.on(
        "GET",
        FEATURES_PATH,
        status=200,
        payload=MOCK_FEATURE_RESPONSE_PROJECT,
        headers={"etag": ETAG_VALUE},
    )

    result = await api_client.fetch_features(
        options=PollingOptions(project_name=PROJECT_NAME)
    )

    calls = server.calls("GET", FEATURES_PATH)
    assert len(calls) == 1
    assert calls[0].query == {"project": PROJECT_NAME}
    assert len(json.loads(result.raw_state)["features"]) == 1
    assert result.etag == ETAG_VALUE


@mark.asyncio
async def test_fetch_features_drops_the_etag_on_failure(server, build_api_client):
    api_client = build_api_client()
    server.on(
        "GET",
        FEATURES_PATH,
        status=500,
        payload={},
        headers={"etag": ETAG_VALUE},
        repeat=True,
    )

    result = await api_client.fetch_features(
        options=PollingOptions(project_name=PROJECT_NAME)
    )

    assert len(server.calls("GET", FEATURES_PATH)) == 4
    assert not result.etag
    assert result.not_modified is False


@mark.asyncio
async def test_fetch_features_sends_if_none_match_when_an_etag_is_known(
    server, build_api_client
):
    api_client = build_api_client()
    server.on("GET", FEATURES_PATH, status=304, headers={"etag": ETAG_VALUE})

    result = await api_client.fetch_features(
        ETAG_VALUE, options=PollingOptions(project_name=PROJECT_NAME)
    )

    calls = server.calls("GET", FEATURES_PATH)
    assert len(calls) == 1
    assert calls[0].headers["If-None-Match"] == ETAG_VALUE
    assert result.raw_state is None
    assert result.etag == ETAG_VALUE
    assert result.not_modified is True


@mark.asyncio
async def test_fetch_features_retries_and_recovers(server, build_api_client):
    api_client = build_api_client()
    server.on("GET", FEATURES_PATH, status=500, payload={})
    server.on(
        "GET",
        FEATURES_PATH,
        status=200,
        payload=MOCK_FEATURE_RESPONSE_PROJECT,
        headers={"etag": ETAG_VALUE},
    )

    result = await api_client.fetch_features(
        ETAG_VALUE, options=PollingOptions(project_name=PROJECT_NAME)
    )

    assert len(server.calls("GET", FEATURES_PATH)) == 2
    assert len(json.loads(result.raw_state)["features"]) == 1
    assert result.etag == ETAG_VALUE


@mark.asyncio
async def test_fetch_features_retries_and_recovers_from_a_connection_error(
    server, build_api_client
):
    api_client = build_api_client()
    server.on("GET", FEATURES_PATH, disconnect=True)
    server.on(
        "GET",
        FEATURES_PATH,
        status=200,
        payload=MOCK_FEATURE_RESPONSE_PROJECT,
        headers={"etag": ETAG_VALUE},
    )

    result = await api_client.fetch_features(
        ETAG_VALUE, options=PollingOptions(project_name=PROJECT_NAME)
    )

    assert len(server.calls("GET", FEATURES_PATH)) == 2
    assert len(json.loads(result.raw_state)["features"]) == 1


@mark.asyncio
@mark.parametrize(
    "reply,expected",
    (
        param({"status": 202, "payload": {}}, True, id="success"),
        param({"status": 200, "payload": {}}, True, id="success-200"),
        param({"status": 500, "payload": {}}, False, id="failure"),
        param({"disconnect": True}, False, id="connection-error"),
    ),
)
async def test_register(server, api_client, reply, expected):
    server.on("POST", REGISTER_PATH, **reply)

    result = await api_client.register({"appName": APP_NAME})

    assert len(server.calls("POST", REGISTER_PATH)) == 1
    assert result is expected


@mark.asyncio
async def test_register_sends_the_payload_it_is_given(server, api_client):
    server.on("POST", REGISTER_PATH, status=202, payload={})

    await api_client.register({"appName": APP_NAME, "strategies": []})

    body = server.calls("POST", REGISTER_PATH)[0].body
    assert json.loads(body) == {"appName": APP_NAME, "strategies": []}


@pytest.fixture
def skip_url_validation(monkeypatch):
    """
    UnleashConfig rejects these urls on construction, so register() only sees
    one that slipped past that check. Skip it to reach aiohttp's own error.
    """
    monkeypatch.setattr("UnleashClient.config._validate_url", lambda url: None)


@mark.asyncio
@mark.usefixtures("skip_url_validation")
@mark.parametrize(
    "url", ("thisisnotavalidurl", "localhost:4242/api"), ids=("no-scheme", "bad-scheme")
)
async def test_register_reports_a_url_aiohttp_rejects_as_a_failure(
    server, build_api_client, url
):
    assert await build_api_client(url=url).register({}) is False

    assert server.requests == []


@mark.asyncio
@mark.parametrize(
    "reply,expected",
    (
        param({"status": 202, "payload": {}}, True, id="success"),
        param({"status": 200, "payload": {}}, False, id="200-is-a-failure"),
        param({"status": 500, "payload": {}}, False, id="failure"),
        param({"disconnect": True}, False, id="connection-error"),
    ),
)
async def test_send_metrics(server, api_client, reply, expected):
    server.on("POST", METRICS_PATH, **reply)

    result = await api_client.send_metrics(MOCK_METRICS_REQUEST)

    calls = server.calls("POST", METRICS_PATH)
    assert len(calls) == 1
    assert result is expected

    body = json.loads(calls[0].body)
    assert body["connectionId"] == MOCK_METRICS_REQUEST.get("connectionId")


@mark.asyncio
async def test_send_metrics_returns_false_when_the_request_times_out(
    server, build_api_client
):
    config = UnleashConfig(server.base_url, APP_NAME)
    transport = AiohttpTransport(timeout=0.1)
    api_client = _AsyncUnleashApiClient(
        config, _HeaderFactory(config), transport=transport
    )
    server.on("POST", METRICS_PATH, hang=True)

    try:
        result = await api_client.send_metrics(MOCK_METRICS_REQUEST)
    finally:
        await transport.aclose()

    assert len(server.calls("POST", METRICS_PATH)) == 1
    assert result is False


@mark.asyncio
async def test_send_metrics_raises_when_cancelled(server, api_client):
    server.on("POST", METRICS_PATH, hang=True)
    send = asyncio.create_task(api_client.send_metrics(MOCK_METRICS_REQUEST))
    while not server.calls("POST", METRICS_PATH):
        await asyncio.sleep(0.01)

    send.cancel()

    with pytest.raises(asyncio.CancelledError):
        await send


@mark.asyncio
async def test_every_endpoint_gets_its_headers_from_the_factory(
    server, build_api_client
):
    api_client = build_api_client(metrics=MetricsOptions(interval=2))
    server.on("GET", FEATURES_PATH, status=200, payload=MOCK_FEATURE_RESPONSE)
    server.on("POST", REGISTER_PATH, status=202, payload={})
    server.on("POST", METRICS_PATH, status=202, payload={})

    await api_client.fetch_features(options=PollingOptions(interval=1))
    await api_client.register({})
    await api_client.send_metrics(MOCK_METRICS_REQUEST)

    fetch = server.calls("GET", FEATURES_PATH)[0].headers
    register = server.calls("POST", REGISTER_PATH)[0].headers
    metrics = server.calls("POST", METRICS_PATH)[0].headers
    for headers in (fetch, register, metrics):
        assert headers["unleash-appname"] == APP_NAME
        assert headers["Unleash-Client-Spec"] == CLIENT_SPEC_VERSION
    assert fetch["unleash-interval"] == "1000"
    assert "unleash-interval" not in register
    assert metrics["unleash-interval"] == "2000"


@mark.asyncio
async def test_the_session_is_reused_across_requests(server, api_client):
    server.on("POST", METRICS_PATH, status=202, payload={}, repeat=True)

    await api_client.send_metrics(MOCK_METRICS_REQUEST)
    first = api_client._transport._session
    await api_client.send_metrics(MOCK_METRICS_REQUEST)

    assert first is not None
    assert api_client._transport._session is first


@mark.asyncio
@mark.parametrize(
    "call",
    (
        param(
            lambda api_client: api_client.fetch_features(options=PollingOptions()),
            id="fetch_features",
        ),
        param(lambda api_client: api_client.register({}), id="register"),
        param(
            lambda api_client: api_client.send_metrics(MOCK_METRICS_REQUEST),
            id="send_metrics",
        ),
    ),
)
async def test_a_closed_api_client_refuses_every_request(server, api_client, call):
    await api_client.aclose()

    with pytest.raises(AlreadyClosedError):
        await call(api_client)

    assert server.requests == []


@mark.asyncio
async def test_closing_a_closed_api_client_does_nothing(api_client):
    await api_client.aclose()
    await api_client.aclose()


class RecordingEvents:
    """Stands in for the dispatcher, keeping emitted events in order."""

    def __init__(self):
        self.events = []

    def emit_event(self, event):
        self.events.append(event)


def fetch_outcomes(events: RecordingEvents):
    return [
        event.status
        for event in events.events
        if event.event_type == UnleashEventType.FETCH_COMPLETED
    ]


@mark.asyncio
@mark.parametrize(
    "status,payload,expected",
    (
        param(200, MOCK_FEATURE_RESPONSE, FetchStatus.CHANGED, id="changed"),
        param(304, None, FetchStatus.NOT_CHANGED, id="not-changed"),
        param(401, {}, FetchStatus.UNAUTHORIZED, id="unknown-token"),
        param(403, {}, FetchStatus.UNAUTHORIZED, id="wrong-token-type"),
        param(429, {}, FetchStatus.RATE_LIMITED, id="rate-limited"),
        param(500, {}, FetchStatus.UNAVAILABLE, id="server-error-after-retries"),
        param(503, {}, FetchStatus.UNAVAILABLE, id="server-unavailable"),
        param(
            202, MOCK_FEATURE_RESPONSE, FetchStatus.INVALID_RESPONSE, id="unexpected"
        ),
        param(200, None, FetchStatus.INVALID_RESPONSE, id="empty-200"),
    ),
)
async def test_fetch_features_reports_how_the_fetch_ended(
    server, build_api_client, status, payload, expected
):
    server.on("GET", FEATURES_PATH, status=status, payload=payload, repeat=True)
    events = RecordingEvents()

    await build_api_client(events=events).fetch_features(options=PollingOptions())

    assert fetch_outcomes(events) == [expected]


@mark.asyncio
async def test_fetch_features_reports_unavailable_when_no_response_arrives(
    server, build_api_client
):
    server.on("GET", FEATURES_PATH, disconnect=True, repeat=True)
    events = RecordingEvents()

    await build_api_client(events=events).fetch_features(options=PollingOptions())

    assert fetch_outcomes(events) == [FetchStatus.UNAVAILABLE]


@mark.asyncio
async def test_fetch_features_reports_unavailable_when_the_body_times_out(
    server, build_api_client, monkeypatch
):
    # A 200 status line arrives but its body never does. That is the server
    # being unreachable, not a bad response.
    server.on("GET", FEATURES_PATH, payload=MOCK_FEATURE_RESPONSE, repeat=True)

    async def body_times_out(_response):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(aiohttp.ClientResponse, "read", body_times_out)
    events = RecordingEvents()

    await build_api_client(events=events).fetch_features(options=PollingOptions())

    assert fetch_outcomes(events) == [FetchStatus.UNAVAILABLE]


class RecordingTransport:
    """Records every request and answers each with the same response."""

    def __init__(self, response: Response):
        self.response = response
        self.requests = []
        self.closed = False

    async def execute(self, request: Request) -> Response:
        self.requests.append(request)
        return self.response

    async def aclose(self) -> None:
        self.closed = True


def api_client_over(transport, events=None) -> _AsyncUnleashApiClient:
    config = UnleashConfig(
        url=URL,
        app_name=APP_NAME,
        identity=IdentityOptions(instance_id=INSTANCE_ID),
    )
    return _AsyncUnleashApiClient(
        config, _HeaderFactory(config), events, transport=transport
    )


@mark.asyncio
async def test_fetch_features_sends_its_request_through_the_transport():
    transport = RecordingTransport(
        Response(status=200, headers={"etag": ETAG_VALUE}, body=b'{"version": 1}')
    )

    result = await api_client_over(transport).fetch_features(
        ETAG_VALUE, options=PollingOptions(project_name=PROJECT_NAME)
    )

    assert result == ('{"version": 1}', ETAG_VALUE, False)
    (request,) = transport.requests
    assert request.method == Method.GET
    assert request.url == URL + FEATURES_URL
    assert request.params == {"project": PROJECT_NAME}
    assert request.headers["If-None-Match"] == ETAG_VALUE


@mark.asyncio
async def test_register_posts_its_payload_through_the_transport():
    transport = RecordingTransport(Response(status=202, headers={}, body=b""))

    assert await api_client_over(transport).register({"appName": APP_NAME})

    (request,) = transport.requests
    assert request.method == Method.POST
    assert request.url == URL + REGISTER_URL
    assert json.loads(request.body) == {"appName": APP_NAME}


@mark.asyncio
async def test_send_metrics_posts_its_payload_through_the_transport():
    transport = RecordingTransport(Response(status=202, headers={}, body=b""))

    assert await api_client_over(transport).send_metrics(MOCK_METRICS_REQUEST)

    (request,) = transport.requests
    assert request.method == Method.POST
    assert request.url == URL + METRICS_URL
    assert json.loads(request.body) == MOCK_METRICS_REQUEST


@mark.asyncio
async def test_aclose_leaves_a_transport_it_was_given_open():
    transport = RecordingTransport(Response(status=202, headers={}, body=b""))

    await api_client_over(transport).aclose()

    assert not transport.closed


@mark.asyncio
async def test_aclose_closes_the_default_transport(server, api_client):
    server.on("POST", METRICS_PATH, status=202, payload={})
    await api_client.send_metrics(MOCK_METRICS_REQUEST)
    session = api_client._transport._session

    await api_client.aclose()

    assert session.closed


class RaisingTransport:
    """Raises the same exception for every request."""

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def execute(self, request: Request) -> Response:
        raise self.exc


class CustomTransportError(Exception):
    pass


@mark.asyncio
@mark.parametrize(
    "exc",
    (CustomTransportError("boom"), OSError("refused"), ValueError("bad")),
    ids=("foreign", "os-error", "value-error"),
)
async def test_any_transport_exception_is_a_failed_request(exc):
    events = RecordingEvents()
    api_client = api_client_over(RaisingTransport(exc), events)

    result = await api_client.fetch_features(options=PollingOptions())

    assert result == (None, "", False)
    assert fetch_outcomes(events) == [FetchStatus.UNAVAILABLE]
    assert await api_client.register({}) is False
    assert await api_client.send_metrics(MOCK_METRICS_REQUEST) is False


@mark.asyncio
async def test_a_transport_closed_by_its_creator_gives_failed_requests():
    transport = AiohttpTransport()
    await transport.aclose()
    events = RecordingEvents()
    api_client = api_client_over(transport, events)

    result = await api_client.fetch_features(options=PollingOptions())

    assert result == (None, "", False)
    assert fetch_outcomes(events) == [FetchStatus.UNAVAILABLE]
    assert await api_client.register({}) is False
    assert await api_client.send_metrics(MOCK_METRICS_REQUEST) is False


@mark.asyncio
@mark.parametrize(
    "call",
    (
        param(lambda api_client: api_client.register, id="register"),
        param(lambda api_client: api_client.send_metrics, id="send_metrics"),
    ),
)
async def test_a_payload_that_cannot_be_serialised_still_raises(call):
    # Only the transport's exceptions are failed requests: this is an SDK bug.
    transport = RecordingTransport(Response(status=202, headers={}, body=b""))

    with pytest.raises(TypeError):
        await call(api_client_over(transport))({"not-json": object()})

    assert transport.requests == []
