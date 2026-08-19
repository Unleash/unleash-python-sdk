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
    ASYNC_CUSTOM_OPTIONS,
    CUSTOM_HEADERS,
    ETAG_VALUE,
    INSTANCE_ID,
    PROJECT_NAME,
    REQUEST_RETRIES,
    REQUEST_TIMEOUT,
)
from UnleashClient.async_transport import AsyncTransport
from UnleashClient.config import UnleashConfig
from UnleashClient.constants import (
    CLIENT_SPEC_VERSION,
    FEATURES_URL,
    METRICS_URL,
    REGISTER_URL,
)
from UnleashClient.headers import HeaderFactory

# testing_constants.URL mounts Unleash under /api, and the fake server does the
# same, so the transport builds the URL shape it builds against a deployment.
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
async def build_transport(server: FakeUnleash):
    """
    Factory pointed at the fake server. Keyword arguments override the defaults
    on the config.

    Every transport it builds is closed on teardown: nothing calls aclose() in
    production yet, and an unclosed ClientSession is reported by aiohttp on
    garbage collection.
    """
    built = []

    def _build_transport(**kwargs) -> AsyncTransport:
        defaults = {
            "instance_id": INSTANCE_ID,
            "custom_headers": CUSTOM_HEADERS,
            "custom_options": ASYNC_CUSTOM_OPTIONS,
            "request_timeout": REQUEST_TIMEOUT,
            "request_retries": REQUEST_RETRIES,
        }
        defaults.update(kwargs)
        config = UnleashConfig(server.base_url, APP_NAME, **defaults)
        transport = AsyncTransport(config, HeaderFactory(config))
        built.append(transport)
        return transport

    try:
        yield _build_transport
    finally:
        for transport in built:
            await transport.aclose()


@pytest_asyncio.fixture
async def transport(build_transport: Callable[..., AsyncTransport]) -> AsyncTransport:
    """The transport the tests that need no config override share."""
    return build_transport()


# fetch_features


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
    server, transport, response, status, call_count, expected
):
    server.on(
        "GET",
        FEATURES_PATH,
        status=status,
        payload=response,
        headers={"etag": ETAG_VALUE},
        repeat=True,
    )

    result = await transport.fetch_features()

    # 4 calls on a 500 is 1 + REQUEST_RETRIES, as the sync transport's
    # mounted HTTPAdapter/Retry gives it.
    assert len(server.calls("GET", FEATURES_PATH)) == call_count
    assert expected(result.raw_state)


@mark.asyncio
async def test_fetch_features_sends_the_project_as_a_query_parameter(
    server, build_transport
):
    transport = build_transport(project_name=PROJECT_NAME)
    server.on(
        "GET",
        FEATURES_PATH,
        status=200,
        payload=MOCK_FEATURE_RESPONSE_PROJECT,
        headers={"etag": ETAG_VALUE},
    )

    result = await transport.fetch_features()

    calls = server.calls("GET", FEATURES_PATH)
    assert len(calls) == 1
    assert calls[0].query == {"project": PROJECT_NAME}
    assert len(json.loads(result.raw_state)["features"]) == 1
    assert result.etag == ETAG_VALUE


@mark.asyncio
async def test_fetch_features_drops_the_etag_on_failure(server, build_transport):
    transport = build_transport(project_name=PROJECT_NAME)
    server.on(
        "GET",
        FEATURES_PATH,
        status=500,
        payload={},
        headers={"etag": ETAG_VALUE},
        repeat=True,
    )

    result = await transport.fetch_features()

    assert len(server.calls("GET", FEATURES_PATH)) == 4
    assert not result.etag
    assert result.not_modified is False


@mark.asyncio
async def test_fetch_features_sends_if_none_match_when_an_etag_is_known(
    server, build_transport
):
    transport = build_transport(project_name=PROJECT_NAME)
    server.on("GET", FEATURES_PATH, status=304, headers={"etag": ETAG_VALUE})

    result = await transport.fetch_features(ETAG_VALUE)

    calls = server.calls("GET", FEATURES_PATH)
    assert len(calls) == 1
    assert calls[0].headers["If-None-Match"] == ETAG_VALUE
    assert result.raw_state is None
    assert result.etag == ETAG_VALUE
    # 304 and a hard failure are both raw_state=None; only this tells them apart.
    assert result.not_modified is True


@mark.asyncio
async def test_fetch_features_retries_and_recovers(server, build_transport):
    transport = build_transport(project_name=PROJECT_NAME)
    server.on("GET", FEATURES_PATH, status=500, payload={})
    server.on(
        "GET",
        FEATURES_PATH,
        status=200,
        payload=MOCK_FEATURE_RESPONSE_PROJECT,
        headers={"etag": ETAG_VALUE},
    )

    result = await transport.fetch_features(ETAG_VALUE)

    assert len(server.calls("GET", FEATURES_PATH)) == 2
    assert len(json.loads(result.raw_state)["features"]) == 1
    assert result.etag == ETAG_VALUE


@mark.asyncio
async def test_fetch_features_retries_and_recovers_from_a_connection_error(
    server, build_transport
):
    transport = build_transport(project_name=PROJECT_NAME)
    server.on("GET", FEATURES_PATH, disconnect=True)
    server.on(
        "GET",
        FEATURES_PATH,
        status=200,
        payload=MOCK_FEATURE_RESPONSE_PROJECT,
        headers={"etag": ETAG_VALUE},
    )

    # urllib3's Retry covers connection failures as well as the status
    # forcelist, so the hand-rolled loop has to do both.
    result = await transport.fetch_features(ETAG_VALUE)

    assert len(server.calls("GET", FEATURES_PATH)) == 2
    assert len(json.loads(result.raw_state)["features"]) == 1


@mark.asyncio
async def test_fetch_features_carries_the_uppercase_identification_headers(
    server, transport, mocker
):
    # The spelling is read off the request rather than off the wire: header
    # names are case-insensitive, so a server cannot tell the uppercase copy
    # from the lowercase pair HeaderFactory.polling() already carries.
    spy = mocker.spy(aiohttp.ClientSession, "get")
    server.on(
        "GET",
        FEATURES_PATH,
        status=200,
        payload=MOCK_FEATURE_RESPONSE,
        headers={"etag": ETAG_VALUE},
    )

    await transport.fetch_features()

    sent = spy.call_args.kwargs["headers"]
    assert [key for key in sent if key.lower() == "unleash-appname"] == [
        "UNLEASH-APPNAME"
    ]
    assert [key for key in sent if key.lower() == "unleash-instanceid"] == [
        "UNLEASH-INSTANCEID"
    ]

    received = server.calls("GET", FEATURES_PATH)[0].headers
    assert received["unleash-appname"] == APP_NAME
    assert received["unleash-instanceid"] == INSTANCE_ID


@mark.asyncio
async def test_fetch_features_sends_each_identification_header_once(
    server, transport, mocker
):
    # Read off the request rather than off the wire: aiohttp folds repeated
    # spellings of a header itself, so a server cannot tell a transport that
    # merged them from one that did not.
    spy = mocker.spy(aiohttp.ClientSession, "get")
    server.on("GET", FEATURES_PATH, status=200, payload=MOCK_FEATURE_RESPONSE)

    await transport.fetch_features()

    # HeaderFactory.base() carries a lowercase pair and the features
    # endpoint adds an uppercase one. requests folds the two into a single
    # header; aiohttp would put both spellings on the wire unless the merge
    # happens in a CIMultiDict first.
    headers = spy.call_args.kwargs["headers"]
    assert headers.getall("unleash-appname") == [APP_NAME]
    assert headers.getall("unleash-instanceid") == [INSTANCE_ID]


@mark.asyncio
async def test_fetch_features_strips_a_trailing_slash_from_the_url(server, transport):
    server.on(
        "GET",
        FEATURES_PATH,
        status=200,
        payload=MOCK_FEATURE_RESPONSE,
        headers={"etag": ETAG_VALUE},
    )
    # The unleash_url setter writes config.url directly and never
    # re-normalizes, so the trailing slash has to be stripped at request time.
    transport._config.url = f"{server.base_url}/"

    result = await transport.fetch_features()

    assert len(server.calls("GET", FEATURES_PATH)) == 1
    assert json.loads(result.raw_state)["version"] == 1
    assert result.etag == ETAG_VALUE


@mark.asyncio
async def test_fetch_features_swallows_a_bad_custom_option(server, build_transport):
    transport = build_transport(custom_options={"verify": False})
    server.on("GET", FEATURES_PATH, status=200, payload=MOCK_FEATURE_RESPONSE)

    # `verify` is a requests keyword; aiohttp rejects it while binding the
    # call. It is a TypeError, not a ClientError, and fetch_features
    # swallows everything.
    result = await transport.fetch_features()

    assert result == (None, "", False)
    assert server.calls("GET", FEATURES_PATH) == []


# register


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
async def test_register(server, transport, reply, expected):
    server.on("POST", REGISTER_PATH, **reply)

    result = await transport.register({"appName": APP_NAME})

    # No retry loop on this one, unlike fetch_features.
    assert len(server.calls("POST", REGISTER_PATH)) == 1
    assert result is expected


@mark.asyncio
async def test_register_sends_the_payload_it_is_given(server, transport):
    server.on("POST", REGISTER_PATH, status=202, payload={})

    await transport.register({"appName": APP_NAME, "strategies": []})

    body = server.calls("POST", REGISTER_PATH)[0].body
    assert json.loads(body) == {"appName": APP_NAME, "strategies": []}


@mark.asyncio
async def test_register_strips_a_trailing_slash_from_the_url(server, transport):
    server.on("POST", REGISTER_PATH, status=202, payload={})
    transport._config.url = f"{server.base_url}/"

    result = await transport.register({})

    assert len(server.calls("POST", REGISTER_PATH)) == 1
    assert result is True


@mark.asyncio
@mark.parametrize(
    "url", ("thisisnotavalidurl", "localhost:4242/api"), ids=("no-scheme", "bad-scheme")
)
async def test_register_reraises_an_unusable_url(server, transport, url):
    transport._config.url = url

    # initialize_client() fails loudly on a malformed URL because these are
    # re-raised rather than reported as False.
    with pytest.raises(aiohttp.ClientError):
        await transport.register({})

    # Raised before a socket is opened, so nothing reaches the server.
    assert server.requests == []


@mark.asyncio
async def test_register_reraises_a_missing_scheme_as_a_value_error(transport):
    transport._config.url = "thisisnotavalidurl"

    # test_uc_with_invalid_url only sees the ValueError that requests'
    # MissingSchema subclasses; aiohttp's InvalidURL subclasses it too, so the
    # sync client's contract carries over.
    with pytest.raises(ValueError):
        await transport.register({})


@mark.asyncio
async def test_register_lets_a_bad_custom_option_escape(server, build_transport):
    transport = build_transport(custom_options={"verify": False})
    server.on("POST", REGISTER_PATH, status=202, payload={})

    # A TypeError is not a ClientError, so unlike fetch_features this
    # propagates and fails initialize_client().
    with pytest.raises(TypeError):
        await transport.register({})


# send_metrics


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
async def test_send_metrics(server, transport, reply, expected):
    server.on("POST", METRICS_PATH, **reply)

    result = await transport.send_metrics(MOCK_METRICS_REQUEST)

    calls = server.calls("POST", METRICS_PATH)
    assert len(calls) == 1
    assert result is expected

    body = json.loads(calls[0].body)
    assert body["connectionId"] == MOCK_METRICS_REQUEST.get("connectionId")


@mark.asyncio
async def test_send_metrics_strips_a_trailing_slash_from_the_url(server, transport):
    server.on("POST", METRICS_PATH, status=202, payload={})
    transport._config.url = f"{server.base_url}/"

    result = await transport.send_metrics(MOCK_METRICS_REQUEST)

    assert len(server.calls("POST", METRICS_PATH)) == 1
    assert result is True


@mark.asyncio
async def test_send_metrics_lets_a_bad_custom_option_escape(server, build_transport):
    transport = build_transport(custom_options={"verify": False})
    server.on("POST", METRICS_PATH, status=202, payload={})

    with pytest.raises(TypeError):
        await transport.send_metrics({})


# config read-through


@mark.asyncio
async def test_the_config_is_read_on_every_request(server, transport, mocker):
    # Read off the request rather than off the wire: a timeout is aiohttp's own
    # bookkeeping and never reaches the server.
    spy = mocker.spy(aiohttp.ClientSession, "post")
    server.on("POST", METRICS_PATH, status=202, payload={})

    transport._config.request_timeout = 7
    await transport.send_metrics(MOCK_METRICS_REQUEST)

    # unleash_request_timeout and friends are public setters, so an
    # AsyncTransport built in __init__ has to pick up a change made after
    # initialize_client().
    timeout = spy.call_args.kwargs["timeout"]
    # sock_connect/sock_read rather than total: requests' scalar timeout
    # bounds each socket operation, not the whole request.
    assert timeout == aiohttp.ClientTimeout(total=None, sock_connect=7, sock_read=7)


@mark.asyncio
async def test_every_endpoint_gets_its_headers_from_the_factory(
    server, build_transport
):
    transport = build_transport(refresh_interval=1, metrics_interval=2)
    server.on("GET", FEATURES_PATH, status=200, payload=MOCK_FEATURE_RESPONSE)
    server.on("POST", REGISTER_PATH, status=202, payload={})
    server.on("POST", METRICS_PATH, status=202, payload={})

    await transport.fetch_features()
    await transport.register({})
    await transport.send_metrics(MOCK_METRICS_REQUEST)

    fetch = server.calls("GET", FEATURES_PATH)[0].headers
    register = server.calls("POST", REGISTER_PATH)[0].headers
    metrics = server.calls("POST", METRICS_PATH)[0].headers
    # The custom header and the identification pair reach all three...
    for headers in (fetch, register, metrics):
        assert headers["name"] == CUSTOM_HEADERS["name"]
        assert headers["unleash-appname"] == APP_NAME
        assert headers["Unleash-Client-Spec"] == CLIENT_SPEC_VERSION
    # ...and each endpoint gets the interval its own header set carries.
    assert fetch["unleash-interval"] == "1000"
    assert "unleash-interval" not in register
    assert metrics["unleash-interval"] == "2000"


@mark.asyncio
async def test_headers_are_rebuilt_on_every_request(server, transport):
    server.on("POST", METRICS_PATH, status=202, payload={}, repeat=True)

    await transport.send_metrics(MOCK_METRICS_REQUEST)
    # unleash_custom_headers is a public setter, so the factory has to be
    # asked again rather than its answer captured.
    transport._config.custom_headers = {"Authorization": "second"}
    await transport.send_metrics(MOCK_METRICS_REQUEST)

    calls = server.calls("POST", METRICS_PATH)
    assert "Authorization" not in calls[0].headers
    assert calls[1].headers["Authorization"] == "second"


# session lifecycle -- no sync counterpart


@mark.asyncio
async def test_the_session_is_reused_across_requests(server, transport):
    server.on("POST", METRICS_PATH, status=202, payload={}, repeat=True)

    await transport.send_metrics(MOCK_METRICS_REQUEST)
    first = transport._session
    await transport.send_metrics(MOCK_METRICS_REQUEST)

    assert first is not None
    assert transport._session is first


@mark.asyncio
async def test_aclose_is_a_no_op_before_any_request(build_transport):
    transport = build_transport()

    await transport.aclose()
    await transport.aclose()

    assert transport._session is None


@mark.asyncio
async def test_aclose_closes_the_session_and_a_later_request_opens_a_new_one(
    server, transport
):
    server.on("POST", METRICS_PATH, status=202, payload={}, repeat=True)

    await transport.send_metrics(MOCK_METRICS_REQUEST)
    first = transport._session
    await transport.aclose()

    assert first.closed
    assert transport._session is None

    # A closed session is not reused: aiohttp refuses to send on one.
    await transport.send_metrics(MOCK_METRICS_REQUEST)

    assert transport._session is not None
    assert transport._session is not first
