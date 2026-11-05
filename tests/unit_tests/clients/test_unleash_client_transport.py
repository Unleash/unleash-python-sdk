import json

import pytest
import requests
import responses

from examples import fake_transport
from examples.fake_transport import FakeTransport, flag
from tests.utilities.testing_constants import APP_NAME, ETAG_VALUE, URL
from UnleashClient import INSTANCES, RequestsTransport, Response, UnleashClient
from UnleashClient.config import MetricsOptions, PollingOptions, StreamingOptions
from UnleashClient.constants import FEATURES_URL, REQUEST_TIMEOUT
from UnleashClient.utils import InstanceAllowType


@pytest.fixture(autouse=True)
def before_each():
    INSTANCES._reset()


def build_client(tmp_path, transport, **kwargs):
    return UnleashClient(
        URL,
        APP_NAME,
        api_key="project:environment.hash",
        cache_directory=str(tmp_path),
        transport=transport,
        **kwargs,
    )


def test_the_fake_transport_example_works(tmp_path):
    fake_transport.test_new_checkout_is_on(tmp_path)


def test_the_client_sends_every_request_through_the_transport(tmp_path):
    transport = FakeTransport(flag("testFlag", True))

    with build_client(tmp_path, transport) as client:
        assert client.is_enabled("testFlag")

    sent = [(request.method, request.url) for request in transport.requests]
    assert ("POST", URL + "/client/register") in sent
    assert ("GET", URL + FEATURES_URL) in sent
    assert ("POST", URL + "/client/metrics") in sent
    assert all(
        request.headers["Authorization"] == "project:environment.hash"
        for request in transport.requests
    )


class RecordingTransport(FakeTransport):
    def __len__(self):
        return len(self.requests)


def test_a_falsy_transport_is_used_and_not_replaced_by_the_default(tmp_path):
    transport = RecordingTransport(flag("testFlag", True))

    with build_client(tmp_path, transport) as client:
        assert client.is_enabled("testFlag")

    assert len(transport) > 0


class PlainDictEtagTransport(FakeTransport):
    """Returns its ETag in a plain dict, with the header name capitalised."""

    def execute(self, request):
        response = super().execute(request)
        if request.method != "GET":
            return response
        return Response(status=200, headers={"ETag": ETAG_VALUE}, body=response.body)


def test_an_etag_in_a_plain_dict_is_sent_back_on_the_next_fetch(tmp_path):
    transport = PlainDictEtagTransport(flag("testFlag", True))
    client = build_client(
        tmp_path,
        transport,
        metrics=MetricsOptions(disabled=True, disable_registration=True),
    )
    client.initialize_client()

    client.connector._fetch_and_load()
    client.destroy()

    first, second = transport.requests
    assert "If-None-Match" not in first.headers
    assert second.headers["If-None-Match"] == ETAG_VALUE


@responses.activate
def test_the_client_never_closes_a_session_passed_in(tmp_path, mocker):
    responses.add(
        responses.GET,
        URL + FEATURES_URL,
        json={"version": 1, "features": [flag("testFlag", True)]},
        status=200,
    )
    session = requests.Session()
    close = mocker.spy(session, "close")

    with build_client(
        tmp_path,
        RequestsTransport(session),
        metrics=MetricsOptions(disabled=True, disable_registration=True),
    ) as client:
        assert client.is_enabled("testFlag")

    close.assert_not_called()


class AsyncTransport:
    async def execute(self, request):
        raise AssertionError("never sent")


@pytest.mark.parametrize(
    "transport,message",
    (
        (requests.Session(), "RequestsTransport\\(session\\)"),
        (object(), "execute"),
        (AsyncTransport(), "async"),
    ),
    ids=("a-bare-session", "no-execute", "async-execute"),
)
def test_a_transport_that_cannot_work_raises(tmp_path, transport, message):
    with pytest.raises(TypeError, match=message):
        build_client(tmp_path, transport)


def test_a_rejected_transport_does_not_register_the_instance(tmp_path):
    with pytest.raises(TypeError):
        build_client(tmp_path, object())

    with build_client(
        tmp_path, FakeTransport(), multiple_instance_mode=InstanceAllowType.BLOCK
    ):
        pass


def test_the_httpx_example_works(tmp_path):
    httpx = pytest.importorskip("httpx")
    from examples.httpx_transport import HttpxTransport  # noqa: PLC0415

    sent = []

    def server(request):
        sent.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"version": 1, "features": [flag("testFlag", True)]},
                headers={"ETag": ETAG_VALUE},
            )
        return httpx.Response(202)

    with httpx.Client(transport=httpx.MockTransport(server)) as http_client:
        with build_client(
            tmp_path,
            HttpxTransport(http_client),
            mode=PollingOptions(project_name="checkout"),
        ) as client:
            assert client.is_enabled("testFlag")
            client.connector._fetch_and_load()

    register = next(r for r in sent if r.url.path.endswith("/register"))
    assert json.loads(register.content)["appName"] == APP_NAME
    fetches = [r for r in sent if r.method == "GET"]
    assert fetches[0].url.params["project"] == "checkout"
    assert fetches[1].headers["If-None-Match"] == ETAG_VALUE
