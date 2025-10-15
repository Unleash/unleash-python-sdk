"""
Integration tests for async Unleash client

These tests require a running Unleash instance.
Set UNLEASH_URL and UNLEASH_API_TOKEN environment variables to run them.
"""

import asyncio
import os

import pytest

from UnleashClient.asynchronous import AsyncUnleashClient

UNLEASH_URL = os.getenv("UNLEASH_URL", "http://localhost:4242/api")
UNLEASH_API_TOKEN = os.getenv("UNLEASH_API_TOKEN", "")
UNLEASH_APP_NAME = os.getenv("UNLEASH_APP_NAME", "agent-core-llmo")
UNLEASH_FEATURE_FLAG = os.getenv("UNLEASH_FEATURE_FLAG", "")
UNLEASH_VARIANT = os.getenv("UNLEASH_VARIANT", "")


@pytest.mark.integration
@pytest.mark.skipif(
    not UNLEASH_URL or not UNLEASH_API_TOKEN,
    reason="Integration test requires UNLEASH_URL and UNLEASH_API_TOKEN",
)
@pytest.mark.asyncio
async def test_async_integration():
    """Test basic async integration with Unleash server"""
    custom_headers = {"Authorization": UNLEASH_API_TOKEN}

    async with AsyncUnleashClient(
        url=UNLEASH_URL,
        app_name=UNLEASH_APP_NAME,
        custom_headers=custom_headers,
    ) as client:
        # Wait for initialization
        await asyncio.sleep(2)

        assert client.is_initialized

        # Test feature flag
        if UNLEASH_FEATURE_FLAG:
            is_enabled = client.is_enabled(UNLEASH_FEATURE_FLAG)
            assert isinstance(is_enabled, bool)
            assert is_enabled is True

        # Test variant
        if UNLEASH_VARIANT:
            variant = client.get_variant(UNLEASH_VARIANT)
            assert "name" in variant
            assert "enabled" in variant
