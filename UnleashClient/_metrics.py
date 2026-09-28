"""Metrics reporting, for the sync and async Unleash clients."""

from typing import Optional

from yggdrasil_engine.engine import UnleashEngine

from UnleashClient._async_scheduler import _AsyncJob, _AsyncScheduler
from UnleashClient._async_transport import _AsyncTransport
from UnleashClient._scheduler import _ScheduledJob, _Scheduler
from UnleashClient._transport import _Transport
from UnleashClient.config import UnleashConfig
from UnleashClient.impact_metrics import ImpactMetrics
from UnleashClient.payloads import build_metrics_payload
from UnleashClient.utils import LOGGER


class _MetricsReporter:
    """
    Owns the metrics send: the recurring job, the one-shot flush, and the shutdown
    flush that runs before the scheduler goes away.

    Example::

        reporter = _MetricsReporter(
            config=config,
            transport=transport,
            scheduler=scheduler,
            engine=engine,
            impact_metrics=impact_metrics,
        )
        reporter.start()

        reporter.flush()

        reporter.stop()
    """

    def __init__(
        self,
        config: UnleashConfig,
        transport: _Transport,
        scheduler: _Scheduler,
        engine: UnleashEngine,
        impact_metrics: ImpactMetrics,
    ) -> None:
        self._config: UnleashConfig = config
        self._transport: _Transport = transport
        self._scheduler: _Scheduler = scheduler
        self._engine: UnleashEngine = engine
        self._impact_metrics: ImpactMetrics = impact_metrics
        self._job: _ScheduledJob = None

    @property
    def job(self) -> _ScheduledJob:
        """The registered job, or None before :meth:`start` and after :meth:`stop`."""
        return self._job

    @job.setter
    def job(self, value: _ScheduledJob) -> None:
        self._job = value

    def start(self) -> None:
        """Registers the recurring send."""
        self._job = self._scheduler.every(
            interval_seconds=int(self._config.metrics_interval),
            jitter_seconds=self._config.metrics_jitter,
            fn=self.flush,
        )

    def flush(self) -> None:
        """
        Collects one bucket and sends it.

        Sends nothing when there is nothing to report.  Impact metrics are handed back
        to the engine when the send fails, so the next flush carries them instead.
        """
        bucket = self._engine.get_metrics()
        impact_metrics = self._impact_metrics.collect()

        if not (bucket or impact_metrics):
            LOGGER.debug("No feature flags with metrics, skipping metrics submission.")
            return

        payload = build_metrics_payload(self._config, bucket, impact_metrics)
        if not self._transport.send_metrics(payload) and impact_metrics:
            self._impact_metrics.restore(impact_metrics)

    def stop(self) -> None:
        """
        Flushes what is left and cancels the job.

        A no-op when no job was ever registered, which is the case for a client with
        metrics disabled and for one that was destroyed without being initialized.
        """
        if not self._job:
            return

        self.flush()
        self._scheduler.cancel(self._job)
        self._job = None


class _AsyncMetricsReporter:
    """
    Sends feature and impact metrics to Unleash on a recurring interval.

    :meth:`start` must be called, and :meth:`stop` awaited, from the event loop the client
    runs on, and the loop must stay open for as long as metrics are being reported.

    Example::

        reporter = _AsyncMetricsReporter(
            config=config,
            transport=transport,
            scheduler=scheduler,
            engine=engine,
            impact_metrics=impact_metrics,
        )
        reporter.start()

        await reporter.flush()

        await reporter.stop()
    """

    def __init__(
        self,
        config: UnleashConfig,
        transport: _AsyncTransport,
        scheduler: _AsyncScheduler,
        engine: UnleashEngine,
        impact_metrics: ImpactMetrics,
    ) -> None:
        self._config: UnleashConfig = config
        self._transport: _AsyncTransport = transport
        self._scheduler: _AsyncScheduler = scheduler
        self._engine: UnleashEngine = engine
        self._impact_metrics: ImpactMetrics = impact_metrics
        self._job: Optional[_AsyncJob] = None

    def start(self) -> None:
        """Schedules a send every ``metrics_interval`` seconds, with ``metrics_jitter`` of jitter."""
        self._job = self._scheduler.every(
            interval_seconds=int(self._config.metrics_interval),
            jitter_seconds=self._config.metrics_jitter,
            fn=self.flush,
        )

    async def flush(self) -> None:
        """
        Sends one bucket of feature and impact metrics.

        Sends nothing when neither has anything to report. When a send fails or is
        cancelled, its impact metrics are restored so the next send carries them.
        """
        bucket = self._engine.get_metrics()
        impact_metrics = self._impact_metrics.collect()

        if not (bucket or impact_metrics):
            LOGGER.debug("No feature flags with metrics, skipping metrics submission.")
            return

        payload = build_metrics_payload(self._config, bucket, impact_metrics)
        sent = False
        try:
            sent = await self._transport.send_metrics(payload)
        finally:
            if not sent and impact_metrics:
                self._impact_metrics.restore(impact_metrics)

    async def stop(self) -> None:
        """
        Stops the recurring send and flushes whatever is left.

        Does nothing when :meth:`start` was never called. A send still in flight is
        cancelled: its impact metrics go out with the final flush, and its feature
        metrics are lost.
        """
        if self._job is None:
            return

        job, self._job = self._job, None
        await self._scheduler.cancel_and_wait(job)
        await self.flush()
