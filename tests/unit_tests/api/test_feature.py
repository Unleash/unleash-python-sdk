import json

import responses
from pytest import mark, param

from tests.utilities.mocks.mock_features import (
    MOCK_FEATURE_RESPONSE,
    MOCK_FEATURE_RESPONSE_PROJECT,
)
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
from UnleashClient.api.sync_api import get_feature_toggles
from UnleashClient.constants import FEATURES_URL

FULL_FEATURE_URL = URL + FEATURES_URL


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
def test_get_feature_toggle(response, status, calls, expected):
    responses.add(
        responses.GET,
        FULL_FEATURE_URL,
        json=response,
        status=status,
        headers={"etag": ETAG_VALUE},
    )

    (result, etag) = get_feature_toggles(
        URL,
        APP_NAME,
        INSTANCE_ID,
        CUSTOM_HEADERS,
        CUSTOM_OPTIONS,
        REQUEST_TIMEOUT,
        REQUEST_RETRIES,
    )

    assert len(responses.calls) == calls
    assert expected(result)


@responses.activate
def test_get_feature_toggle_project():
    responses.add(
        responses.GET,
        PROJECT_URL,
        json=MOCK_FEATURE_RESPONSE_PROJECT,
        status=200,
        headers={"etag": ETAG_VALUE},
    )

    (result, etag) = get_feature_toggles(
        URL,
        APP_NAME,
        INSTANCE_ID,
        CUSTOM_HEADERS,
        CUSTOM_OPTIONS,
        REQUEST_TIMEOUT,
        REQUEST_RETRIES,
        PROJECT_NAME,
    )

    assert len(responses.calls) == 1
    assert len(json.loads(result)["features"]) == 1
    assert etag == ETAG_VALUE


@responses.activate
def test_get_feature_toggle_failed_etag():
    responses.add(
        responses.GET, PROJECT_URL, json={}, status=500, headers={"etag": ETAG_VALUE}
    )

    (result, etag) = get_feature_toggles(
        URL,
        APP_NAME,
        INSTANCE_ID,
        CUSTOM_HEADERS,
        CUSTOM_OPTIONS,
        REQUEST_TIMEOUT,
        REQUEST_RETRIES,
        PROJECT_NAME,
    )

    assert len(responses.calls) == 4
    assert not etag


@responses.activate
def test_get_feature_toggle_etag_present():
    responses.add(responses.GET, PROJECT_URL, status=304, headers={"etag": ETAG_VALUE})

    (result, etag) = get_feature_toggles(
        URL,
        APP_NAME,
        INSTANCE_ID,
        CUSTOM_HEADERS,
        CUSTOM_OPTIONS,
        REQUEST_TIMEOUT,
        REQUEST_RETRIES,
        PROJECT_NAME,
        ETAG_VALUE,
    )

    assert len(responses.calls) == 1
    assert not result
    assert responses.calls[0].request.headers["If-None-Match"] == ETAG_VALUE
    assert etag == ETAG_VALUE


@responses.activate
def test_get_feature_toggle_retries():
    responses.add(responses.GET, PROJECT_URL, json={}, status=500)
    responses.add(
        responses.GET,
        PROJECT_URL,
        json=MOCK_FEATURE_RESPONSE_PROJECT,
        status=200,
        headers={"etag": ETAG_VALUE},
    )

    (result, etag) = get_feature_toggles(
        URL,
        APP_NAME,
        INSTANCE_ID,
        CUSTOM_HEADERS,
        CUSTOM_OPTIONS,
        REQUEST_TIMEOUT,
        REQUEST_RETRIES,
        PROJECT_NAME,
        ETAG_VALUE,
    )

    assert len(responses.calls) == 2
    assert len(json.loads(result)["features"]) == 1
    assert etag == ETAG_VALUE
