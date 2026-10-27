from UnleashClient._headers import _HeaderFactory
from UnleashClient.config import (
    HttpOptions,
    IdentityOptions,
    MetricsOptions,
    PollingOptions,
    UnleashConfig,
)
from UnleashClient.constants import (
    APPLICATION_HEADERS,
    CLIENT_SPEC_VERSION,
    SDK_NAME,
    SDK_VERSION,
)

TEST_URL = "http://localhost:4242/api"
TEST_APP_NAME = "pytest"


def build_factory(**kwargs) -> _HeaderFactory:
    return _HeaderFactory(UnleashConfig(TEST_URL, TEST_APP_NAME, **kwargs))


def test_base_carries_the_identification_headers():
    config = UnleashConfig(
        TEST_URL, TEST_APP_NAME, identity=IdentityOptions(instance_id="123")
    )
    factory = _HeaderFactory(config)

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
    factory = build_factory(http=HttpOptions(headers={"X-Custom": "header"}))

    headers = factory.base()

    assert headers["X-Custom"] == "header"


def test_base_sends_the_api_key_as_the_authorization_header():
    factory = build_factory(api_key="project:env.hash")

    headers = factory.base()

    assert headers["Authorization"] == "project:env.hash"


def test_base_has_no_authorization_header_without_an_api_key():
    factory = build_factory()

    headers = factory.base()

    assert "Authorization" not in headers


def test_application_headers_win_over_custom_headers():
    factory = build_factory(
        http=HttpOptions(headers={"Content-Type": "application/xml"})
    )

    headers = factory.base()

    assert headers["Content-Type"] == "application/json"


def test_custom_headers_cannot_override_the_identification_headers():
    factory = build_factory(http=HttpOptions(headers={"unleash-appname": "spoofed"}))

    headers = factory.base()

    assert headers["unleash-appname"] == TEST_APP_NAME


def test_each_call_returns_a_fresh_dict():
    # The returned dicts are handed to collaborators that hold on to them.
    config = UnleashConfig(
        TEST_URL, TEST_APP_NAME, http=HttpOptions(headers={"name": "header"})
    )
    factory = _HeaderFactory(config)

    first = factory.base()
    first["injected"] = "value"

    assert "injected" not in factory.base()
    assert "injected" not in config.http.headers
    assert "injected" not in APPLICATION_HEADERS


def test_polling_adds_the_refresh_interval():
    factory = build_factory()

    assert factory.polling(PollingOptions(interval=1))["unleash-interval"] == "1000"
    assert "unleash-interval" not in factory.base()


def test_metrics_adds_the_metrics_interval():
    factory = build_factory(metrics=MetricsOptions(interval=2))

    assert factory.metrics()["unleash-interval"] == "2000"


def test_polling_and_metrics_differ_only_in_the_interval():
    factory = build_factory(metrics=MetricsOptions(interval=2))

    polling = factory.polling(PollingOptions(interval=1))
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
    factory = build_factory(
        api_key="project:env.hash", http=HttpOptions(headers={"X-Custom": "header"})
    )

    headers = factory.streaming()

    assert {
        **headers,
        **APPLICATION_HEADERS,
        "Accept": "text/event-stream",
    } == headers


def test_polling_is_what_the_polling_connector_used_to_rebuild():
    # PollingConnector used to merge the interval in on every tick.
    refresh_interval = 7
    factory = build_factory()

    headers = factory.polling(PollingOptions(interval=refresh_interval))

    assert {
        **headers,
        "unleash-interval": str(refresh_interval * 1000),
    } == headers
