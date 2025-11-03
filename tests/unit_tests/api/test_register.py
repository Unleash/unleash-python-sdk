import json

import responses
from pytest import mark, param
from requests import ConnectionError

from tests.utilities.testing_constants import (
    APP_NAME,
    CONNECTION_ID,
    CUSTOM_HEADERS,
    CUSTOM_OPTIONS,
    INSTANCE_ID,
    METRICS_INTERVAL,
    REQUEST_TIMEOUT,
    URL,
)
from UnleashClient.api.sync_api import register_client
from UnleashClient.constants import CLIENT_SPEC_VERSION, REGISTER_URL

FULL_REGISTER_URL = URL + REGISTER_URL


@responses.activate
@mark.parametrize(
    "payload,status,expected",
    (
        param({"json": {}}, 202, True, id="success"),
        param({"json": {}}, 500, False, id="failure"),
        param(
            {"body": ConnectionError("Test connection error")},
            200,
            False,
            id="exception",
        ),
    ),
)
def test_register_client(payload, status, expected):
    responses.add(responses.POST, FULL_REGISTER_URL, **payload, status=status)

    result = register_client(
        URL,
        APP_NAME,
        INSTANCE_ID,
        CONNECTION_ID,
        METRICS_INTERVAL,
        CUSTOM_HEADERS,
        CUSTOM_OPTIONS,
        {},
        REQUEST_TIMEOUT,
    )

    assert len(responses.calls) == 1
    assert result is expected


@responses.activate
def test_register_includes_metadata():
    responses.add(responses.POST, FULL_REGISTER_URL, json={}, status=202)

    register_client(
        URL,
        APP_NAME,
        INSTANCE_ID,
        CONNECTION_ID,
        METRICS_INTERVAL,
        CUSTOM_HEADERS,
        CUSTOM_OPTIONS,
        {},
        REQUEST_TIMEOUT,
    )

    assert len(responses.calls) == 1
    request = json.loads(responses.calls[0].request.body)

    assert request["yggdrasilVersion"] is not None
    assert request["specVersion"] == CLIENT_SPEC_VERSION
    assert request["connectionId"] == CONNECTION_ID
    assert request["platformName"] is not None
    assert request["platformVersion"] is not None
