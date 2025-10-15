import pytest

from tests.utilities.testing_constants import (
    CUSTOM_HEADERS,
    REQUEST_TIMEOUT,
    URL,
)
from UnleashClient.api.asynchronous import send_metrics


class MockResponse:
    def __init__(self, status_code):
        self.status_code = status_code
        self.headers = {}
        self.text = ""


@pytest.mark.asyncio
async def test_send_metrics_success(mocker):
    """Test successful metrics send"""
    mock_response = MockResponse(202)

    async def mock_post(*args, **kwargs):
        return mock_response

    mock_session = mocker.MagicMock()
    mock_session.post = mock_post
    mock_session.__aenter__ = mocker.AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = mocker.AsyncMock(return_value=None)

    mocker.patch("niquests.AsyncSession", return_value=mock_session)

    result = await send_metrics(
        url=URL,
        request_body={"bucket": {}},
        headers=CUSTOM_HEADERS,
        custom_options={},
        request_timeout=REQUEST_TIMEOUT,
    )

    assert result is True


@pytest.mark.asyncio
async def test_send_metrics_failure(mocker):
    """Test metrics send failure"""
    mock_response = MockResponse(500)

    async def mock_post(*args, **kwargs):
        return mock_response

    mock_session = mocker.MagicMock()
    mock_session.post = mock_post
    mock_session.__aenter__ = mocker.AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = mocker.AsyncMock(return_value=None)

    mocker.patch("niquests.AsyncSession", return_value=mock_session)

    result = await send_metrics(
        url=URL,
        request_body={"bucket": {}},
        headers=CUSTOM_HEADERS,
        custom_options={},
        request_timeout=REQUEST_TIMEOUT,
    )

    assert result is False
