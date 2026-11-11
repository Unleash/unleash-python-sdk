import json

import pytest
import requests
import responses
from requests import ConnectionError
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from tests.utilities.testing_constants import URL
from UnleashClient.transport import Method, Request, RequestsTransport, Transport

ENDPOINT = URL + "/client/features"


def test_requests_transport_is_a_transport():
    assert isinstance(RequestsTransport(), Transport)


@responses.activate
def test_execute_sends_a_get_with_its_headers_and_params():
    responses.add(responses.GET, ENDPOINT, status=200)

    RequestsTransport().execute(
        Request(
            method=Method.GET,
            url=ENDPOINT,
            headers={"X-Test": "value"},
            params={"project": "ivan"},
        )
    )

    sent = responses.calls[0].request
    assert sent.method == "GET"
    assert sent.url == ENDPOINT + "?project=ivan"
    assert sent.headers["X-Test"] == "value"
    assert sent.body is None


@responses.activate
def test_execute_sends_a_post_with_its_body():
    responses.add(responses.POST, ENDPOINT, status=202)

    RequestsTransport().execute(
        Request(method=Method.POST, url=ENDPOINT, headers={}, body=b'{"appName": "x"}')
    )

    sent = responses.calls[0].request
    assert sent.method == "POST"
    assert sent.url == ENDPOINT
    assert json.loads(sent.body) == {"appName": "x"}


@responses.activate
def test_execute_returns_the_status_headers_and_body():
    responses.add(
        responses.GET,
        ENDPOINT,
        body=b'{"version": 1}',
        status=200,
        headers={"ETag": "v1"},
    )

    response = RequestsTransport().execute(
        Request(method=Method.GET, url=ENDPOINT, headers={})
    )

    assert response.status == 200
    assert response.body == b'{"version": 1}'
    # looked up case-insensitively
    assert response.headers["etag"] == "v1"


@responses.activate
@pytest.mark.parametrize("status", [304, 401, 500])
def test_execute_returns_any_status_instead_of_raising(status):
    responses.add(responses.GET, ENDPOINT, status=status)

    response = RequestsTransport().execute(
        Request(method=Method.GET, url=ENDPOINT, headers={})
    )

    assert response.status == status


@responses.activate
def test_execute_raises_when_no_response_arrives():
    responses.add(responses.GET, ENDPOINT, body=ConnectionError("refused"))

    with pytest.raises(ConnectionError):
        RequestsTransport().execute(
            Request(method=Method.GET, url=ENDPOINT, headers={})
        )


@responses.activate
@pytest.mark.parametrize("method", [Method.GET, Method.POST])
def test_execute_sends_once_even_on_a_retry_status(method):
    responses.add(method, ENDPOINT, status=500)
    responses.add(method, ENDPOINT, status=200)

    response = RequestsTransport().execute(
        Request(method=method, url=ENDPOINT, headers={})
    )

    assert len(responses.calls) == 1
    assert response.status == 500


@responses.activate
def test_execute_sends_once_on_a_connection_error():
    responses.add(responses.GET, ENDPOINT, body=ConnectionError("refused"))
    responses.add(responses.GET, ENDPOINT, status=200)

    with pytest.raises(ConnectionError):
        RequestsTransport().execute(
            Request(method=Method.GET, url=ENDPOINT, headers={})
        )

    assert len(responses.calls) == 1


@responses.activate
def test_execute_passes_the_extra_request_kwargs():
    responses.add(
        responses.GET, ENDPOINT, status=302, headers={"Location": URL + "/elsewhere"}
    )

    response = RequestsTransport(_request_kwargs={"allow_redirects": False}).execute(
        Request(method=Method.GET, url=ENDPOINT, headers={})
    )

    assert response.status == 302


def test_execute_rejects_an_extra_kwarg_it_already_sets():
    transport = RequestsTransport(_request_kwargs={"timeout": 5})

    with pytest.raises(TypeError):
        transport.execute(Request(method=Method.GET, url=ENDPOINT, headers={}))


@responses.activate
def test_execute_uses_a_fresh_session_for_every_request():
    responses.add(responses.GET, ENDPOINT, status=200, headers={"Set-Cookie": "a=1"})
    responses.add(responses.GET, ENDPOINT, status=200)
    transport = RequestsTransport()

    transport.execute(Request(method=Method.GET, url=ENDPOINT, headers={}))
    transport.execute(Request(method=Method.GET, url=ENDPOINT, headers={}))

    # A shared session would send the cookie back.
    assert "Cookie" not in responses.calls[1].request.headers


@responses.activate
def test_execute_sends_on_the_session_passed_in():
    responses.add(responses.GET, ENDPOINT, status=200, headers={"Set-Cookie": "a=1"})
    responses.add(responses.GET, ENDPOINT, status=200)
    session = requests.Session()
    session.headers["X-From-Session"] = "yes"
    transport = RequestsTransport(session)

    transport.execute(Request(method=Method.GET, url=ENDPOINT, headers={}))
    transport.execute(Request(method=Method.GET, url=ENDPOINT, headers={}))

    assert responses.calls[0].request.headers["X-From-Session"] == "yes"
    assert responses.calls[1].request.headers["Cookie"] == "a=1"


@responses.activate
def test_execute_never_closes_the_session_passed_in(mocker):
    responses.add(responses.GET, ENDPOINT, status=200)
    session = requests.Session()
    close = mocker.spy(session, "close")

    RequestsTransport(session).execute(
        Request(method=Method.GET, url=ENDPOINT, headers={})
    )

    close.assert_not_called()


def test_a_session_with_a_retrying_adapter_logs_a_warning(caplog):
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=Retry(total=3)))

    RequestsTransport(session)

    assert "retries requests itself" in caplog.text


def test_a_plain_session_logs_no_warning(caplog):
    RequestsTransport(requests.Session())

    assert "retries requests itself" not in caplog.text


@responses.activate
def test_execute_sends_the_transport_headers():
    responses.add(responses.GET, ENDPOINT, status=200)

    RequestsTransport(headers={"X-Team": "checkout"}).execute(
        Request(method=Method.GET, url=ENDPOINT, headers={"X-Test": "value"})
    )

    sent = responses.calls[0].request
    assert sent.headers["X-Team"] == "checkout"
    assert sent.headers["X-Test"] == "value"


@responses.activate
def test_the_request_headers_win_over_the_transport_headers_whatever_their_case():
    responses.add(responses.GET, ENDPOINT, status=200)

    RequestsTransport(headers={"UNLEASH-APPNAME": "spoofed"}).execute(
        Request(method=Method.GET, url=ENDPOINT, headers={"unleash-appname": "my-app"})
    )

    assert responses.calls[0].request.headers["unleash-appname"] == "my-app"


@pytest.mark.parametrize("name", ["Authorization", "authorization"])
def test_an_authorization_header_raises(name):
    with pytest.raises(ValueError, match="api_key"):
        RequestsTransport(headers={name: "token"})


@responses.activate
def test_execute_uses_the_timeout(mocker):
    responses.add(responses.GET, ENDPOINT, status=200)
    send = mocker.spy(requests.Session, "request")

    RequestsTransport(timeout=7).execute(
        Request(method=Method.GET, url=ENDPOINT, headers={})
    )

    assert send.call_args.kwargs["timeout"] == 7
