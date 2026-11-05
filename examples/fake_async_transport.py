"""
Test code that uses the async client without a server or HTTP mocking.

Builds on ``fake_transport.py``: only ``execute`` is ``async``.
"""

import pytest

from examples.fake_transport import FakeTransport, flag
from UnleashClient import Request, Response
from UnleashClient.clients.async_unleash_client import AsyncUnleashClient


class FakeAsyncTransport(FakeTransport):
    async def execute(self, request: Request) -> Response:  # type: ignore[override]
        return super().execute(request)


# A pytest test with pytest-asyncio, as it would look in your own test suite.
@pytest.mark.asyncio
async def test_new_checkout_is_on(tmp_path):
    transport = FakeAsyncTransport(flag("new-checkout", True))

    async with AsyncUnleashClient(
        "http://unleash.test/api",
        "my-app-tests",
        transport=transport,
        cache_directory=str(tmp_path),
    ) as client:
        assert client.is_enabled("new-checkout")
        assert not client.is_enabled("unknown-flag")
