import json

import responses
from yggdrasil_engine.engine import UnleashEngine

from tests.utilities.testing_constants import (
    APP_NAME,
    CONNECTION_ID,
    CUSTOM_HEADERS,
    CUSTOM_OPTIONS,
    INSTANCE_ID,
    REQUEST_TIMEOUT,
    URL,
)
from UnleashClient.config import UnleashConfig
from UnleashClient.constants import (
    CLIENT_SPEC_VERSION,
    METRICS_URL,
)
from UnleashClient.headers import HeaderFactory
from UnleashClient.periodic_tasks import aggregate_and_send_metrics
from UnleashClient.transport import Transport

FULL_METRICS_URL = URL + METRICS_URL


def build_transport() -> Transport:
    config = UnleashConfig(
        URL,
        APP_NAME,
        instance_id=INSTANCE_ID,
        custom_headers=CUSTOM_HEADERS,
        custom_options=CUSTOM_OPTIONS,
        request_timeout=REQUEST_TIMEOUT,
    )
    return Transport(config, HeaderFactory(config))


@responses.activate
def test_no_metrics():
    responses.add(responses.POST, FULL_METRICS_URL, json={}, status=200)

    engine = UnleashEngine()

    aggregate_and_send_metrics(
        build_transport(),
        APP_NAME,
        INSTANCE_ID,
        CONNECTION_ID,
        engine,
    )

    assert len(responses.calls) == 0


@responses.activate
def test_metrics_metadata_is_sent():
    responses.add(responses.POST, FULL_METRICS_URL, json={}, status=200)

    engine = UnleashEngine()
    engine.count_toggle("something-to-make-sure-metrics-get-sent", True)

    aggregate_and_send_metrics(
        build_transport(),
        APP_NAME,
        INSTANCE_ID,
        CONNECTION_ID,
        engine,
    )

    assert len(responses.calls) == 1
    request = json.loads(responses.calls[0].request.body)

    assert request["yggdrasilVersion"] is not None
    assert request["specVersion"] == CLIENT_SPEC_VERSION
    assert request["platformName"] is not None
    assert request["platformVersion"] is not None


@responses.activate
def test_metrics_includes_sdk_flavor_when_set():
    responses.add(responses.POST, FULL_METRICS_URL, json={}, status=200)

    engine = UnleashEngine()
    engine.count_toggle("something-to-make-sure-metrics-get-sent", True)

    aggregate_and_send_metrics(
        build_transport(),
        APP_NAME,
        INSTANCE_ID,
        CONNECTION_ID,
        engine,
        sdk_flavor="unleash-openfeature-python-provider",
        sdk_flavor_version="1.2.3",
    )

    request = json.loads(responses.calls[0].request.body)
    assert request["sdkFlavor"] == "unleash-openfeature-python-provider"
    assert request["sdkFlavorVersion"] == "1.2.3"


@responses.activate
def test_metrics_omits_sdk_flavor_when_unset():
    responses.add(responses.POST, FULL_METRICS_URL, json={}, status=200)

    engine = UnleashEngine()
    engine.count_toggle("something-to-make-sure-metrics-get-sent", True)

    aggregate_and_send_metrics(
        build_transport(),
        APP_NAME,
        INSTANCE_ID,
        CONNECTION_ID,
        engine,
    )

    request = json.loads(responses.calls[0].request.body)
    assert "sdkFlavor" not in request
    assert "sdkFlavorVersion" not in request
