import uuid
from dataclasses import FrozenInstanceError

import pytest

from UnleashClient.config import HttpOptions, IdentityOptions, UnleashConfig

URL = "http://localhost:4242/api"
APP_NAME = "pytest"


def test_defaults():
    config = UnleashConfig(URL, APP_NAME)

    assert config.url == URL
    assert config.app_name == APP_NAME
    assert config.identity == IdentityOptions(
        environment="default",
        instance_id="unleash-python-sdk",
        sdk_flavor=None,
        sdk_flavor_version=None,
    )
    assert config.refresh_interval == 15
    assert config.refresh_jitter is None
    assert config.metrics_interval == 60
    assert config.metrics_jitter is None
    assert config.http == HttpOptions(headers={}, options={}, timeout=30, retries=3)
    assert config.disable_metrics is False
    assert config.disable_registration is False
    assert config.project_name is None
    assert config.verbose_log_level == 30
    assert config.experimental_mode == {"type": "polling"}


def test_is_immutable():
    config = UnleashConfig(URL, APP_NAME)

    with pytest.raises(FrozenInstanceError):
        config.url = "http://elsewhere:4242/api"
    with pytest.raises(FrozenInstanceError):
        config.refresh_interval = 1
    with pytest.raises(FrozenInstanceError):
        config.http.timeout = 1
    with pytest.raises(FrozenInstanceError):
        config.identity.environment = "production"


def test_url_is_rstripped():
    assert UnleashConfig("http://localhost:4242/api/", APP_NAME).url == URL
    assert UnleashConfig("http://localhost:4242/api///", APP_NAME).url == URL
    assert UnleashConfig(URL, APP_NAME).url == URL


def test_jitters_are_int_coerced():
    config = UnleashConfig(URL, APP_NAME, refresh_jitter=5.9, metrics_jitter="7")

    assert config.refresh_jitter == 5
    assert config.metrics_jitter == 7


def test_zero_jitter_is_preserved_and_not_confused_with_none():
    config = UnleashConfig(URL, APP_NAME, refresh_jitter=0, metrics_jitter=0)

    assert config.refresh_jitter == 0
    assert config.metrics_jitter == 0
    assert UnleashConfig(URL, APP_NAME).refresh_jitter is None


def test_no_other_coercion():
    # The client has never validated these.
    config = UnleashConfig(
        URL,
        APP_NAME,
        http=HttpOptions(timeout="9"),
        refresh_interval="60",
        metrics_interval="60",
    )

    assert config.refresh_interval == "60"
    assert config.metrics_interval == "60"
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
    headers = {"Authorization": "project:environment.hash"}
    options = {"verify": False}
    http = HttpOptions(headers=headers, options=options)

    headers["extra"] = "header"
    options["extra"] = "option"

    assert http.headers == {"Authorization": "project:environment.hash"}
    assert http.options == {"verify": False}


def test_missing_headers_and_options_become_empty_dicts():
    http = HttpOptions(headers=None, options=None)

    assert http.headers == {}
    assert http.options == {}


def test_refresh_interval_str_millis():
    assert UnleashConfig(URL, APP_NAME).refresh_interval_str_millis == "15000"
    assert (
        UnleashConfig(URL, APP_NAME, refresh_interval=2).refresh_interval_str_millis
        == "2000"
    )


def test_metrics_interval_str_millis():
    assert UnleashConfig(URL, APP_NAME).metrics_interval_str_millis == "60000"
    assert (
        UnleashConfig(URL, APP_NAME, metrics_interval=2).metrics_interval_str_millis
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
        http=HttpOptions(headers={"Authorization": "project:production.hash"}),
    )

    assert config.impact_metrics_environment == "production"


def test_impact_metrics_environment_falls_back_on_an_unparseable_token():
    config = UnleashConfig(
        URL,
        APP_NAME,
        identity=IdentityOptions(environment="unit"),
        http=HttpOptions(headers={"Authorization": "no-colon-here"}),
    )

    assert config.impact_metrics_environment == "unit"


def test_instance_identifier_redacts_the_api_key():
    config = UnleashConfig(
        URL,
        APP_NAME,
        identity=IdentityOptions(instance_id="123"),
        http=HttpOptions(
            headers={"Authorization": "project:environment.abcdefghijklmnop"}
        ),
    )

    identifier = config.instance_identifier

    assert "abcdefghijklmnop" not in identifier
    # rpartition splits on the last colon, so everything after "project:" is
    # treated as the secret.
    assert identifier == ("apiKey:project:enviro...nop appName:pytest instanceId:123")


def test_instance_identifier_without_headers():
    config = UnleashConfig(URL, APP_NAME, identity=IdentityOptions(instance_id="123"))

    assert config.instance_identifier == ("apiKey:None appName:pytest instanceId:123")


def test_experimental_mode_is_passed_through():
    mode = {"type": "streaming", "somethingElse": True}
    config = UnleashConfig(URL, APP_NAME, experimental_mode=mode)

    assert config.experimental_mode is mode
    assert config.mode == "streaming"


def test_mode_defaults_to_polling():
    assert UnleashConfig(URL, APP_NAME).mode == "polling"
    assert UnleashConfig(URL, APP_NAME, experimental_mode={}).mode == "polling"


def test_repr_does_not_leak_the_api_key():
    config = UnleashConfig(
        URL,
        APP_NAME,
        http=HttpOptions(
            headers={"Authorization": "project:environment.abcdefghijklmnop"}
        ),
    )

    assert "abcdefghijklmnop" not in repr(config)
