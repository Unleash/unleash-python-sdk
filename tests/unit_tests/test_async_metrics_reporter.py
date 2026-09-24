import asyncio
import json
from typing import Callable, List, Optional, TypedDict

import pytest_asyncio
from pytest import mark
from yggdrasil_engine.engine import UnleashEngine

from tests.utilities.fake_unleash_server import FakeUnleash
from tests.utilities.testing_constants import APP_NAME
from UnleashClient._async_scheduler import (
    _AsyncJob,
    _AsyncJobFn,
    _AsyncScheduler,
)
from UnleashClient.async_metrics_reporter import AsyncMetricsReporter
from UnleashClient.async_transport import AsyncTransport
from UnleashClient.config import UnleashConfig
from UnleashClient.constants import CLIENT_SPEC_VERSION, METRICS_URL
from UnleashClient.headers import HeaderFactory
from UnleashClient.impact_metrics import ImpactMetrics

# testing_constants.URL mounts Unleash under /api, and the fake server does the same,
# so the transport builds the URL shape it builds against a deployment.
API_PREFIX = "/api"
METRICS_PATH = API_PREFIX + METRICS_URL

# Any flag will do; the bucket only has to be non-empty for a send to happen.
COUNTED_FLAG = "something-to-make-sure-metrics-get-sent"

# Long enough that the scheduled flush never runs during a test, so a recorded request
# can only have come from the call the test made.
NEVER = 3600


class Registration(TypedDict):
    interval_seconds: float
    jitter_seconds: Optional[float]
    fn: _AsyncJobFn
    job: _AsyncJob


class RecordingScheduler(_AsyncScheduler):
    """Captures what reached every() and cancel_and_wait()."""

    def __init__(self) -> None:
        super().__init__()
        self.registered: List[Registration] = []
        self.cancelled: List[_AsyncJob] = []

    def every(self, interval_seconds, jitter_seconds, fn, kwargs=None):
        job = super().every(interval_seconds, jitter_seconds, fn, kwargs)
        self.registered.append(
            {
                "interval_seconds": interval_seconds,
                "jitter_seconds": jitter_seconds,
                "fn": fn,
                "job": job,
            }
        )
        return job

    async def cancel_and_wait(self, job):
        self.cancelled.append(job)
        await super().cancel_and_wait(job)


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


@pytest_asyncio.fixture
async def server():
    """A real Unleash server on an ephemeral port, stopped on teardown."""
    fake = FakeUnleash()
    await fake.start(API_PREFIX)
    try:
        yield fake
    finally:
        await fake.close()


@pytest_asyncio.fixture
async def build_reporter(server: FakeUnleash):
    """
    Factory pointed at the fake server. Keyword arguments override the defaults on the
    config.

    Every reporter it builds gets its own RecordingScheduler, and both are shut down on
    teardown: a job left running outlives the test, and an unclosed ClientSession is
    reported by aiohttp on garbage collection.
    """
    built = []

    def _build_reporter(impact_metrics=None, **kwargs) -> AsyncMetricsReporter:
        defaults = {
            "metrics_interval": NEVER,
        }
        defaults.update(kwargs)
        config = UnleashConfig(server.base_url, APP_NAME, **defaults)
        engine = UnleashEngine()
        reporter = AsyncMetricsReporter(
            config=config,
            transport=AsyncTransport(config, HeaderFactory(config)),
            scheduler=RecordingScheduler(),
            engine=engine,
            impact_metrics=(
                impact_metrics
                if impact_metrics is not None
                else ImpactMetrics(
                    engine, config.app_name, config.impact_metrics_environment
                )
            ),
        )
        built.append(reporter)
        return reporter

    try:
        yield _build_reporter
    finally:
        for reporter in built:
            await reporter._scheduler.shutdown()
            await reporter._transport.aclose()


@pytest_asyncio.fixture
async def reporter(
    build_reporter: Callable[..., AsyncMetricsReporter],
) -> AsyncMetricsReporter:
    """The reporter the tests that need no config override share."""
    return build_reporter()


def metrics_body(server: FakeUnleash, index: int = 0) -> dict:
    return json.loads(server.calls("POST", METRICS_PATH)[index].body)


# flush


@mark.asyncio
async def test_flush_sends_nothing_when_nothing_was_recorded(server, reporter):
    server.on("POST", METRICS_PATH, status=202, payload={})

    await reporter.flush()

    assert len(server.calls("POST", METRICS_PATH)) == 0


@mark.asyncio
async def test_flush_sends_the_bucket_it_collected(server, reporter):
    server.on("POST", METRICS_PATH, status=202, payload={})
    reporter._engine.count_toggle(COUNTED_FLAG, True)

    await reporter.flush()

    assert len(server.calls("POST", METRICS_PATH)) == 1
    assert metrics_body(server)["bucket"]["toggles"][COUNTED_FLAG]["yes"] == 1


@mark.asyncio
async def test_flush_identifies_the_client(server, build_reporter):
    reporter = build_reporter(instance_id="123")
    server.on("POST", METRICS_PATH, status=202, payload={})
    reporter._engine.count_toggle(COUNTED_FLAG, True)

    await reporter.flush()

    body = metrics_body(server)
    assert body["appName"] == APP_NAME
    assert body["instanceId"] == "123"
    assert body["connectionId"] == reporter._config.connection_id


@mark.asyncio
async def test_flush_sends_the_platform_metadata(server, reporter):
    server.on("POST", METRICS_PATH, status=202, payload={})
    reporter._engine.count_toggle(COUNTED_FLAG, True)

    await reporter.flush()

    body = metrics_body(server)
    assert body["yggdrasilVersion"] is not None
    assert body["specVersion"] == CLIENT_SPEC_VERSION
    assert body["platformName"] is not None
    assert body["platformVersion"] is not None


@mark.asyncio
async def test_flush_includes_sdk_flavor_when_set(server, build_reporter):
    reporter = build_reporter(
        sdk_flavor="unleash-openfeature-python-provider", sdk_flavor_version="1.2.3"
    )
    server.on("POST", METRICS_PATH, status=202, payload={})
    reporter._engine.count_toggle(COUNTED_FLAG, True)

    await reporter.flush()

    body = metrics_body(server)
    assert body["sdkFlavor"] == "unleash-openfeature-python-provider"
    assert body["sdkFlavorVersion"] == "1.2.3"


@mark.asyncio
async def test_flush_omits_sdk_flavor_when_unset(server, reporter):
    server.on("POST", METRICS_PATH, status=202, payload={})
    reporter._engine.count_toggle(COUNTED_FLAG, True)

    await reporter.flush()

    body = metrics_body(server)
    assert "sdkFlavor" not in body
    assert "sdkFlavorVersion" not in body


@mark.asyncio
async def test_the_config_is_read_on_every_flush(server, reporter):
    # UnleashClient.unleash_app_name has a setter, so a client can change it after the
    # reporter was constructed.
    server.on("POST", METRICS_PATH, status=202, payload={}, repeat=True)

    reporter._engine.count_toggle(COUNTED_FLAG, True)
    await reporter.flush()

    reporter._config.app_name = "renamed"
    reporter._engine.count_toggle(COUNTED_FLAG, True)
    await reporter.flush()

    assert metrics_body(server, 0)["appName"] == APP_NAME
    assert metrics_body(server, 1)["appName"] == "renamed"


@mark.asyncio
async def test_the_flush_goes_through_the_async_transport(reporter):
    # The flush runs on the client's loop, so a blocking transport would hold it up for
    # the length of every POST.
    assert isinstance(reporter._transport, AsyncTransport)
    assert asyncio.iscoroutinefunction(reporter._transport.send_metrics)
    assert asyncio.iscoroutinefunction(reporter.flush)


# start and stop


@mark.asyncio
async def test_start_registers_the_flush_with_the_metrics_interval_and_jitter(
    build_reporter,
):
    reporter = build_reporter(metrics_interval=30, metrics_jitter=10)

    reporter.start()

    (call,) = reporter._scheduler.registered
    assert call["interval_seconds"] == 30
    assert call["jitter_seconds"] == 10
    assert call["fn"] == reporter.flush


@mark.asyncio
async def test_start_coerces_the_metrics_interval(build_reporter):
    # A client can be built with metrics_interval="30": the constructor does not
    # validate types.
    reporter = build_reporter()
    reporter._config.metrics_interval = "30"

    reporter.start()

    (call,) = reporter._scheduler.registered
    assert call["interval_seconds"] == 30


@mark.asyncio
async def test_stop_flushes_what_is_left_and_cancels_the_job(server, build_reporter):
    # A short-lived client can be destroyed before its first interval elapses, so the
    # bucket has to go out on the way down.
    reporter = build_reporter()
    server.on("POST", METRICS_PATH, status=202, payload={})
    reporter.start()
    reporter._engine.count_toggle(COUNTED_FLAG, True)

    await reporter.stop()

    assert len(server.calls("POST", METRICS_PATH)) == 1
    (call,) = reporter._scheduler.registered
    assert reporter._scheduler.cancelled == [call["job"]]


@mark.asyncio
async def test_stop_sends_nothing_when_start_was_never_called(server, reporter):
    # Metrics disabled, or destroy() on a client that was never initialized.
    server.on("POST", METRICS_PATH, status=202, payload={})
    reporter._engine.count_toggle(COUNTED_FLAG, True)

    await reporter.stop()

    assert len(server.calls("POST", METRICS_PATH)) == 0


@mark.asyncio
async def test_stop_is_idempotent(server, build_reporter):
    reporter = build_reporter()
    server.on("POST", METRICS_PATH, status=202, payload={}, repeat=True)
    reporter.start()
    reporter._engine.count_toggle(COUNTED_FLAG, True)

    await reporter.stop()
    await reporter.stop()

    assert len(server.calls("POST", METRICS_PATH)) == 1


@mark.asyncio
async def test_constructing_the_reporter_registers_no_job_and_opens_no_session(
    build_reporter,
):
    # __init__ is synchronous and runs with no loop: the client's constructor has to
    # work before anything is awaited.
    reporter = build_reporter()

    assert reporter._scheduler.registered == []
    assert reporter._transport._session is None


# impact metrics
#
# Kept 1:1 with test_metrics_reporter.py, so both reporters are held to the same answer
# on what counts as a failed send and what happens to the metrics after one.


@mark.asyncio
async def test_impact_metrics_go_out_with_the_bucket(server, reporter):
    server.on("POST", METRICS_PATH, status=202, payload={})
    reporter._impact_metrics.define_counter("purchases", "Number of purchases")
    reporter._impact_metrics.increment_counter("purchases", 1)

    await reporter.flush()

    assert metrics_body(server)["impactMetrics"][0]["name"] == "purchases"


@mark.asyncio
async def test_impact_metrics_alone_are_enough_to_trigger_a_send(server, reporter):
    # Nothing was evaluated, so there is no toggle bucket at all.
    server.on("POST", METRICS_PATH, status=202, payload={})
    reporter._impact_metrics.define_counter("purchases", "Number of purchases")
    reporter._impact_metrics.increment_counter("purchases", 1)

    await reporter.flush()

    assert len(server.calls("POST", METRICS_PATH)) == 1
    assert metrics_body(server)["bucket"] is None


@mark.asyncio
async def test_impact_metrics_are_restored_when_the_send_fails(server, reporter):
    server.on("POST", METRICS_PATH, status=500, payload={})
    server.on("POST", METRICS_PATH, status=202, payload={})
    reporter._impact_metrics.define_counter("my_counter", "Test counter")
    reporter._impact_metrics.increment_counter("my_counter", 5)

    await reporter.flush()
    await reporter.flush()

    resent = metrics_body(server, 1)["impactMetrics"][0]
    assert resent["name"] == "my_counter"
    assert resent["samples"][0]["value"] == 5


@mark.asyncio
async def test_impact_metrics_are_not_restored_when_the_send_lands(server, reporter):
    server.on("POST", METRICS_PATH, status=202, payload={}, repeat=True)
    reporter._impact_metrics.define_counter("my_counter", "Test counter")
    reporter._impact_metrics.increment_counter("my_counter", 5)

    await reporter.flush()
    await reporter.flush()

    # The engine keeps the counter definition, so a second send still describes it
    # -- but back at zero, rather than replaying the 5 the server already took.
    assert metrics_body(server, 1)["impactMetrics"][0]["samples"][0]["value"] == 0


@mark.asyncio
async def test_nothing_is_restored_when_there_were_no_impact_metrics(
    server, build_reporter
):
    impact_metrics = SilentImpactMetrics()
    reporter = build_reporter(impact_metrics=impact_metrics)
    server.on("POST", METRICS_PATH, status=500, payload={})
    reporter._engine.count_toggle(COUNTED_FLAG, True)

    await reporter.flush()

    assert len(server.calls("POST", METRICS_PATH)) == 1
    assert impact_metrics.restored == []


@mark.asyncio
async def test_the_bucket_still_goes_out_when_impact_collection_yields_nothing(
    server, build_reporter
):
    # ImpactMetrics.collect() returns None on a broken engine; that must not take the
    # toggle metrics down with it.
    reporter = build_reporter(impact_metrics=SilentImpactMetrics())
    server.on("POST", METRICS_PATH, status=202, payload={})
    reporter._engine.count_toggle(COUNTED_FLAG, True)

    await reporter.flush()

    assert len(server.calls("POST", METRICS_PATH)) == 1
    assert "impactMetrics" not in metrics_body(server)
