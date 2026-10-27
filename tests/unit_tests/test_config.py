import uuid
from dataclasses import FrozenInstanceError

import pytest

from UnleashClient.config import (
    HttpOptions,
    IdentityOptions,
    MetricsOptions,
    PollingOptions,
    UnleashConfig,
)

URL = "http://localhost:4242/api"
APP_NAME = "pytest"


def test_defaults():
    config = UnleashConfig(URL, APP_NAME)

    assert config.url == URL
    assert config.app_name == APP_NAME
    assert config.api_key is None
    assert config.identity == IdentityOptions(
        environment="default",
        instance_id="unleash-python-sdk",
        sdk_flavor=None,
        sdk_flavor_version=None,
    )
    assert config.mode == PollingOptions(interval=15, jitter=None, project_name=None)
    assert config.metrics == MetricsOptions(
        interval=60, jitter=None, disabled=False, disable_registration=False
    )
    assert config.http == HttpOptions(headers={}, options={}, timeout=30, retries=3)
    assert config.verbose_log_level == 30


def test_groups_left_as_none_get_their_defaults():
    config = UnleashConfig(
        URL,
        APP_NAME,
        identity=None,
        http=None,
        mode=None,
        metrics=None,
        connection_id="fixed-id",
    )

    assert config == UnleashConfig(URL, APP_NAME, connection_id="fixed-id")


def test_is_immutable():
    config = UnleashConfig(URL, APP_NAME)

    with pytest.raises(FrozenInstanceError):
        config.url = "http://elsewhere:4242/api"
    with pytest.raises(FrozenInstanceError):
        config.mode.interval = 1
    with pytest.raises(FrozenInstanceError):
        config.http.timeout = 1
    with pytest.raises(FrozenInstanceError):
        config.metrics.disabled = True
    with pytest.raises(FrozenInstanceError):
        config.identity.environment = "production"


def test_options_are_shared_between_configs_without_copying():
    http = HttpOptions(headers={"X-Custom": "header"})

    first = UnleashConfig(URL, APP_NAME, http=http)
    second = UnleashConfig(URL, "other", http=http)

    assert first.http is second.http


def test_url_is_rstripped():
    assert UnleashConfig("http://localhost:4242/api/", APP_NAME).url == URL
    assert UnleashConfig("http://localhost:4242/api///", APP_NAME).url == URL
    assert UnleashConfig(URL, APP_NAME).url == URL


def test_jitters_are_int_coerced():
    config = UnleashConfig(
        URL,
        APP_NAME,
        mode=PollingOptions(jitter=5.9),
        metrics=MetricsOptions(jitter="7"),
    )

    assert config.mode.jitter == 5
    assert config.metrics.jitter == 7


def test_zero_jitter_is_preserved_and_not_confused_with_none():
    config = UnleashConfig(
        URL,
        APP_NAME,
        mode=PollingOptions(jitter=0),
        metrics=MetricsOptions(jitter=0),
    )

    assert config.mode.jitter == 0
    assert config.metrics.jitter == 0
    assert UnleashConfig(URL, APP_NAME).mode.jitter is None


def test_no_other_coercion():
    # The client has never validated these.
    config = UnleashConfig(
        URL,
        APP_NAME,
        http=HttpOptions(timeout="9"),
        mode=PollingOptions(interval="60"),
        metrics=MetricsOptions(interval="60"),
    )

    assert config.mode.interval == "60"
    assert config.metrics.interval == "60"
    assert config.http.timeout == "9"


def test_connection_id_is_generated_and_unique():
    first = UnleashConfig(URL, APP_NAME)
    second = UnleashConfig(URL, APP_NAME)

    uuid.UUID(first.connection_id)
    assert first.connection_id != second.connection_id


def test_connection_id_can_be_supplied():
    config = UnleashConfig(URL, APP_NAME, connection_id="fixed-id")

    assert config.connection_id == "fixed-id"


def test_static_context():
    config = UnleashConfig(URL, APP_NAME, identity=IdentityOptions(environment="unit"))

    assert config.static_context == {"appName": APP_NAME, "environment": "unit"}

    # A fresh dict every time, so a caller can't change the config through it.
    config.static_context["environment"] = "qa"
    assert config.static_context["environment"] == "unit"


def test_headers_and_options_are_copied():
    headers = {"X-Custom": "header"}
    options = {"verify": False}
    http = HttpOptions(headers=headers, options=options)

    headers["extra"] = "header"
    options["extra"] = "option"

    assert http.headers == {"X-Custom": "header"}
    assert http.options == {"verify": False}


def test_missing_headers_and_options_become_empty_dicts():
    http = HttpOptions(headers=None, options=None)

    assert http.headers == {}
    assert http.options == {}


def test_headers_and_options_are_read_only():
    http = HttpOptions(headers={"X-Custom": "header"}, options={"verify": True})

    with pytest.raises(TypeError):
        http.headers["X-Custom"] = "changed"
    with pytest.raises(TypeError):
        http.options["verify"] = False

    assert http.headers == {"X-Custom": "header"}
    assert http.options == {"verify": True}


@pytest.mark.parametrize("name", ["Authorization", "authorization", "AUTHORIZATION"])
def test_an_authorization_header_is_rejected(name):
    with pytest.raises(ValueError, match="api_key"):
        HttpOptions(headers={name: "project:environment.hash"})


def test_an_authorization_header_cannot_be_added_later():
    http = HttpOptions(headers={"X-Custom": "header"})

    with pytest.raises(TypeError):
        http.headers["Authorization"] = "project:environment.hash"


@pytest.mark.parametrize("mode", ["streaming", "polling", {"interval": 5}])
def test_a_mode_of_the_wrong_type_falls_back_on_polling(mode, caplog):
    config = UnleashConfig(URL, APP_NAME, mode=mode)

    assert config.mode == PollingOptions()
    assert "Polling instead" in caplog.text


def test_metrics_interval_str_millis():
    assert UnleashConfig(URL, APP_NAME).metrics_interval_str_millis == "60000"
    assert (
        UnleashConfig(
            URL, APP_NAME, metrics=MetricsOptions(interval=2)
        ).metrics_interval_str_millis
        == "2000"
    )


def test_impact_metrics_environment_defaults_to_environment():
    config = UnleashConfig(URL, APP_NAME, identity=IdentityOptions(environment="unit"))

    assert config.impact_metrics_environment == "unit"


def test_impact_metrics_environment_is_taken_from_the_api_token():
    config = UnleashConfig(
        URL,
        APP_NAME,
        identity=IdentityOptions(environment="unit"),
        api_key="project:production.hash",
    )

    assert config.impact_metrics_environment == "production"


def test_impact_metrics_environment_falls_back_on_an_unparseable_token():
    config = UnleashConfig(
        URL,
        APP_NAME,
        identity=IdentityOptions(environment="unit"),
        api_key="no-colon-here",
    )

    assert config.impact_metrics_environment == "unit"


def test_instance_identifier_redacts_the_api_key():
    config = UnleashConfig(
        URL,
        APP_NAME,
        identity=IdentityOptions(instance_id="123"),
        api_key="project:environment.abcdefghijklmnop",
    )

    identifier = config.instance_identifier

    assert "abcdefghijklmnop" not in identifier
    # rpartition splits on the last colon, so everything after "project:" is
    # treated as the secret.
    assert identifier == ("apiKey:project:enviro...nop appName:pytest instanceId:123")


def test_instance_identifier_without_an_api_key():
    config = UnleashConfig(URL, APP_NAME, identity=IdentityOptions(instance_id="123"))

    assert config.instance_identifier == ("apiKey:None appName:pytest instanceId:123")


def test_repr_does_not_leak_the_api_key():
    config = UnleashConfig(
        URL,
        APP_NAME,
        api_key="project:environment.abcdefghijklmnop",
    )

    assert "abcdefghijklmnop" not in repr(config)
