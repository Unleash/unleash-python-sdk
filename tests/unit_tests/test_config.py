import uuid

from UnleashClient.config import UnleashConfig

URL = "http://localhost:4242/api"
APP_NAME = "pytest"


def test_defaults():
    config = UnleashConfig(URL, APP_NAME)

    assert config.url == URL
    assert config.app_name == APP_NAME
    assert config.environment == "default"
    assert config.instance_id == "unleash-python-sdk"
    assert config.refresh_interval == 15
    assert config.refresh_jitter is None
    assert config.metrics_interval == 60
    assert config.metrics_jitter is None
    assert config.request_timeout == 30
    assert config.request_retries == 3
    assert config.disable_metrics is False
    assert config.disable_registration is False
    assert config.custom_headers == {}
    assert config.custom_options == {}
    assert config.custom_strategies == {}
    assert config.project_name is None
    assert config.verbose_log_level == 30
    assert config.sdk_flavor is None
    assert config.sdk_flavor_version is None
    assert config.experimental_mode == {"type": "polling"}


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
    # The client has never validated these, and UnleashClient exposes them
    # verbatim.  See test_UC_type_violation.
    config = UnleashConfig(
        URL, APP_NAME, refresh_interval="60", metrics_interval="60", request_timeout="9"
    )

    assert config.refresh_interval == "60"
    assert config.metrics_interval == "60"
    assert config.request_timeout == "9"


def test_connection_id_is_generated_and_unique():
    first = UnleashConfig(URL, APP_NAME)
    second = UnleashConfig(URL, APP_NAME)

    uuid.UUID(first.connection_id)
    assert first.connection_id != second.connection_id


def test_connection_id_can_be_supplied():
    config = UnleashConfig(URL, APP_NAME, connection_id="fixed-id")

    assert config.connection_id == "fixed-id"


def test_static_context():
    config = UnleashConfig(URL, APP_NAME, environment="unit")

    assert config.static_context == {"appName": APP_NAME, "environment": "unit"}
    assert config.static_context is config.static_context

    config.static_context["environment"] = "qa"
    assert config.static_context["environment"] == "qa"


def test_custom_headers_are_not_copied():
    headers = {"Authorization": "project:environment.hash"}
    config = UnleashConfig(URL, APP_NAME, custom_headers=headers)

    assert config.custom_headers is headers


def test_empty_custom_dicts_become_fresh_dicts():
    headers: dict = {}
    options: dict = {}
    strategies: dict = {}
    config = UnleashConfig(
        URL,
        APP_NAME,
        custom_headers=headers,
        custom_options=options,
        custom_strategies=strategies,
    )

    assert config.custom_headers is not headers
    assert config.custom_options is not options
    assert config.custom_strategies is not strategies


def test_custom_strategies_are_not_copied():
    # The client registers these objects on the engine as they were given.
    strategies = {"amIACat": object()}
    config = UnleashConfig(URL, APP_NAME, custom_strategies=strategies)

    assert config.custom_strategies is strategies


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
    config = UnleashConfig(URL, APP_NAME, environment="unit")

    assert config.impact_metrics_environment == "unit"


def test_impact_metrics_environment_is_taken_from_the_api_token():
    config = UnleashConfig(
        URL,
        APP_NAME,
        environment="unit",
        custom_headers={"Authorization": "project:production.hash"},
    )

    assert config.impact_metrics_environment == "production"


def test_impact_metrics_environment_falls_back_on_an_unparseable_token():
    config = UnleashConfig(
        URL,
        APP_NAME,
        environment="unit",
        custom_headers={"Authorization": "no-colon-here"},
    )

    assert config.impact_metrics_environment == "unit"


def test_instance_identifier_redacts_the_api_key():
    config = UnleashConfig(
        URL,
        APP_NAME,
        instance_id="123",
        custom_headers={"Authorization": "project:environment.abcdefghijklmnop"},
    )

    identifier = config.instance_identifier

    assert "abcdefghijklmnop" not in identifier
    # rpartition splits on the last colon, so everything after "project:" is
    # treated as the secret.
    assert identifier == ("apiKey:project:enviro...nop appName:pytest instanceId:123")


def test_instance_identifier_without_headers():
    config = UnleashConfig(URL, APP_NAME, instance_id="123")

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
        custom_headers={"Authorization": "project:environment.abcdefghijklmnop"},
    )

    assert "abcdefghijklmnop" not in repr(config)
