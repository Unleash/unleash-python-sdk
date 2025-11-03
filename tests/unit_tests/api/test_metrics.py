import json

import responses
from pytest import mark, param
from requests import ConnectionError

from tests.utilities.mocks.mock_metrics import MOCK_METRICS_REQUEST
from tests.utilities.testing_constants import (
    CUSTOM_HEADERS,
    CUSTOM_OPTIONS,
    REQUEST_TIMEOUT,
    URL,
)
from UnleashClient.api.sync_api import send_metrics
from UnleashClient.constants import METRICS_URL

FULL_METRICS_URL = URL + METRICS_URL


@responses.activate
@mark.parametrize(
    "payload,status,expected",
    (
        param({"json": {}}, 202, lambda result: result, id="success"),
        param({"json": {}}, 500, lambda result: not result, id="failure"),
        param(
            {"body": ConnectionError("Test connection error.")},
            200,
            lambda result: not result,
            id="exception",
        ),
    ),
)
def test_send_metrics(payload, status, expected):
    responses.add(responses.POST, FULL_METRICS_URL, **payload, status=status)

    result = send_metrics(
        URL, MOCK_METRICS_REQUEST, CUSTOM_HEADERS, CUSTOM_OPTIONS, REQUEST_TIMEOUT
    )

    request = json.loads(responses.calls[0].request.body)

    assert len(responses.calls) == 1
    assert expected(result)

    assert request["connectionId"] == MOCK_METRICS_REQUEST.get("connectionId")
