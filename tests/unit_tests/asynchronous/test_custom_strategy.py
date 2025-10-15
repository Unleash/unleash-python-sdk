import pytest

from tests.utilities.testing_constants import APP_NAME, INSTANCE_ID, URL
from UnleashClient.asynchronous import AsyncFileCache, AsyncUnleashClient


class EnvironmentStrategy:
    def load_provisioning(self, parameters) -> list:
        return [x.strip() for x in parameters["environments"].split(",")]

    def apply(self, parameters: dict, context: dict = None) -> bool:
        """
        Turn on if environment is a match.
        """
        default_value = False
        parsed_provisioning = self.load_provisioning(parameters)

        if "environment" in context.keys():
            default_value = context["environment"] in parsed_provisioning

        return default_value


@pytest.fixture
def async_cache(tmpdir):
    return AsyncFileCache(APP_NAME, directory=tmpdir.dirname)


@pytest.mark.asyncio
async def test_async_client_custom_strategies(async_cache):
    """Test async client with custom strategies"""
    custom_strategies = {"Environment": EnvironmentStrategy()}

    client = AsyncUnleashClient(
        url=URL,
        app_name=APP_NAME,
        instance_id=INSTANCE_ID,
        cache=async_cache,
        custom_strategies=custom_strategies,
        disable_metrics=True,
        disable_registration=True,
    )

    assert "Environment" in client.strategy_mapping
    await client.destroy()
