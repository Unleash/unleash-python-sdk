import json

import pytest
import responses
from requests import ConnectionError

from tests.utilities.testing_constants import URL
from UnleashClient._transport import Method, Request, RequestsTransport, Transport

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
def test_execute_retries_a_get_when_retries_are_set():
    responses.add(responses.GET, ENDPOINT, status=500)
    responses.add(responses.GET, ENDPOINT, body=b"{}", status=200)

    response = RequestsTransport(_retries=1).execute(
        Request(method=Method.GET, url=ENDPOINT, headers={})
    )

    assert len(responses.calls) == 2
    assert response.status == 200


@responses.activate
def test_execute_does_not_retry_without_retries():
    responses.add(responses.GET, ENDPOINT, status=500)

    response = RequestsTransport().execute(
        Request(method=Method.GET, url=ENDPOINT, headers={})
    )

    assert len(responses.calls) == 1
    assert response.status == 500


@responses.activate
def test_execute_never_retries_a_post():
    responses.add(responses.POST, ENDPOINT, status=500)

    response = RequestsTransport(_retries=3).execute(
        Request(method=Method.POST, url=ENDPOINT, headers={}, body=b"{}")
    )

    assert len(responses.calls) == 1
    assert response.status == 500


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
