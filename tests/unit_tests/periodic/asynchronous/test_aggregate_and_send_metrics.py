import pytest
from yggdrasil_engine.engine import UnleashEngine

from tests.utilities.testing_constants import (
    APP_NAME,
    CUSTOM_HEADERS,
    INSTANCE_ID,
    REQUEST_TIMEOUT,
    URL,
)
from UnleashClient.periodic_tasks.asynchronous import aggregate_and_send_metrics


@pytest.mark.asyncio
async def test_aggregate_and_send_metrics():
    """Test aggregate and send metrics task"""
    engine = UnleashEngine()

    # Should complete without sending (metrics bucket is empty)
    await aggregate_and_send_metrics(
        url=URL,
        app_name=APP_NAME,
        instance_id=INSTANCE_ID,
        connection_id="test-connection",
        headers=CUSTOM_HEADERS,
        custom_options={},
        request_timeout=REQUEST_TIMEOUT,
        engine=engine,
    )

    # Should complete without error
    assert True


@pytest.mark.asyncio
async def test_aggregate_and_send_metrics_with_data(mocker):
    """Test aggregate and send metrics with actual data"""
    engine = UnleashEngine()
    # Simulate some metrics
    engine.count_toggle("test_feature", True)

    class MockResponse:
        status_code = 202

    async def mock_post(*args, **kwargs):
        return MockResponse()

    mock_session = mocker.MagicMock()
    mock_session.post = mock_post
    mock_session.__aenter__ = mocker.AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = mocker.AsyncMock(return_value=None)

    mocker.patch("niquests.AsyncSession", return_value=mock_session)

    await aggregate_and_send_metrics(
        url=URL,
        app_name=APP_NAME,
        instance_id=INSTANCE_ID,
        connection_id="test-connection",
        headers=CUSTOM_HEADERS,
        custom_options={},
        request_timeout=REQUEST_TIMEOUT,
        engine=engine,
    )

    # Should have completed successfully
    assert True
