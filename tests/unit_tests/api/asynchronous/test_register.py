import pytest

from tests.utilities.testing_constants import (
    APP_NAME,
    CUSTOM_HEADERS,
    INSTANCE_ID,
    METRICS_INTERVAL,
    REQUEST_TIMEOUT,
    URL,
)
from UnleashClient.api.asynchronous import register_client


class MockResponse:
    def __init__(self, status_code):
        self.status_code = status_code
        self.headers = {}
        self.text = ""


@pytest.mark.asyncio
async def test_register_client_success(mocker):
    """Test successful client registration"""
    mock_response = MockResponse(202)

    async def mock_post(*args, **kwargs):
        return mock_response

    mock_session = mocker.MagicMock()
    mock_session.post = mock_post
    mock_session.__aenter__ = mocker.AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = mocker.AsyncMock(return_value=None)

    mocker.patch("niquests.AsyncSession", return_value=mock_session)

    result = await register_client(
        url=URL,
        app_name=APP_NAME,
        instance_id=INSTANCE_ID,
        connection_id="test-connection",
        metrics_interval=METRICS_INTERVAL,
        headers=CUSTOM_HEADERS,
        custom_options={},
        supported_strategies={},
        request_timeout=REQUEST_TIMEOUT,
    )

    assert result is True


@pytest.mark.asyncio
async def test_register_client_failure(mocker):
    """Test client registration failure"""
    mock_response = MockResponse(500)

    async def mock_post(*args, **kwargs):
        return mock_response

    mock_session = mocker.MagicMock()
    mock_session.post = mock_post
    mock_session.__aenter__ = mocker.AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = mocker.AsyncMock(return_value=None)

    mocker.patch("niquests.AsyncSession", return_value=mock_session)

    result = await register_client(
        url=URL,
        app_name=APP_NAME,
        instance_id=INSTANCE_ID,
        connection_id="test-connection",
        metrics_interval=METRICS_INTERVAL,
        headers=CUSTOM_HEADERS,
        custom_options={},
        supported_strategies={},
        request_timeout=REQUEST_TIMEOUT,
    )

    assert result is False
