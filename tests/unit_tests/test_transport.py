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
from UnleashClient._headers import _HeaderFactory
from UnleashClient._transport import _Transport
from UnleashClient.config import (
    HttpOptions,
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
from UnleashClient.events import FetchStatus, UnleashEventType

FULL_FEATURE_URL = URL + FEATURES_URL
FULL_REGISTER_URL = URL + REGISTER_URL
FULL_METRICS_URL = URL + METRICS_URL


@pytest.fixture
def build_transport():
    """Factory. Keyword arguments override the defaults on the config."""

    def _build_transport(events=None, **kwargs) -> _Transport:
        defaults = {
            "url": URL,
            "app_name": APP_NAME,
            "identity": IdentityOptions(instance_id=INSTANCE_ID),
            "http": HttpOptions(
                headers=CUSTOM_HEADERS,
                options=CUSTOM_OPTIONS,
                timeout=REQUEST_TIMEOUT,
                retries=REQUEST_RETRIES,
            ),
        }
        defaults.update(kwargs)
        config = UnleashConfig(**defaults)
        return _Transport(config, _HeaderFactory(config), events)

    return _build_transport


@pytest.fixture
def transport(build_transport) -> _Transport:
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

    result = transport.fetch_features(options=PollingOptions())

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

    result = build_transport().fetch_features(
        options=PollingOptions(project_name=PROJECT_NAME)
    )

    assert len(responses.calls) == 1
    assert len(json.loads(result.raw_state)["features"]) == 1
    assert result.etag == ETAG_VALUE


@responses.activate
def test_fetch_features_drops_the_etag_on_failure(build_transport):
    responses.add(
        responses.GET, PROJECT_URL, json={}, status=500, headers={"etag": ETAG_VALUE}
    )

    result = build_transport().fetch_features(
        options=PollingOptions(project_name=PROJECT_NAME)
    )

    assert len(responses.calls) == 4
    assert not result.etag
    assert result.not_modified is False


@responses.activate
def test_fetch_features_sends_if_none_match_when_an_etag_is_known(build_transport):
    responses.add(responses.GET, PROJECT_URL, status=304, headers={"etag": ETAG_VALUE})

    result = build_transport().fetch_features(
        ETAG_VALUE, options=PollingOptions(project_name=PROJECT_NAME)
    )

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

    result = build_transport().fetch_features(
        ETAG_VALUE, options=PollingOptions(project_name=PROJECT_NAME)
    )

    assert len(responses.calls) == 2
    assert len(json.loads(result.raw_state)["features"]) == 1
    assert result.etag == ETAG_VALUE


@responses.activate
def test_fetch_features_swallows_a_bad_custom_option(build_transport):
    responses.add(
        responses.GET, FULL_FEATURE_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )

    # `timeout` collides with the keyword the transport already passes. It is a
    # TypeError, not a RequestException, and fetch_features swallows everything.
    result = build_transport(http=HttpOptions(options={"timeout": 5})).fetch_features(
        options=PollingOptions()
    )

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
def test_register_reraises_a_missing_schema(build_transport):
    transport = build_transport(url="thisisnotavalidurl")

    # initialize_client() fails loudly on a malformed URL because these four
    # are re-raised rather than reported as False. See test_uc_with_invalid_url,
    # which only sees the ValueError that MissingSchema also subclasses.
    with pytest.raises(MissingSchema):
        transport.register({})


@responses.activate
def test_register_reraises_an_invalid_schema(build_transport):
    transport = build_transport(url="localhost:4242/api")

    with pytest.raises(InvalidSchema):
        transport.register({})


@responses.activate
def test_register_lets_a_bad_custom_option_escape(build_transport):
    responses.add(responses.POST, FULL_REGISTER_URL, json={}, status=202)

    # A TypeError is not a RequestException, so unlike fetch_features this
    # propagates and fails initialize_client().
    with pytest.raises(TypeError):
        build_transport(http=HttpOptions(options={"timeout": 5})).register({})


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
def test_send_metrics_lets_a_bad_custom_option_escape(build_transport):
    responses.add(responses.POST, FULL_METRICS_URL, json={}, status=202)

    with pytest.raises(TypeError):
        build_transport(http=HttpOptions(options={"timeout": 5})).send_metrics({})


@responses.activate
def test_every_endpoint_gets_its_headers_from_the_factory(build_transport):
    responses.add(
        responses.GET, FULL_FEATURE_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )
    responses.add(responses.POST, FULL_REGISTER_URL, json={}, status=202)
    responses.add(responses.POST, FULL_METRICS_URL, json={}, status=202)
    transport = build_transport(metrics=MetricsOptions(interval=2))

    transport.fetch_features(options=PollingOptions(interval=1))
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


@responses.activate
@mark.parametrize(
    "status,body,expected",
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
    ),
)
def test_fetch_features_reports_how_the_fetch_ended(
    build_transport, status, body, expected
):
    responses.add(responses.GET, FULL_FEATURE_URL, json=body, status=status)
    events = RecordingEvents()

    build_transport(events=events).fetch_features(options=PollingOptions())

    assert fetch_outcomes(events) == [expected]


@responses.activate
def test_fetch_features_reports_an_empty_200_as_invalid(build_transport):
    responses.add(responses.GET, FULL_FEATURE_URL, body="", status=200)
    events = RecordingEvents()

    build_transport(events=events).fetch_features(options=PollingOptions())

    assert fetch_outcomes(events) == [FetchStatus.INVALID_RESPONSE]


@responses.activate
def test_fetch_features_reports_unavailable_when_no_response_arrives(
    build_transport,
):
    responses.add(responses.GET, FULL_FEATURE_URL, body=ConnectionError("refused"))
    events = RecordingEvents()

    build_transport(events=events).fetch_features(options=PollingOptions())

    assert fetch_outcomes(events) == [FetchStatus.UNAVAILABLE]


@responses.activate
def test_fetch_features_survives_a_listener_that_raises(build_transport):
    responses.add(
        responses.GET, FULL_FEATURE_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )

    class BrokenEvents:
        def emit_event(self, event):
            raise RuntimeError("listener is broken")

    result = build_transport(events=BrokenEvents()).fetch_features(
        options=PollingOptions()
    )

    assert json.loads(result.raw_state)["version"] == 1
