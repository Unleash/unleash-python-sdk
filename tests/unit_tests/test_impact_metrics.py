import json

import pytest
import responses

from tests.utilities.testing_constants import (
    APP_NAME,
    ENVIRONMENT,
    INSTANCE_ID,
    URL,
)
from UnleashClient import INSTANCES, UnleashClient
from UnleashClient.cache import FileCache
from UnleashClient.constants import METRICS_URL
from UnleashClient.impact_metrics import MetricFlagContext
from UnleashClient.periodic_tasks import aggregate_and_send_metrics

MOCK_FEATURES_RESPONSE = {
    "version": 1,
    "features": [
        {
            "name": "feature-with-variant",
            "enabled": True,
            "strategies": [{"name": "default", "parameters": {}}],
            "variants": [{"name": "treatment", "weight": 1000}],
        },
        {
            "name": "enabled-feature",
            "enabled": True,
            "strategies": [{"name": "default", "parameters": {}}],
        },
        {
            "name": "disabled-feature",
            "enabled": False,
            "strategies": [{"name": "default", "parameters": {}}],
        },
    ],
}


@pytest.fixture(autouse=True)
def before_each():
    INSTANCES._reset()


@pytest.fixture
def unleash_client():
    cache = FileCache("TEST_CACHE")
    cache.bootstrap_from_dict(MOCK_FEATURES_RESPONSE)
    client = UnleashClient(
        url=URL,
        app_name=APP_NAME,
        environment=ENVIRONMENT,
        instance_id=INSTANCE_ID,
        disable_metrics=True,
        disable_registration=True,
        cache=cache,
    )
    client.initialize_client(fetch_toggles=False)
    yield client
    client.destroy()


class TestSendMetricsViaClient:
    @responses.activate
    def test_impact_metrics_in_payload(self, unleash_client):
        responses.add(responses.POST, URL + METRICS_URL, json={}, status=202)

        unleash_client.impact_metrics.define_counter("purchases", "Number of purchases")
        unleash_client.impact_metrics.increment_counter("purchases", 1)

        unleash_client.impact_metrics.define_gauge("active_users", "Active users")
        unleash_client.impact_metrics.update_gauge("active_users", 42)

        unleash_client.impact_metrics.define_histogram(
            "latency", "Request latency", [0.1, 0.5, 1.0]
        )
        unleash_client.impact_metrics.observe_histogram("latency", 0.3)

        aggregate_and_send_metrics(
            url=URL,
            app_name=APP_NAME,
            instance_id=INSTANCE_ID,
            connection_id="test-connection",
            headers={},
            custom_options={},
            request_timeout=30,
            engine=unleash_client.engine,
        )

        request_body = json.loads(responses.calls[0].request.body)
        metrics = {m["name"]: m for m in request_body["impactMetrics"]}

        expected_labels = {"appName": APP_NAME, "environment": ENVIRONMENT}

        assert metrics == {
            "purchases": {
                "name": "purchases",
                "help": "Number of purchases",
                "type": "counter",
                "samples": [{"labels": expected_labels, "value": 1}],
            },
            "active_users": {
                "name": "active_users",
                "help": "Active users",
                "type": "gauge",
                "samples": [{"labels": expected_labels, "value": 42}],
            },
            "latency": {
                "name": "latency",
                "help": "Request latency",
                "type": "histogram",
                "samples": [
                    {
                        "labels": expected_labels,
                        "count": 1,
                        "sum": 0.3,
                        "buckets": [
                            {"le": 0.1, "count": 0},
                            {"le": 0.5, "count": 1},
                            {"le": 1.0, "count": 1},
                            {"le": "+Inf", "count": 1},
                        ],
                    }
                ],
            },
        }

    @responses.activate
    def test_impact_metrics_with_flag_context(self, unleash_client):
        responses.add(responses.POST, URL + METRICS_URL, json={}, status=202)

        flag_context = MetricFlagContext(
            flag_names=["feature-with-variant", "enabled-feature", "disabled-feature"],
            context={"userId": "123"},
        )

        unleash_client.impact_metrics.define_counter("purchases", "Number of purchases")
        unleash_client.impact_metrics.increment_counter("purchases", 1, flag_context)

        aggregate_and_send_metrics(
            url=URL,
            app_name=APP_NAME,
            instance_id=INSTANCE_ID,
            connection_id="test-connection",
            headers={},
            custom_options={},
            request_timeout=30,
            engine=unleash_client.engine,
        )

        request_body = json.loads(responses.calls[0].request.body)
        labels = request_body["impactMetrics"][0]["samples"][0]["labels"]

        assert labels == {
            "appName": APP_NAME,
            "environment": ENVIRONMENT,
            "feature-with-variant": "treatment",
            "enabled-feature": "enabled",
            "disabled-feature": "disabled",
        }

    @responses.activate
    def test_impact_metrics_resent_after_failure(self, unleash_client):
        responses.add(responses.POST, URL + METRICS_URL, json={}, status=500)
        responses.add(responses.POST, URL + METRICS_URL, json={}, status=202)

        unleash_client.impact_metrics.define_counter("my_counter", "Test counter")
        unleash_client.impact_metrics.increment_counter("my_counter", 5)

        aggregate_and_send_metrics(
            url=URL,
            app_name=APP_NAME,
            instance_id=INSTANCE_ID,
            connection_id="test-connection",
            headers={},
            custom_options={},
            request_timeout=30,
            engine=unleash_client.engine,
        )
        aggregate_and_send_metrics(
            url=URL,
            app_name=APP_NAME,
            instance_id=INSTANCE_ID,
            connection_id="test-connection",
            headers={},
            custom_options={},
            request_timeout=30,
            engine=unleash_client.engine,
        )

        request_body = json.loads(responses.calls[1].request.body)
        assert request_body["impactMetrics"][0]["name"] == "my_counter"
