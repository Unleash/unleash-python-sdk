import json

import pytest

from tests.utilities.mocks.mock_features import MOCK_FEATURE_RESPONSE
from tests.utilities.testing_constants import (
    APP_NAME,
    CUSTOM_HEADERS,
    INSTANCE_ID,
    REQUEST_RETRIES,
    REQUEST_TIMEOUT,
    URL,
)
from UnleashClient.api.asynchronous import get_feature_toggles


class MockResponse:
    def __init__(self, status_code, text=None, headers=None):
        self.status_code = status_code
        self.text = text or ""
        self.headers = headers or {}


@pytest.mark.asyncio
async def test_get_feature_toggles_success(mocker):
    """Test successful feature toggle fetch"""
    mock_response = MockResponse(
        200, json.dumps(MOCK_FEATURE_RESPONSE), {"etag": "test-etag"}
    )

    async def mock_get(*args, **kwargs):
        return mock_response

    mock_session = mocker.MagicMock()
    mock_session.get = mock_get
    mock_session.__aenter__ = mocker.AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = mocker.AsyncMock(return_value=None)

    mocker.patch("niquests.AsyncSession", return_value=mock_session)

    features, etag = await get_feature_toggles(
        url=URL,
        app_name=APP_NAME,
        instance_id=INSTANCE_ID,
        headers=CUSTOM_HEADERS,
        custom_options={},
        request_timeout=REQUEST_TIMEOUT,
        request_retries=REQUEST_RETRIES,
    )

    assert features is not None
    assert etag == "test-etag"


@pytest.mark.asyncio
async def test_get_feature_toggles_not_modified(mocker):
    """Test 304 Not Modified response"""
    mock_response = MockResponse(304, "", {"etag": "test-etag"})

    async def mock_get(*args, **kwargs):
        return mock_response

    mock_session = mocker.MagicMock()
    mock_session.get = mock_get
    mock_session.__aenter__ = mocker.AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = mocker.AsyncMock(return_value=None)

    mocker.patch("niquests.AsyncSession", return_value=mock_session)

    features, etag = await get_feature_toggles(
        url=URL,
        app_name=APP_NAME,
        instance_id=INSTANCE_ID,
        headers=CUSTOM_HEADERS,
        custom_options={},
        request_timeout=REQUEST_TIMEOUT,
        request_retries=REQUEST_RETRIES,
        cached_etag="test-etag",
    )

    assert features is None
    assert etag == "test-etag"


@pytest.mark.asyncio
async def test_get_feature_toggles_error(mocker):
    """Test error handling"""
    mock_response = MockResponse(500)

    async def mock_get(*args, **kwargs):
        return mock_response

    mock_session = mocker.MagicMock()
    mock_session.get = mock_get
    mock_session.__aenter__ = mocker.AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = mocker.AsyncMock(return_value=None)

    mocker.patch("niquests.AsyncSession", return_value=mock_session)

    features, etag = await get_feature_toggles(
        url=URL,
        app_name=APP_NAME,
        instance_id=INSTANCE_ID,
        headers=CUSTOM_HEADERS,
        custom_options={},
        request_timeout=REQUEST_TIMEOUT,
        request_retries=REQUEST_RETRIES,
    )

    assert features is None
    assert etag == ""
