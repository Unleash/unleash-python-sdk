import platform
import sys
import uuid

import pytest

from tests.specification_tests.test_client_specs import TEST_DATA, TEST_NAMES
from tests.utilities.testing_constants import APP_NAME, URL
from UnleashClient.cache import FileCache
from UnleashClient.clients.async_unleash_client import AsyncUnleashClient


async def get_async_client(state, test_context=None, cache_directory=None):
    cache_kwargs = {}
    if cache_directory is not None:
        cache_kwargs["directory"] = str(cache_directory)

    cache = FileCache("MOCK_CACHE", **cache_kwargs)
    cache.bootstrap_from_dict(state)
    env = "default"
    if test_context is not None and "environment" in test_context:
        env = test_context["environment"]

    unleash_client = AsyncUnleashClient(
        url=URL,
        app_name=APP_NAME,
        instance_id="pytest_%s" % uuid.uuid4(),
        disable_metrics=True,
        disable_registration=True,
        cache=cache,
        environment=env,
    )

    await unleash_client.initialize_client(fetch_toggles=False)
    return unleash_client


@pytest.mark.skipif(
    sys.version_info < (3, 9) and platform.system() == "Windows",
    reason="Requires Python >= 3.9 on Windows",
)
@pytest.mark.asyncio
@pytest.mark.parametrize("spec", TEST_DATA, ids=TEST_NAMES)
async def test_spec(spec, tmp_path):
    state, test_data, is_variant_test = spec
    context = test_data.get("context")
    unleash_client = await get_async_client(state, context, tmp_path)
    try:
        if not is_variant_test:
            toggle_name = test_data["toggleName"]
            expected = test_data["expectedResult"]
            assert unleash_client.is_enabled(toggle_name, context) == expected
        else:
            toggle_name = test_data["toggleName"]
            expected = test_data["expectedResult"]
            variant = unleash_client.get_variant(toggle_name, context)
            assert variant == expected
    finally:
        await unleash_client.destroy()
