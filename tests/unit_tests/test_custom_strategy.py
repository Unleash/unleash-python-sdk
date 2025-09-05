import pytest
import responses

from tests.utilities.mocks import MOCK_CUSTOM_STRATEGY
from tests.utilities.testing_constants import APP_NAME, URL
from UnleashClient import UnleashClient
from UnleashClient.constants import FEATURES_URL, METRICS_URL, REGISTER_URL


class CatTest:
    def load_provisioning(self, parameters) -> list:
        return [x.strip() for x in parameters["sound"].split(",")]

    def apply(self, parameters: dict, context: dict = None) -> bool:
        """
        Turn on if I'm a cat.

        :return:
        """
        default_value = False

        parameters = self.load_provisioning(parameters)

        if "sound" in context.keys():
            default_value = context["sound"] in parameters

        return default_value


class DogTest:

    def apply(self, parameters: dict, context: dict = None) -> bool:
        """
        Turn on if I'm a dog.

        :return:
        """
        default_value = False

        parameters = [x.strip() for x in parameters["sound"].split(",")]

        if "sound" in context.keys():
            default_value = context["sound"] in parameters

        return default_value


@responses.activate
def test_uc_customstrategy_happypath(recwarn):
    responses.add(responses.POST, URL + REGISTER_URL, json={}, status=202)
    responses.add(
        responses.GET, URL + FEATURES_URL, json=MOCK_CUSTOM_STRATEGY, status=200
    )
    responses.add(responses.POST, URL + METRICS_URL, json={}, status=202)

    custom_strategies_dict = {"amIACat": CatTest()}

    unleash_client = UnleashClient(
        URL, APP_NAME, environment="prod", custom_strategies=custom_strategies_dict
    )

    unleash_client.initialize_client()

    # Check custom strategy.
    assert unleash_client.is_enabled("CustomToggle", {"sound": "meow"})
    assert not unleash_client.is_enabled("CustomToggle", {"sound": "bark"})
    unleash_client.destroy()


@responses.activate
def test_uc_customstrategy_deprecation_error():
    responses.add(responses.POST, URL + REGISTER_URL, json={}, status=202)
    responses.add(
        responses.GET, URL + FEATURES_URL, json=MOCK_CUSTOM_STRATEGY, status=200
    )
    responses.add(responses.POST, URL + METRICS_URL, json={}, status=202)

    custom_strategies_dict = {"amIACat": CatTest, "amIADog": DogTest}

    with pytest.raises(ValueError):
        UnleashClient(
            URL, APP_NAME, environment="prod", custom_strategies=custom_strategies_dict
        )


@responses.activate
def test_uc_customstrategy_safemulti():
    responses.add(responses.POST, URL + REGISTER_URL, json={}, status=202)
    responses.add(
        responses.GET, URL + FEATURES_URL, json=MOCK_CUSTOM_STRATEGY, status=200
    )
    responses.add(responses.POST, URL + METRICS_URL, json={}, status=202)

    custom_strategies_dict = {"amIACat": CatTest(), "amIADog": DogTest()}

    unleash_client = UnleashClient(
        URL, APP_NAME, environment="prod", custom_strategies=custom_strategies_dict
    )

    unleash_client.initialize_client()

    # Check a toggle that contains an outdated custom strategy and a default strategy.
    assert unleash_client.is_enabled("CustomToggleWarningMultiStrat", {"sound": "meow"})
    unleash_client.destroy()
