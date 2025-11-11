import json

import pytest
from aioresponses import aioresponses

from UnleashClient.api.async_api import get_feature_toggles_async
from UnleashClient.constants import FEATURES_URL

URL = "https://example.com"
FULL_FEATURE_URL = URL + FEATURES_URL

APP_NAME = "myapp"
INSTANCE_ID = "iid"
CUSTOM_HEADERS = {"Authorization": "secret"}
CUSTOM_OPTIONS = {}
REQUEST_TIMEOUT = 3
REQUEST_RETRIES = 3
ETAG_VALUE = "W/123"
PROJECT_NAME = "default"

MOCK_FEATURE_RESPONSE = {"version": 1, "features": []}
PROJECT_URL = f"{FULL_FEATURE_URL}?project={PROJECT_NAME}"


@pytest.mark.asyncio
async def test_get_feature_toggles_success():
    with aioresponses() as m:
        m.get(
            FULL_FEATURE_URL,
            status=200,
            payload=MOCK_FEATURE_RESPONSE,
            headers={"etag": ETAG_VALUE},
        )

        body, etag = await get_feature_toggles_async(
            URL,
            APP_NAME,
            INSTANCE_ID,
            CUSTOM_HEADERS,
            CUSTOM_OPTIONS,
            REQUEST_TIMEOUT,
            REQUEST_RETRIES,
        )

    assert json.loads(body)["version"] == 1
    assert etag == ETAG_VALUE


@pytest.mark.asyncio
async def test_get_feature_toggles_project_and_etag_present():
    with aioresponses() as m:
        m.get(PROJECT_URL, status=304, headers={"etag": ETAG_VALUE})

        body, etag = await get_feature_toggles_async(
            URL,
            APP_NAME,
            INSTANCE_ID,
            CUSTOM_HEADERS,
            CUSTOM_OPTIONS,
            REQUEST_TIMEOUT,
            REQUEST_RETRIES,
            project=PROJECT_NAME,
            cached_etag=ETAG_VALUE,
        )

    assert body is None
    assert etag == ETAG_VALUE


@pytest.mark.asyncio
async def test_get_feature_toggles_retries_then_success():
    with aioresponses() as m:
        m.get(PROJECT_URL, status=500)  # first attempt
        m.get(
            PROJECT_URL,
            status=200,
            payload=MOCK_FEATURE_RESPONSE,
            headers={"etag": ETAG_VALUE},
        )

        body, etag = await get_feature_toggles_async(
            URL,
            APP_NAME,
            INSTANCE_ID,
            CUSTOM_HEADERS,
            CUSTOM_OPTIONS,
            REQUEST_TIMEOUT,
            request_retries=1,
            project=PROJECT_NAME,
            cached_etag=ETAG_VALUE,
        )

    assert json.loads(body)["version"] == 1
    assert etag == ETAG_VALUE


@pytest.mark.asyncio
async def test_get_feature_toggles_failure_after_retries():
    with aioresponses() as m:
        m.get(PROJECT_URL, status=500)
        m.get(PROJECT_URL, status=500)
        body, etag = await get_feature_toggles_async(
            URL,
            APP_NAME,
            INSTANCE_ID,
            CUSTOM_HEADERS,
            CUSTOM_OPTIONS,
            REQUEST_TIMEOUT,
            request_retries=1,
            project=PROJECT_NAME,
        )
    assert body is None
    assert etag == ""
