from UnleashClient.config import UnleashConfig
from UnleashClient.constants import (
    APPLICATION_HEADERS,
    CLIENT_SPEC_VERSION,
    SDK_NAME,
    SDK_VERSION,
)
from UnleashClient.headers import HeaderFactory

TEST_URL = "http://localhost:4242/api"
TEST_APP_NAME = "pytest"


def build_factory(**kwargs) -> HeaderFactory:
    return HeaderFactory(UnleashConfig(TEST_URL, TEST_APP_NAME, **kwargs))


def test_base_carries_the_identification_headers():
    config = UnleashConfig(TEST_URL, TEST_APP_NAME, instance_id="123")
    factory = HeaderFactory(config)

    headers = factory.base()

    assert headers["unleash-connection-id"] == config.connection_id
    assert headers["unleash-appname"] == TEST_APP_NAME
    assert headers["unleash-instanceid"] == "123"
    assert headers["unleash-sdk"] == f"{SDK_NAME}:{SDK_VERSION}"


def test_base_carries_the_application_headers():
    factory = build_factory()

    headers = factory.base()

    assert headers["Content-Type"] == "application/json"
    assert headers["Unleash-Client-Spec"] == CLIENT_SPEC_VERSION


def test_base_includes_the_custom_headers():
    factory = build_factory(custom_headers={"Authorization": "project:env.hash"})

    headers = factory.base()

    assert headers["Authorization"] == "project:env.hash"


def test_application_headers_win_over_custom_headers():
    factory = build_factory(custom_headers={"Content-Type": "application/xml"})

    headers = factory.base()

    assert headers["Content-Type"] == "application/json"


def test_custom_headers_cannot_override_the_identification_headers():
    factory = build_factory(custom_headers={"unleash-appname": "spoofed"})

    headers = factory.base()

    assert headers["unleash-appname"] == TEST_APP_NAME


def test_custom_headers_are_read_on_every_call():
    # UnleashClient.unleash_custom_headers has a setter, so a client can swap
    # the dict out after the factory was constructed.
    config = UnleashConfig(TEST_URL, TEST_APP_NAME)
    factory = HeaderFactory(config)

    config.custom_headers = {"Authorization": "replaced"}

    assert factory.base()["Authorization"] == "replaced"


def test_custom_headers_mutated_in_place_are_picked_up():
    config = UnleashConfig(TEST_URL, TEST_APP_NAME, custom_headers={"name": "header"})
    factory = HeaderFactory(config)

    config.custom_headers["extra"] = "another"

    assert factory.base()["extra"] == "another"


def test_identity_is_read_on_every_call():
    config = UnleashConfig(TEST_URL, TEST_APP_NAME)
    factory = HeaderFactory(config)

    config.app_name = "renamed"
    config.instance_id = "456"

    headers = factory.base()
    assert headers["unleash-appname"] == "renamed"
    assert headers["unleash-instanceid"] == "456"


def test_each_call_returns_a_fresh_dict():
    # The returned dicts are handed to collaborators that hold on to them.
    config = UnleashConfig(TEST_URL, TEST_APP_NAME, custom_headers={"name": "header"})
    factory = HeaderFactory(config)

    first = factory.base()
    first["injected"] = "value"

    assert "injected" not in factory.base()
    assert "injected" not in config.custom_headers
    assert "injected" not in APPLICATION_HEADERS


def test_polling_adds_the_refresh_interval():
    factory = build_factory(refresh_interval=1)

    assert factory.polling()["unleash-interval"] == "1000"
    assert "unleash-interval" not in factory.base()


def test_metrics_adds_the_metrics_interval():
    factory = build_factory(metrics_interval=2)

    assert factory.metrics()["unleash-interval"] == "2000"


def test_polling_and_metrics_differ_only_in_the_interval():
    factory = build_factory(refresh_interval=1, metrics_interval=2)

    polling = factory.polling()
    metrics = factory.metrics()

    assert polling.keys() == metrics.keys()
    assert {k: v for k, v in polling.items() if k != "unleash-interval"} == {
        k: v for k, v in metrics.items() if k != "unleash-interval"
    }


def test_streaming_adds_the_sse_accept_header():
    factory = build_factory()

    headers = factory.streaming()

    assert headers["Accept"] == "text/event-stream"
    assert "unleash-interval" not in headers


def test_streaming_is_what_the_streaming_connector_used_to_rebuild():
    # StreamingConnector used to re-merge these itself.  Pinning the
    # equivalence keeps the two from drifting apart.
    factory = build_factory(custom_headers={"Authorization": "project:env.hash"})

    headers = factory.streaming()

    assert {
        **headers,
        **APPLICATION_HEADERS,
        "Accept": "text/event-stream",
    } == headers


def test_polling_is_what_the_polling_connector_used_to_rebuild():
    # PollingConnector used to merge the interval in on every tick.
    refresh_interval = 7
    factory = build_factory(refresh_interval=refresh_interval)

    headers = factory.polling()

    assert {
        **headers,
        "unleash-interval": str(refresh_interval * 1000),
    } == headers
