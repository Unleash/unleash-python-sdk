from UnleashClient.config import UnleashConfig
from UnleashClient.constants import CLIENT_SPEC_VERSION, SDK_NAME, SDK_VERSION
from UnleashClient.payloads import build_register_payload

URL = "http://localhost:4242/api"
APP_NAME = "pytest"


def build_config(**kwargs) -> UnleashConfig:
    return UnleashConfig(URL, APP_NAME, **kwargs)


def test_register_payload_identifies_the_client():
    config = build_config(instance_id="123", metrics_interval=30)

    payload = build_register_payload(config, {})

    assert payload["appName"] == APP_NAME
    assert payload["instanceId"] == "123"
    assert payload["connectionId"] == config.connection_id
    assert payload["sdkVersion"] == f"{SDK_NAME}:{SDK_VERSION}"
    assert payload["interval"] == 30


def test_register_payload_includes_metadata():
    payload = build_register_payload(build_config(), {})

    assert payload["yggdrasilVersion"] is not None
    assert payload["specVersion"] == CLIENT_SPEC_VERSION
    assert payload["platformName"] is not None
    assert payload["platformVersion"] is not None


def test_register_payload_sends_only_the_strategy_names():
    payload = build_register_payload(
        build_config(), {"default": object(), "gradualRollout": object()}
    )

    assert payload["strategies"] == ["default", "gradualRollout"]


def test_register_payload_includes_sdk_flavor_when_set():
    config = build_config(
        sdk_flavor="unleash-openfeature-python-provider", sdk_flavor_version="1.2.3"
    )

    payload = build_register_payload(config, {})

    assert payload["sdkFlavor"] == "unleash-openfeature-python-provider"
    assert payload["sdkFlavorVersion"] == "1.2.3"
    # additive: the SDK version is still present
    assert payload["sdkVersion"] is not None


def test_register_payload_omits_sdk_flavor_when_unset():
    payload = build_register_payload(build_config(), {})

    assert "sdkFlavor" not in payload
    assert "sdkFlavorVersion" not in payload


def test_register_payload_stamps_started_at_call_time():
    config = build_config()

    first = build_register_payload(config, {})
    second = build_register_payload(config, {})

    # `started` is the moment of the call, so a config reused across two
    # registrations does not carry a stale timestamp.
    assert first["started"] <= second["started"]
    assert first["started"].endswith("+00:00")
