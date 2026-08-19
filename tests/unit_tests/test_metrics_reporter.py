import json

import responses
from apscheduler.schedulers.background import BackgroundScheduler
from yggdrasil_engine.engine import UnleashEngine

from UnleashClient.config import UnleashConfig
from UnleashClient.constants import CLIENT_SPEC_VERSION, METRICS_URL
from UnleashClient.headers import HeaderFactory
from UnleashClient.impact_metrics import ImpactMetrics
from UnleashClient.metrics_reporter import MetricsReporter
from UnleashClient.scheduler import Scheduler
from UnleashClient.transport import Transport

URL = "http://localhost:4242/api"
APP_NAME = "pytest"

FULL_METRICS_URL = URL + METRICS_URL

# Any flag will do; the bucket only has to be non-empty for a send to happen.
COUNTED_FLAG = "something-to-make-sure-metrics-get-sent"


class RecordingScheduler(BackgroundScheduler):
    """
    Captures what reached add_job.  Mirrors the fake in test_scheduler.py, so a change
    to how the reporter describes its job shows up here rather than in the client tests.
    """

    def __init__(self):
        super().__init__()
        self.calls = []

    def add_job(self, func, trigger=None, **kwargs):
        self.calls.append({"func": func, "trigger": trigger, **kwargs})
        return super().add_job(func, trigger=trigger, **kwargs)


class MinimalScheduler:
    """A duck-typed scheduler whose add_job returns nothing, as a user's may."""

    def start(self):
        pass

    def shutdown(self, *args, **kwargs):
        pass

    def add_job(self, *args, **kwargs):
        return None

    def remove_all_jobs(self, *args, **kwargs):
        pass


class SilentImpactMetrics:
    """
    Impact metrics that never yield anything -- what a client that records none looks
    like, and what a failed collection degrades to.
    """

    def __init__(self):
        self.restored = []

    def collect(self):
        return None

    def restore(self, metrics):
        self.restored.append(metrics)


def build_reporter(scheduler=None, impact_metrics=None, **kwargs) -> MetricsReporter:
    config = UnleashConfig(URL, APP_NAME, **kwargs)
    engine = UnleashEngine()
    return MetricsReporter(
        config=config,
        transport=Transport(config, HeaderFactory(config)),
        scheduler=scheduler if scheduler is not None else Scheduler(),
        engine=engine,
        impact_metrics=(
            impact_metrics
            if impact_metrics is not None
            else ImpactMetrics(
                engine, config.app_name, config.impact_metrics_environment
            )
        ),
    )


# flush


@responses.activate
def test_flush_sends_nothing_when_nothing_was_recorded():
    responses.add(responses.POST, FULL_METRICS_URL, json={}, status=202)
    reporter = build_reporter()

    reporter.flush()

    assert len(responses.calls) == 0


@responses.activate
def test_flush_sends_the_bucket_it_collected():
    responses.add(responses.POST, FULL_METRICS_URL, json={}, status=202)
    reporter = build_reporter()
    reporter._engine.count_toggle(COUNTED_FLAG, True)

    reporter.flush()

    assert len(responses.calls) == 1
    request = json.loads(responses.calls[0].request.body)
    assert request["bucket"]["toggles"][COUNTED_FLAG]["yes"] == 1


@responses.activate
def test_flush_identifies_the_client():
    responses.add(responses.POST, FULL_METRICS_URL, json={}, status=202)
    reporter = build_reporter(instance_id="123")
    reporter._engine.count_toggle(COUNTED_FLAG, True)

    reporter.flush()

    request = json.loads(responses.calls[0].request.body)
    assert request["appName"] == APP_NAME
    assert request["instanceId"] == "123"
    assert request["connectionId"] == reporter._config.connection_id


@responses.activate
def test_flush_sends_the_platform_metadata():
    responses.add(responses.POST, FULL_METRICS_URL, json={}, status=202)
    reporter = build_reporter()
    reporter._engine.count_toggle(COUNTED_FLAG, True)

    reporter.flush()

    request = json.loads(responses.calls[0].request.body)
    assert request["yggdrasilVersion"] is not None
    assert request["specVersion"] == CLIENT_SPEC_VERSION
    assert request["platformName"] is not None
    assert request["platformVersion"] is not None


@responses.activate
def test_flush_includes_sdk_flavor_when_set():
    responses.add(responses.POST, FULL_METRICS_URL, json={}, status=202)
    reporter = build_reporter(
        sdk_flavor="unleash-openfeature-python-provider", sdk_flavor_version="1.2.3"
    )
    reporter._engine.count_toggle(COUNTED_FLAG, True)

    reporter.flush()

    request = json.loads(responses.calls[0].request.body)
    assert request["sdkFlavor"] == "unleash-openfeature-python-provider"
    assert request["sdkFlavorVersion"] == "1.2.3"


@responses.activate
def test_flush_omits_sdk_flavor_when_unset():
    responses.add(responses.POST, FULL_METRICS_URL, json={}, status=202)
    reporter = build_reporter()
    reporter._engine.count_toggle(COUNTED_FLAG, True)

    reporter.flush()

    request = json.loads(responses.calls[0].request.body)
    assert "sdkFlavor" not in request
    assert "sdkFlavorVersion" not in request


@responses.activate
def test_the_config_is_read_on_every_flush():
    # UnleashClient.unleash_app_name has a setter, so a client can change it after the
    # reporter was constructed.  The body used to be captured when the job was
    # registered, which made a reassignment invisible.
    responses.add(responses.POST, FULL_METRICS_URL, json={}, status=202)
    reporter = build_reporter()

    reporter._engine.count_toggle(COUNTED_FLAG, True)
    reporter.flush()

    reporter._config.app_name = "renamed"
    reporter._engine.count_toggle(COUNTED_FLAG, True)
    reporter.flush()

    assert json.loads(responses.calls[0].request.body)["appName"] == APP_NAME
    assert json.loads(responses.calls[1].request.body)["appName"] == "renamed"


# start


def test_start_builds_an_interval_trigger_from_the_metrics_interval_and_jitter():
    recording = RecordingScheduler()
    reporter = build_reporter(
        scheduler=Scheduler(recording, "default"),
        metrics_interval=30,
        metrics_jitter=10,
    )

    reporter.start()

    (call,) = recording.calls
    assert call["trigger"].interval.total_seconds() == 30
    assert call["trigger"].jitter == 10


def test_start_registers_the_flush():
    recording = RecordingScheduler()
    reporter = build_reporter(scheduler=Scheduler(recording, "default"))

    reporter.start()

    (call,) = recording.calls
    assert call["func"] == reporter.flush


def test_start_coerces_the_metrics_interval():
    # Scheduler.every does not coerce -- a str interval would raise there.  The metrics
    # call site has always int()ed its own, and a client can be built with
    # metrics_interval="30" because the constructor does not validate types.
    recording = RecordingScheduler()
    reporter = build_reporter(scheduler=Scheduler(recording, "default"))
    reporter._config.metrics_interval = "30"

    reporter.start()

    (call,) = recording.calls
    assert call["trigger"].interval.total_seconds() == 30


def test_start_exposes_the_registered_job():
    reporter = build_reporter(scheduler=Scheduler(BackgroundScheduler(), "default"))

    assert reporter.job is None
    reporter.start()

    assert reporter.job is not None


# stop


@responses.activate
def test_stop_flushes_what_is_left_and_cancels_the_job():
    # A short-lived client can be destroyed before its first interval elapses, so the
    # bucket has to go out on the way down.
    responses.add(responses.POST, FULL_METRICS_URL, json={}, status=202)
    scheduler = Scheduler(BackgroundScheduler(), "default")
    reporter = build_reporter(scheduler=scheduler)
    reporter.start()
    reporter._engine.count_toggle(COUNTED_FLAG, True)

    reporter.stop()

    assert len(responses.calls) == 1
    assert scheduler.scheduler.get_jobs() == []
    assert reporter.job is None


@responses.activate
def test_stop_sends_nothing_when_no_job_was_ever_registered():
    # Metrics disabled, or destroy() on a client that was never initialized.
    responses.add(responses.POST, FULL_METRICS_URL, json={}, status=202)
    reporter = build_reporter()
    reporter._engine.count_toggle(COUNTED_FLAG, True)

    reporter.stop()

    assert len(responses.calls) == 0


@responses.activate
def test_stop_tolerates_a_scheduler_that_registered_no_job():
    responses.add(responses.POST, FULL_METRICS_URL, json={}, status=202)
    reporter = build_reporter(scheduler=Scheduler(MinimalScheduler(), "default"))
    reporter.start()
    reporter._engine.count_toggle(COUNTED_FLAG, True)

    reporter.stop()

    assert len(responses.calls) == 0


# impact metrics


@responses.activate
def test_impact_metrics_go_out_with_the_bucket():
    responses.add(responses.POST, FULL_METRICS_URL, json={}, status=202)
    reporter = build_reporter()
    reporter._impact_metrics.define_counter("purchases", "Number of purchases")
    reporter._impact_metrics.increment_counter("purchases", 1)

    reporter.flush()

    request = json.loads(responses.calls[0].request.body)
    assert request["impactMetrics"][0]["name"] == "purchases"


@responses.activate
def test_impact_metrics_alone_are_enough_to_trigger_a_send():
    # Nothing was evaluated, so there is no toggle bucket at all.
    responses.add(responses.POST, FULL_METRICS_URL, json={}, status=202)
    reporter = build_reporter()
    reporter._impact_metrics.define_counter("purchases", "Number of purchases")
    reporter._impact_metrics.increment_counter("purchases", 1)

    reporter.flush()

    assert len(responses.calls) == 1
    assert json.loads(responses.calls[0].request.body)["bucket"] is None


@responses.activate
def test_impact_metrics_are_restored_when_the_send_fails():
    responses.add(responses.POST, FULL_METRICS_URL, json={}, status=500)
    responses.add(responses.POST, FULL_METRICS_URL, json={}, status=202)
    reporter = build_reporter()
    reporter._impact_metrics.define_counter("my_counter", "Test counter")
    reporter._impact_metrics.increment_counter("my_counter", 5)

    reporter.flush()
    reporter.flush()

    resent = json.loads(responses.calls[1].request.body)["impactMetrics"][0]
    assert resent["name"] == "my_counter"
    assert resent["samples"][0]["value"] == 5


@responses.activate
def test_impact_metrics_are_not_restored_when_the_send_lands():
    responses.add(responses.POST, FULL_METRICS_URL, json={}, status=202)
    reporter = build_reporter()
    reporter._impact_metrics.define_counter("my_counter", "Test counter")
    reporter._impact_metrics.increment_counter("my_counter", 5)

    reporter.flush()
    reporter.flush()

    # The engine keeps the counter definition, so a second send still describes it --
    # but back at zero, rather than replaying the 5 the server already took.
    second = json.loads(responses.calls[1].request.body)["impactMetrics"][0]
    assert second["samples"][0]["value"] == 0


@responses.activate
def test_nothing_is_restored_when_there_were_no_impact_metrics():
    responses.add(responses.POST, FULL_METRICS_URL, json={}, status=500)
    impact_metrics = SilentImpactMetrics()
    reporter = build_reporter(impact_metrics=impact_metrics)
    reporter._engine.count_toggle(COUNTED_FLAG, True)

    reporter.flush()

    assert len(responses.calls) == 1
    assert impact_metrics.restored == []


@responses.activate
def test_the_bucket_still_goes_out_when_impact_collection_yields_nothing():
    # ImpactMetrics.collect() returns None on a broken engine; that must not take the
    # toggle metrics down with it.
    responses.add(responses.POST, FULL_METRICS_URL, json={}, status=202)
    reporter = build_reporter(impact_metrics=SilentImpactMetrics())
    reporter._engine.count_toggle(COUNTED_FLAG, True)

    reporter.flush()

    assert len(responses.calls) == 1
    assert "impactMetrics" not in json.loads(responses.calls[0].request.body)
