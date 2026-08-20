import json

import pytest
import responses
from pytest import mark, param
from requests import ConnectionError
from requests.exceptions import InvalidSchema, MissingSchema

from tests.utilities.mocks.mock_features import (
    MOCK_FEATURE_RESPONSE,
    MOCK_FEATURE_RESPONSE_PROJECT,
)
from tests.utilities.mocks.mock_metrics import MOCK_METRICS_REQUEST
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
from UnleashClient.config import UnleashConfig
from UnleashClient.constants import (
    CLIENT_SPEC_VERSION,
    FEATURES_URL,
    METRICS_URL,
    REGISTER_URL,
)
from UnleashClient.headers import HeaderFactory
from UnleashClient.transport import Transport

FULL_FEATURE_URL = URL + FEATURES_URL
FULL_REGISTER_URL = URL + REGISTER_URL
FULL_METRICS_URL = URL + METRICS_URL


@pytest.fixture
def build_transport():
    """Factory. Keyword arguments override the defaults on the config."""

    def _build_transport(**kwargs) -> Transport:
        defaults = {
            "instance_id": INSTANCE_ID,
            "custom_headers": CUSTOM_HEADERS,
            "custom_options": CUSTOM_OPTIONS,
            "request_timeout": REQUEST_TIMEOUT,
            "request_retries": REQUEST_RETRIES,
        }
        defaults.update(kwargs)
        config = UnleashConfig(URL, APP_NAME, **defaults)
        return Transport(config, HeaderFactory(config))

    return _build_transport


@pytest.fixture
def transport(build_transport) -> Transport:
    return build_transport()


# fetch_features


@responses.activate
@mark.parametrize(
    "response,status,calls,expected",
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
def test_fetch_features(transport, response, status, calls, expected):
    responses.add(
        responses.GET,
        FULL_FEATURE_URL,
        json=response,
        status=status,
        headers={"etag": ETAG_VALUE},
    )

    result = transport.fetch_features()

    # 4 calls on a 500 is 1 + REQUEST_RETRIES: the mounted HTTPAdapter/Retry
    # has to survive every move of this code.
    assert len(responses.calls) == calls
    assert expected(result.raw_state)


@responses.activate
def test_fetch_features_sends_the_project_as_a_query_parameter(build_transport):
    responses.add(
        responses.GET,
        PROJECT_URL,
        json=MOCK_FEATURE_RESPONSE_PROJECT,
        status=200,
        headers={"etag": ETAG_VALUE},
    )

    result = build_transport(project_name=PROJECT_NAME).fetch_features()

    assert len(responses.calls) == 1
    assert len(json.loads(result.raw_state)["features"]) == 1
    assert result.etag == ETAG_VALUE


@responses.activate
def test_fetch_features_drops_the_etag_on_failure(build_transport):
    responses.add(
        responses.GET, PROJECT_URL, json={}, status=500, headers={"etag": ETAG_VALUE}
    )

    result = build_transport(project_name=PROJECT_NAME).fetch_features()

    assert len(responses.calls) == 4
    assert not result.etag
    assert result.not_modified is False


@responses.activate
def test_fetch_features_sends_if_none_match_when_an_etag_is_known(build_transport):
    responses.add(responses.GET, PROJECT_URL, status=304, headers={"etag": ETAG_VALUE})

    result = build_transport(project_name=PROJECT_NAME).fetch_features(ETAG_VALUE)

    assert len(responses.calls) == 1
    assert responses.calls[0].request.headers["If-None-Match"] == ETAG_VALUE
    assert result.raw_state is None
    assert result.etag == ETAG_VALUE
    # 304 and a hard failure are both raw_state=None; only this tells them apart.
    assert result.not_modified is True


@responses.activate
def test_fetch_features_retries_and_recovers(build_transport):
    responses.add(responses.GET, PROJECT_URL, json={}, status=500)
    responses.add(
        responses.GET,
        PROJECT_URL,
        json=MOCK_FEATURE_RESPONSE_PROJECT,
        status=200,
        headers={"etag": ETAG_VALUE},
    )

    result = build_transport(project_name=PROJECT_NAME).fetch_features(ETAG_VALUE)

    assert len(responses.calls) == 2
    assert len(json.loads(result.raw_state)["features"]) == 1
    assert result.etag == ETAG_VALUE


@responses.activate
def test_fetch_features_carries_the_uppercase_identification_headers(transport):
    responses.add(
        responses.GET,
        FULL_FEATURE_URL,
        json=MOCK_FEATURE_RESPONSE,
        status=200,
        headers={"etag": ETAG_VALUE},
    )

    transport.fetch_features()

    # HeaderFactory.base() already carries a lowercase pair, so this merge is
    # redundant in production -- but requests keeps the last-set casing, so
    # removing it would change the header names on the wire.
    request = responses.calls[0].request
    assert request.headers["UNLEASH-APPNAME"] == APP_NAME
    assert request.headers["UNLEASH-INSTANCEID"] == INSTANCE_ID


@responses.activate
def test_fetch_features_strips_a_trailing_slash_from_the_url(transport):
    responses.add(
        responses.GET,
        FULL_FEATURE_URL,
        json=MOCK_FEATURE_RESPONSE,
        status=200,
        headers={"etag": ETAG_VALUE},
    )
    # The unleash_url setter writes config.url directly and never re-normalizes,
    # so the trailing slash has to be stripped at request time.
    transport._config.url = f"{URL}/"

    result = transport.fetch_features()

    assert len(responses.calls) == 1
    assert responses.calls[0].request.url == FULL_FEATURE_URL
    assert json.loads(result.raw_state)["version"] == 1
    assert result.etag == ETAG_VALUE


@responses.activate
def test_fetch_features_swallows_a_bad_custom_option(build_transport):
    responses.add(
        responses.GET, FULL_FEATURE_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )

    # `timeout` collides with the keyword the transport already passes. It is a
    # TypeError, not a RequestException, and fetch_features swallows everything.
    result = build_transport(custom_options={"timeout": 5}).fetch_features()

    assert result == (None, "", False)


# register


@responses.activate
@mark.parametrize(
    "payload,status,expected",
    (
        param({"json": {}}, 202, True, id="success"),
        param({"json": {}}, 200, True, id="success-200"),
        param({"json": {}}, 500, False, id="failure"),
        param(
            {"body": ConnectionError("Test connection error")},
            200,
            False,
            id="exception",
        ),
    ),
)
def test_register(transport, payload, status, expected):
    responses.add(responses.POST, FULL_REGISTER_URL, **payload, status=status)

    result = transport.register({"appName": APP_NAME})

    # No retry adapter on this one, unlike fetch_features.
    assert len(responses.calls) == 1
    assert result is expected


@responses.activate
def test_register_sends_the_payload_it_is_given(transport):
    responses.add(responses.POST, FULL_REGISTER_URL, json={}, status=202)

    transport.register({"appName": APP_NAME, "strategies": []})

    assert json.loads(responses.calls[0].request.body) == {
        "appName": APP_NAME,
        "strategies": [],
    }


@responses.activate
def test_register_strips_a_trailing_slash_from_the_url(transport):
    responses.add(responses.POST, FULL_REGISTER_URL, json={}, status=202)
    transport._config.url = f"{URL}/"

    result = transport.register({})

    assert len(responses.calls) == 1
    assert responses.calls[0].request.url == FULL_REGISTER_URL
    assert result is True


@responses.activate
def test_register_reraises_a_missing_schema(transport):
    transport._config.url = "thisisnotavalidurl"

    # initialize_client() fails loudly on a malformed URL because these four
    # are re-raised rather than reported as False. See test_uc_with_invalid_url,
    # which only sees the ValueError that MissingSchema also subclasses.
    with pytest.raises(MissingSchema):
        transport.register({})


@responses.activate
def test_register_reraises_an_invalid_schema(transport):
    transport._config.url = "localhost:4242/api"

    with pytest.raises(InvalidSchema):
        transport.register({})


@responses.activate
def test_register_lets_a_bad_custom_option_escape(build_transport):
    responses.add(responses.POST, FULL_REGISTER_URL, json={}, status=202)

    # A TypeError is not a RequestException, so unlike fetch_features this
    # propagates and fails initialize_client().
    with pytest.raises(TypeError):
        build_transport(custom_options={"timeout": 5}).register({})


# send_metrics


@responses.activate
@mark.parametrize(
    "payload,status,expected",
    (
        param({"json": {}}, 202, True, id="success"),
        param({"json": {}}, 200, False, id="200-is-a-failure"),
        param({"json": {}}, 500, False, id="failure"),
        param(
            {"body": ConnectionError("Test connection error.")},
            200,
            False,
            id="exception",
        ),
    ),
)
def test_send_metrics(transport, payload, status, expected):
    responses.add(responses.POST, FULL_METRICS_URL, **payload, status=status)

    result = transport.send_metrics(MOCK_METRICS_REQUEST)

    request = json.loads(responses.calls[0].request.body)

    assert len(responses.calls) == 1
    assert result is expected

    assert request["connectionId"] == MOCK_METRICS_REQUEST.get("connectionId")


@responses.activate
def test_send_metrics_strips_a_trailing_slash_from_the_url(transport):
    responses.add(responses.POST, FULL_METRICS_URL, json={}, status=202)
    transport._config.url = f"{URL}/"

    result = transport.send_metrics(MOCK_METRICS_REQUEST)

    assert len(responses.calls) == 1
    assert responses.calls[0].request.url == FULL_METRICS_URL
    assert result is True


@responses.activate
def test_send_metrics_lets_a_bad_custom_option_escape(build_transport):
    responses.add(responses.POST, FULL_METRICS_URL, json={}, status=202)

    with pytest.raises(TypeError):
        build_transport(custom_options={"timeout": 5}).send_metrics({})


# config read-through


@responses.activate
def test_the_config_is_read_on_every_request(transport):
    responses.add(responses.POST, FULL_METRICS_URL, json={}, status=202)

    transport._config.request_timeout = 7
    transport.send_metrics(MOCK_METRICS_REQUEST)

    # unleash_request_timeout and friends are public setters, so a Transport
    # built in __init__ has to pick up a change made after initialize_client().
    assert responses.calls[0].request.req_kwargs["timeout"] == 7


@responses.activate
def test_every_endpoint_gets_its_headers_from_the_factory(build_transport):
    responses.add(
        responses.GET, FULL_FEATURE_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )
    responses.add(responses.POST, FULL_REGISTER_URL, json={}, status=202)
    responses.add(responses.POST, FULL_METRICS_URL, json={}, status=202)
    transport = build_transport(refresh_interval=1, metrics_interval=2)

    transport.fetch_features()
    transport.register({})
    transport.send_metrics(MOCK_METRICS_REQUEST)

    fetch, register, metrics = (call.request.headers for call in responses.calls)
    # The custom header and the identification pair reach all three...
    for headers in (fetch, register, metrics):
        assert headers["name"] == CUSTOM_HEADERS["name"]
        assert headers["unleash-appname"] == APP_NAME
        assert headers["Unleash-Client-Spec"] == CLIENT_SPEC_VERSION
    # ...and each endpoint gets the interval its own header set carries.
    assert fetch["unleash-interval"] == "1000"
    assert "unleash-interval" not in register
    assert metrics["unleash-interval"] == "2000"


@responses.activate
def test_headers_are_rebuilt_on_every_request(transport):
    responses.add(responses.POST, FULL_METRICS_URL, json={}, status=202)

    transport.send_metrics(MOCK_METRICS_REQUEST)
    # unleash_custom_headers is a public setter, so the factory has to be asked
    # again rather than its answer captured.
    transport._config.custom_headers = {"Authorization": "second"}
    transport.send_metrics(MOCK_METRICS_REQUEST)

    assert "Authorization" not in responses.calls[0].request.headers
    assert responses.calls[1].request.headers["Authorization"] == "second"
