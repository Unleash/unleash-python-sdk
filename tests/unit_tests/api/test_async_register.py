import json
import pytest
from aioresponses import aioresponses
from aiohttp import ClientConnectionError
from yarl import URL as YURL

from UnleashClient.api.async_api import register_client_async
from UnleashClient.constants import REGISTER_URL, CLIENT_SPEC_VERSION

BASE_URL = "https://example.com"
FULL_REGISTER_URL = BASE_URL + REGISTER_URL

APP_NAME = "myapp"
INSTANCE_ID = "iid"
CONNECTION_ID = "cid-123"
METRICS_INTERVAL = 60
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
async def test_register_client_async(status, inject_exception, expected):
    with aioresponses() as m:
        if inject_exception is not None:
            m.post(FULL_REGISTER_URL, exception=inject_exception)
        else:
            m.post(FULL_REGISTER_URL, status=status)

        ok = await register_client_async(
            BASE_URL,
            APP_NAME,
            INSTANCE_ID,
            CONNECTION_ID,
            METRICS_INTERVAL,
            CUSTOM_HEADERS,
            CUSTOM_OPTIONS,
            supported_strategies={},
            request_timeout=REQUEST_TIMEOUT,
        )

        assert ok is expected

        assert ("POST", YURL(FULL_REGISTER_URL)) in m.requests
        assert len(m.requests[("POST", YURL(FULL_REGISTER_URL))]) == 1


@pytest.mark.asyncio
async def test_register_includes_metadata_async():
    with aioresponses() as m:
        m.post(FULL_REGISTER_URL, status=202)

        await register_client_async(
            BASE_URL,
            APP_NAME,
            INSTANCE_ID,
            CONNECTION_ID,
            METRICS_INTERVAL,
            CUSTOM_HEADERS,
            CUSTOM_OPTIONS,
            supported_strategies={},
            request_timeout=REQUEST_TIMEOUT,
        )

        call = m.requests[("POST", YURL(FULL_REGISTER_URL))][0]
        payload = json.loads(call.kwargs["data"])

        assert payload["connectionId"] == CONNECTION_ID
        assert payload["specVersion"] == CLIENT_SPEC_VERSION
        assert isinstance(payload.get("platformName"), str) and payload["platformName"]
        assert (
            isinstance(payload.get("platformVersion"), str)
            and payload["platformVersion"]
        )
        assert (
            isinstance(payload.get("yggdrasilVersion"), str)
            and payload["yggdrasilVersion"]
        )
