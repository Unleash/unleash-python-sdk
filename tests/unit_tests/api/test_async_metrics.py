import json
import pytest
from aioresponses import aioresponses
from aiohttp import ClientConnectionError
from yarl import URL as YURL

from UnleashClient.api.async_api import send_metrics_async
from UnleashClient.constants import METRICS_URL

URL = "https://example.com"
FULL_METRICS_URL = URL + METRICS_URL

MOCK_METRICS_REQUEST = {
    "appName": "myapp",
    "instanceId": "iid",
    "connectionId": "cid-123",
    "bucket": {
        "start": "2020-01-01T00:00:00Z",
        "stop": "2020-01-01T00:01:00Z",
        "toggles": {},
    },
}

CUSTOM_HEADERS = {"Authorization": "secret"}
CUSTOM_OPTIONS = {}
REQUEST_TIMEOUT = 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,inject_exception,expected",
    [
        (202, None, True),
        (500, None, False),
        (200, ClientConnectionError(), False),
    ],
)
async def test_send_metrics_async(status, inject_exception, expected):
    with aioresponses() as m:
        if inject_exception is not None:
            m.post(FULL_METRICS_URL, exception=inject_exception)
        else:
            m.post(FULL_METRICS_URL, status=status)

        ok = await send_metrics_async(
            URL, MOCK_METRICS_REQUEST, CUSTOM_HEADERS, CUSTOM_OPTIONS, REQUEST_TIMEOUT
        )

        assert ok is expected
        # Ensure we actually attempted one POST
        assert ("POST", YURL(FULL_METRICS_URL)) in m.requests
        call = m.requests[("POST", YURL(FULL_METRICS_URL))][0]
        sent = json.loads(call.kwargs["data"])
        assert sent["connectionId"] == MOCK_METRICS_REQUEST["connectionId"]