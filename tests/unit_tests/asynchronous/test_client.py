import asyncio
import json

import pytest

from tests.utilities.mocks.mock_features import MOCK_FEATURE_RESPONSE
from tests.utilities.testing_constants import (
    APP_NAME,
    INSTANCE_ID,
    URL,
)
from UnleashClient.asynchronous import AsyncFileCache, AsyncUnleashClient


@pytest.fixture
def async_cache(tmpdir):
    return AsyncFileCache(APP_NAME, directory=tmpdir.dirname)


@pytest.mark.asyncio
async def test_async_client_initialization(async_cache):
    """Test basic async client initialization"""
    client = AsyncUnleashClient(
        url=URL,
        app_name=APP_NAME,
        instance_id=INSTANCE_ID,
        cache=async_cache,
        disable_metrics=True,
        disable_registration=True,
    )

    assert client.unleash_url == URL
    assert client.unleash_app_name == APP_NAME
    assert client.unleash_instance_id == INSTANCE_ID
    assert not client.is_initialized


@pytest.mark.asyncio
async def test_async_client_context_manager(async_cache, mocker):
    """Test async client as context manager"""

    class MockResponse:
        def __init__(self, status_code, text=None, headers=None):
            self.status_code = status_code
            self.text = text or ""
            self.headers = headers or {}

    async def mock_post(*args, **kwargs):
        return MockResponse(202)

    async def mock_get(*args, **kwargs):
        return MockResponse(200, json.dumps(MOCK_FEATURE_RESPONSE), {"etag": "test"})

    mock_session = mocker.MagicMock()
    mock_session.post = mock_post
    mock_session.get = mock_get
    mock_session.__aenter__ = mocker.AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = mocker.AsyncMock(return_value=None)

    mocker.patch("niquests.AsyncSession", return_value=mock_session)

    async with AsyncUnleashClient(
        url=URL,
        app_name=APP_NAME,
        instance_id=INSTANCE_ID,
        cache=async_cache,
        disable_metrics=True,
    ) as client:
        # Give it a moment to initialize
        await asyncio.sleep(0.1)
        assert client.is_initialized


@pytest.mark.asyncio
async def test_async_client_is_enabled(async_cache):
    """Test is_enabled method"""
    client = AsyncUnleashClient(
        url=URL,
        app_name=APP_NAME,
        instance_id=INSTANCE_ID,
        cache=async_cache,
        disable_metrics=True,
        disable_registration=True,
    )

    # Test with uninitialized client
    result = client.is_enabled("test_feature")
    assert result is False

    await client.destroy()


@pytest.mark.asyncio
async def test_async_client_get_variant(async_cache):
    """Test get_variant method"""
    client = AsyncUnleashClient(
        url=URL,
        app_name=APP_NAME,
        instance_id=INSTANCE_ID,
        cache=async_cache,
        disable_metrics=True,
        disable_registration=True,
    )

    # Test with uninitialized client
    variant = client.get_variant("test_feature")
    assert variant["name"] == "disabled"
    assert variant["enabled"] is False

    await client.destroy()


@pytest.mark.asyncio
async def test_async_client_feature_definitions(async_cache):
    """Test feature_definitions method"""
    client = AsyncUnleashClient(
        url=URL,
        app_name=APP_NAME,
        instance_id=INSTANCE_ID,
        cache=async_cache,
        disable_metrics=True,
        disable_registration=True,
    )

    definitions = client.feature_definitions()
    assert isinstance(definitions, dict)

    await client.destroy()
