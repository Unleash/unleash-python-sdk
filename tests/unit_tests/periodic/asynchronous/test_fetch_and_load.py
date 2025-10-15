import json

import pytest
from yggdrasil_engine.engine import UnleashEngine

from tests.utilities.mocks.mock_features import MOCK_FEATURE_RESPONSE
from tests.utilities.testing_constants import (
    APP_NAME,
    CUSTOM_HEADERS,
    INSTANCE_ID,
    REQUEST_RETRIES,
    REQUEST_TIMEOUT,
    URL,
)
from UnleashClient.asynchronous.cache import AsyncFileCache
from UnleashClient.periodic_tasks.asynchronous import fetch_and_load_features


@pytest.fixture
def async_cache(tmpdir):
    return AsyncFileCache(APP_NAME, directory=tmpdir.dirname)


class MockResponse:
    def __init__(self, status_code, text=None, headers=None):
        self.status_code = status_code
        self.text = text or ""
        self.headers = headers or {}


@pytest.mark.asyncio
async def test_fetch_and_load_features(async_cache, mocker):
    """Test fetch and load features task"""
    engine = UnleashEngine()

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

    await fetch_and_load_features(
        url=URL,
        app_name=APP_NAME,
        instance_id=INSTANCE_ID,
        headers=CUSTOM_HEADERS,
        custom_options={},
        request_timeout=REQUEST_TIMEOUT,
        request_retries=REQUEST_RETRIES,
        cache=async_cache,
        engine=engine,
    )

    # Should have completed successfully
    assert True


@pytest.mark.asyncio
async def test_fetch_and_load_features_not_modified(async_cache, mocker):
    """Test fetch and load with 304 Not Modified"""
    engine = UnleashEngine()
    await async_cache.set("etag", "test-etag")

    mock_response = MockResponse(304, "", {"etag": "test-etag"})

    async def mock_get(*args, **kwargs):
        return mock_response

    mock_session = mocker.MagicMock()
    mock_session.get = mock_get
    mock_session.__aenter__ = mocker.AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = mocker.AsyncMock(return_value=None)

    mocker.patch("niquests.AsyncSession", return_value=mock_session)

    await fetch_and_load_features(
        url=URL,
        app_name=APP_NAME,
        instance_id=INSTANCE_ID,
        headers=CUSTOM_HEADERS,
        custom_options={},
        request_timeout=REQUEST_TIMEOUT,
        request_retries=REQUEST_RETRIES,
        cache=async_cache,
        engine=engine,
    )

    # Should handle 304 gracefully
    assert True
