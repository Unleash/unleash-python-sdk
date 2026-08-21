import asyncio
import json
from typing import Callable

import pytest
import pytest_asyncio
from pytest import mark
from yggdrasil_engine.engine import UnleashEngine

from tests.utilities.fake_unleash_server import FakeUnleash
from tests.utilities.testing_constants import APP_NAME, ASYNC_CUSTOM_OPTIONS
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

# Long enough that the task's first flush never lands during a test, so a recorded
# request can only have come from the call the test made.
NEVER = 3600


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

    Every reporter it builds is dropped and closed on teardown: a task left running
    outlives the test, and an unclosed ClientSession is reported by aiohttp on garbage
    collection.
    """
    built = []

    def _build_reporter(impact_metrics=None, **kwargs) -> AsyncMetricsReporter:
        defaults = {
            "custom_options": ASYNC_CUSTOM_OPTIONS,
            "metrics_interval": NEVER,
        }
        defaults.update(kwargs)
        config = UnleashConfig(server.base_url, APP_NAME, **defaults)
        engine = UnleashEngine()
        reporter = AsyncMetricsReporter(
            config=config,
            transport=AsyncTransport(config, HeaderFactory(config)),
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
            reporter._task = None
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


# the schedule


def test_the_next_fire_is_one_interval_after_the_previous_one(build_reporter):
    reporter = build_reporter(metrics_interval=30)

    assert reporter._next_fire(1000.0) == 1030.0


def test_the_next_fire_is_measured_from_the_previous_fire_not_from_now(build_reporter):
    # Anchoring on the previous fire is what stops a slow send pushing the schedule out.
    reporter = build_reporter(metrics_interval=30)

    assert reporter._next_fire(reporter._next_fire(0.0)) == 60.0


def test_the_jitter_only_ever_delays_a_fire(build_reporter):
    # Jitter delays a fire; it never brings one forward.
    reporter = build_reporter(metrics_interval=30, metrics_jitter=10)

    fires = [reporter._next_fire(0.0) for _ in range(50)]

    assert all(30 <= fire < 40 for fire in fires)
    assert len(set(fires)) > 1


def test_the_interval_is_coerced(build_reporter):
    # A client can be built with metrics_interval="30": the constructor does not
    # validate types.
    reporter = build_reporter()
    reporter._config.metrics_interval = "30"

    assert reporter._next_fire(0.0) == 30.0


def test_the_interval_and_jitter_are_read_on_every_cycle(build_reporter):
    # unleash_metrics_interval and unleash_metrics_jitter have setters.
    reporter = build_reporter(metrics_interval=30)

    assert reporter._next_fire(0.0) == 30.0
    reporter._config.metrics_interval = 5
    assert reporter._next_fire(0.0) == 5.0


# start and stop


@mark.asyncio
async def test_start_creates_a_task(reporter):
    assert reporter._task is None

    await reporter.start()

    assert isinstance(reporter._task, asyncio.Task)


@mark.asyncio
async def test_the_task_flushes_on_the_interval(build_reporter):
    flushed = asyncio.Event()
    reporter = build_reporter(metrics_interval=0)
    reporter.flush = _recording_flush(flushed)

    await reporter.start()

    # Asserting that it happened, not how long it took.
    await asyncio.wait_for(flushed.wait(), timeout=5)
    await reporter.stop()


@mark.asyncio
async def test_the_task_sends_through_the_transport(server, build_reporter):
    reporter = build_reporter(metrics_interval=0)
    server.on("POST", METRICS_PATH, status=202, payload={}, repeat=True)
    reporter._engine.count_toggle(COUNTED_FLAG, True)

    await reporter.start()
    await _until(lambda: server.calls("POST", METRICS_PATH))
    await reporter.stop()

    assert metrics_body(server)["bucket"]["toggles"][COUNTED_FLAG]["yes"] == 1


@mark.asyncio
async def test_a_failed_flush_does_not_end_the_loop(build_reporter):
    # One failed send must not end metrics reporting for the life of the client.
    flushes = []
    reporter = build_reporter(metrics_interval=0)

    async def flush():
        flushes.append(len(flushes))
        if len(flushes) == 1:
            raise TypeError("boom")

    reporter.flush = flush

    await reporter.start()
    await _until(lambda: len(flushes) > 1)
    await reporter.stop()


@mark.asyncio
async def test_the_schedule_does_not_drift_by_however_long_a_flush_took(build_reporter):
    # Computing each fire from the clock instead would push every subsequent send out by
    # the duration of the last one, and the drift would compound.
    fires = []
    reporter = build_reporter(metrics_interval=30)

    async def wait_until(fire):
        fires.append(fire)

    reporter._wait_until = wait_until
    reporter.flush = _slow_flush

    await reporter.start()
    await _until(lambda: len(fires) >= 3)
    await reporter.stop()

    # approx only for float addition noise; a clock-anchored schedule would show the
    # 0.01s flush as ~30.01, orders of magnitude outside this tolerance.
    assert fires[1] - fires[0] == pytest.approx(30)
    assert fires[2] - fires[1] == pytest.approx(30)


@mark.asyncio
async def test_stop_flushes_what_is_left_and_cancels_the_task(server, build_reporter):
    # A short-lived client can be destroyed before its first interval elapses, so the
    # bucket has to go out on the way down.
    reporter = build_reporter()
    server.on("POST", METRICS_PATH, status=202, payload={})
    await reporter.start()
    task = reporter._task
    reporter._engine.count_toggle(COUNTED_FLAG, True)

    await reporter.stop()

    assert len(server.calls("POST", METRICS_PATH)) == 1
    assert task.cancelled()
    assert reporter._task is None


@mark.asyncio
async def test_stop_still_flushes_when_the_task_had_already_died(
    server, build_reporter
):
    # The constructor does not validate types, so metrics_interval="abc" builds a client
    # whose task raises on its first cycle.  destroy() still has to work.
    reporter = build_reporter(metrics_interval="abc")
    server.on("POST", METRICS_PATH, status=202, payload={})
    await reporter.start()
    await _until(reporter._task.done)
    reporter._engine.count_toggle(COUNTED_FLAG, True)

    await reporter.stop()

    assert len(server.calls("POST", METRICS_PATH)) == 1


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
    await reporter.start()
    reporter._engine.count_toggle(COUNTED_FLAG, True)

    await reporter.stop()
    await reporter.stop()

    assert len(server.calls("POST", METRICS_PATH)) == 1


@mark.asyncio
async def test_constructing_the_reporter_starts_no_task_and_opens_no_session(
    build_reporter,
):
    # __init__ is synchronous and runs with no loop: the client's constructor has to
    # work before anything is awaited.
    reporter = build_reporter()

    assert reporter._task is None
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


def _recording_flush(flushed: asyncio.Event) -> Callable:
    async def flush() -> None:
        flushed.set()

    return flush


async def _until(condition: Callable, timeout: float = 5) -> None:
    """
    Yields to the loop until `condition` holds.

    The task under test drives the condition, so the wait is on it happening at all --
    the timeout is a failure mode, not an assertion about how long it took.
    """

    async def wait() -> None:
        while not condition():
            await asyncio.sleep(0)

    await asyncio.wait_for(wait(), timeout=timeout)


async def _slow_flush() -> None:
    """A flush that yields, so a schedule computed from the clock would visibly drift."""
    await asyncio.sleep(0.01)
