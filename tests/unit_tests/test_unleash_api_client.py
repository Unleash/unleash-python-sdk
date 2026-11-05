import json

import pytest
import responses
from pytest import mark, param
from requests import ConnectionError
from requests.structures import CaseInsensitiveDict

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
    PROJECT_URL,
    URL,
)
from UnleashClient._headers import _HeaderFactory
from UnleashClient._unleash_api_client import _header, _UnleashApiClient
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
from UnleashClient.events import FetchStatus, UnleashEventType
from UnleashClient.transport import Request, Response

FULL_FEATURE_URL = URL + FEATURES_URL
FULL_REGISTER_URL = URL + REGISTER_URL
FULL_METRICS_URL = URL + METRICS_URL


@pytest.fixture
def build_api_client():
    """Factory. Keyword arguments override the defaults on the config."""

    def _build_api_client(events=None, **kwargs) -> _UnleashApiClient:
        defaults = {
            "url": URL,
            "app_name": APP_NAME,
            "identity": IdentityOptions(instance_id=INSTANCE_ID),
        }
        defaults.update(kwargs)
        config = UnleashConfig(**defaults)
        return _UnleashApiClient(config, _HeaderFactory(config), events)

    return _build_api_client


@pytest.fixture
def api_client(build_api_client) -> _UnleashApiClient:
    return build_api_client()


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
def test_fetch_features(api_client, response, status, calls, expected):
    responses.add(
        responses.GET,
        FULL_FEATURE_URL,
        json=response,
        status=status,
        headers={"etag": ETAG_VALUE},
    )

    result = api_client.fetch_features(options=PollingOptions())

    # 4 calls on a 500 is 1 + FETCH_RETRIES.
    assert len(responses.calls) == calls
    assert expected(result.raw_state)


@responses.activate
def test_fetch_features_sends_the_project_as_a_query_parameter(build_api_client):
    responses.add(
        responses.GET,
        PROJECT_URL,
        json=MOCK_FEATURE_RESPONSE_PROJECT,
        status=200,
        headers={"etag": ETAG_VALUE},
    )

    result = build_api_client().fetch_features(
        options=PollingOptions(project_name=PROJECT_NAME)
    )

    assert len(responses.calls) == 1
    assert len(json.loads(result.raw_state)["features"]) == 1
    assert result.etag == ETAG_VALUE


@responses.activate
def test_fetch_features_drops_the_etag_on_failure(build_api_client):
    responses.add(
        responses.GET, PROJECT_URL, json={}, status=500, headers={"etag": ETAG_VALUE}
    )

    result = build_api_client().fetch_features(
        options=PollingOptions(project_name=PROJECT_NAME)
    )

    assert len(responses.calls) == 4
    assert not result.etag
    assert result.not_modified is False


@responses.activate
def test_fetch_features_sends_if_none_match_when_an_etag_is_known(build_api_client):
    responses.add(responses.GET, PROJECT_URL, status=304, headers={"etag": ETAG_VALUE})

    result = build_api_client().fetch_features(
        ETAG_VALUE, options=PollingOptions(project_name=PROJECT_NAME)
    )

    assert len(responses.calls) == 1
    assert responses.calls[0].request.headers["If-None-Match"] == ETAG_VALUE
    assert result.raw_state is None
    assert result.etag == ETAG_VALUE
    # 304 and a hard failure are both raw_state=None; only this tells them apart.
    assert result.not_modified is True


@responses.activate
def test_fetch_features_retries_and_recovers(build_api_client):
    responses.add(responses.GET, PROJECT_URL, json={}, status=500)
    responses.add(
        responses.GET,
        PROJECT_URL,
        json=MOCK_FEATURE_RESPONSE_PROJECT,
        status=200,
        headers={"etag": ETAG_VALUE},
    )

    result = build_api_client().fetch_features(
        ETAG_VALUE, options=PollingOptions(project_name=PROJECT_NAME)
    )

    assert len(responses.calls) == 2
    assert len(json.loads(result.raw_state)["features"]) == 1
    assert result.etag == ETAG_VALUE


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
def test_register(api_client, payload, status, expected):
    responses.add(responses.POST, FULL_REGISTER_URL, **payload, status=status)

    result = api_client.register({"appName": APP_NAME})

    # Never retried, unlike fetch_features.
    assert len(responses.calls) == 1
    assert result is expected


@responses.activate
def test_register_sends_the_payload_it_is_given(api_client):
    responses.add(responses.POST, FULL_REGISTER_URL, json={}, status=202)

    api_client.register({"appName": APP_NAME, "strategies": []})

    assert json.loads(responses.calls[0].request.body) == {
        "appName": APP_NAME,
        "strategies": [],
    }


@pytest.fixture
def skip_url_validation(monkeypatch):
    """
    UnleashConfig rejects these urls on construction, so register() only sees
    one that slipped past that check. Skip it to reach requests' own error.
    """
    monkeypatch.setattr("UnleashClient.config._validate_url", lambda url: None)


@responses.activate
@pytest.mark.usefixtures("skip_url_validation")
@mark.parametrize(
    "url", ("thisisnotavalidurl", "localhost:4242/api"), ids=("no-scheme", "bad-scheme")
)
def test_register_reports_a_url_requests_rejects_as_a_failure(build_api_client, url):
    assert build_api_client(url=url).register({}) is False


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
def test_send_metrics(api_client, payload, status, expected):
    responses.add(responses.POST, FULL_METRICS_URL, **payload, status=status)

    result = api_client.send_metrics(MOCK_METRICS_REQUEST)

    request = json.loads(responses.calls[0].request.body)

    assert len(responses.calls) == 1
    assert result is expected

    assert request["connectionId"] == MOCK_METRICS_REQUEST.get("connectionId")


@responses.activate
def test_every_endpoint_gets_its_headers_from_the_factory(build_api_client):
    responses.add(
        responses.GET, FULL_FEATURE_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )
    responses.add(responses.POST, FULL_REGISTER_URL, json={}, status=202)
    responses.add(responses.POST, FULL_METRICS_URL, json={}, status=202)
    api_client = build_api_client(metrics=MetricsOptions(interval=2))

    api_client.fetch_features(options=PollingOptions(interval=1))
    api_client.register({})
    api_client.send_metrics(MOCK_METRICS_REQUEST)

    fetch, register, metrics = (call.request.headers for call in responses.calls)
    # The identification headers reach all three...
    for headers in (fetch, register, metrics):
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
    build_api_client, status, body, expected
):
    responses.add(responses.GET, FULL_FEATURE_URL, json=body, status=status)
    events = RecordingEvents()

    build_api_client(events=events).fetch_features(options=PollingOptions())

    assert fetch_outcomes(events) == [expected]


@responses.activate
def test_fetch_features_reports_an_empty_200_as_invalid(build_api_client):
    responses.add(responses.GET, FULL_FEATURE_URL, body="", status=200)
    events = RecordingEvents()

    build_api_client(events=events).fetch_features(options=PollingOptions())

    assert fetch_outcomes(events) == [FetchStatus.INVALID_RESPONSE]


@responses.activate
def test_fetch_features_reports_unavailable_when_no_response_arrives(
    build_api_client,
):
    responses.add(responses.GET, FULL_FEATURE_URL, body=ConnectionError("refused"))
    events = RecordingEvents()

    build_api_client(events=events).fetch_features(options=PollingOptions())

    assert fetch_outcomes(events) == [FetchStatus.UNAVAILABLE]


@responses.activate
def test_fetch_features_survives_a_listener_that_raises(build_api_client):
    responses.add(
        responses.GET, FULL_FEATURE_URL, json=MOCK_FEATURE_RESPONSE, status=200
    )

    class BrokenEvents:
        def emit_event(self, event):
            raise RuntimeError("listener is broken")

    result = build_api_client(events=BrokenEvents()).fetch_features(
        options=PollingOptions()
    )

    assert json.loads(result.raw_state)["version"] == 1


# transport


class RecordingTransport:
    """Answers every request with one canned response, keeping the requests."""

    def __init__(self, response: Response) -> None:
        self.response = response
        self.requests: list = []

    def execute(self, request: Request) -> Response:
        self.requests.append(request)
        return self.response


def test_fetch_features_sends_its_request_through_the_transport():
    transport = RecordingTransport(
        Response(status=200, headers={"etag": ETAG_VALUE}, body=b'{"version": 1}')
    )
    config = UnleashConfig(URL, APP_NAME)
    api_client = _UnleashApiClient(config, _HeaderFactory(config), transport=transport)

    result = api_client.fetch_features(
        "previous-etag", options=PollingOptions(project_name=PROJECT_NAME)
    )

    (request,) = transport.requests
    assert request.method == "GET"
    assert request.url == FULL_FEATURE_URL
    assert request.params == {"project": PROJECT_NAME}
    assert request.headers["If-None-Match"] == "previous-etag"
    assert result == ('{"version": 1}', ETAG_VALUE, False)


def test_register_posts_its_payload_through_the_transport():
    transport = RecordingTransport(Response(status=202, headers={}, body=b""))
    config = UnleashConfig(URL, APP_NAME)
    api_client = _UnleashApiClient(config, _HeaderFactory(config), transport=transport)

    assert api_client.register({"appName": APP_NAME})

    (request,) = transport.requests
    assert request.method == "POST"
    assert request.url == FULL_REGISTER_URL
    assert json.loads(request.body) == {"appName": APP_NAME}


def test_send_metrics_posts_its_payload_through_the_transport():
    transport = RecordingTransport(Response(status=202, headers={}, body=b""))
    config = UnleashConfig(URL, APP_NAME)
    api_client = _UnleashApiClient(config, _HeaderFactory(config), transport=transport)

    assert api_client.send_metrics({"appName": APP_NAME})

    (request,) = transport.requests
    assert request.method == "POST"
    assert request.url == FULL_METRICS_URL
    assert json.loads(request.body) == {"appName": APP_NAME}


class RaisingTransport:
    """Raises the same exception for every request."""

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def execute(self, request: Request) -> Response:
        raise self.exc


def api_client_over(transport, events=None) -> _UnleashApiClient:
    config = UnleashConfig(URL, APP_NAME)
    return _UnleashApiClient(
        config, _HeaderFactory(config), events, transport=transport
    )


class CustomTransportError(Exception):
    pass


@mark.parametrize(
    "exc",
    (CustomTransportError("boom"), OSError("refused"), ValueError("bad")),
    ids=("foreign", "os-error", "value-error"),
)
def test_any_transport_exception_is_a_failed_request(exc):
    events = RecordingEvents()
    api_client = api_client_over(RaisingTransport(exc), events)

    assert api_client.fetch_features(options=PollingOptions()) == (None, "", False)
    assert fetch_outcomes(events) == [FetchStatus.UNAVAILABLE]
    assert api_client.register({}) is False
    assert api_client.send_metrics({}) is False


@mark.parametrize(
    "call",
    (
        param(lambda api_client: api_client.register, id="register"),
        param(lambda api_client: api_client.send_metrics, id="send_metrics"),
    ),
)
def test_a_payload_that_cannot_be_serialised_still_raises(call):
    transport = RecordingTransport(Response(status=202, headers={}, body=b""))

    with pytest.raises(TypeError):
        call(api_client_over(transport))({"not-json": object()})

    assert transport.requests == []


@pytest.mark.parametrize(
    "headers,expected",
    (
        ({"ETag": "v1"}, "v1"),
        ({"etag": "v1"}, "v1"),
        (CaseInsensitiveDict({"ETAG": "v1"}), "v1"),
        ({"Content-Type": "application/json"}, ""),
    ),
    ids=("plain-dict-capitalised", "plain-dict-lowercase", "requests-dict", "absent"),
)
def test_header_matches_names_case_insensitively(headers, expected):
    assert _header(Response(status=200, headers=headers, body=b""), "etag") == expected
