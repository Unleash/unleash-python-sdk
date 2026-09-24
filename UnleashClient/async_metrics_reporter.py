"""Metrics reporting, for the async Unleash client."""

from typing import Optional

from yggdrasil_engine.engine import UnleashEngine

from UnleashClient._async_scheduler import _AsyncJob, _AsyncScheduler
from UnleashClient.async_transport import AsyncTransport
from UnleashClient.config import UnleashConfig
from UnleashClient.impact_metrics import ImpactMetrics
from UnleashClient.payloads import build_metrics_payload
from UnleashClient.utils import LOGGER


class AsyncMetricsReporter:
    """
    Sends feature and impact metrics to Unleash on a recurring interval.

    :meth:`start` must be called, and :meth:`stop` awaited, from the event loop the client
    runs on, and the loop must stay open for as long as metrics are being reported.

    Example::

        reporter = AsyncMetricsReporter(
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
        transport: AsyncTransport,
        scheduler: _AsyncScheduler,
        engine: UnleashEngine,
        impact_metrics: ImpactMetrics,
    ) -> None:
        self._config: UnleashConfig = config
        self._transport: AsyncTransport = transport
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

        Sends nothing when neither has anything to report. When a send fails, its impact
        metrics are restored so the next send carries them.
        """
        bucket = self._engine.get_metrics()
        impact_metrics = self._impact_metrics.collect()

        if not (bucket or impact_metrics):
            LOGGER.debug("No feature flags with metrics, skipping metrics submission.")
            return

        payload = build_metrics_payload(self._config, bucket, impact_metrics)
        if not await self._transport.send_metrics(payload) and impact_metrics:
            self._impact_metrics.restore(impact_metrics)

    async def stop(self) -> None:
        """
        Stops the recurring send and flushes whatever is left.

        Does nothing when :meth:`start` was never called. Metrics drained by a send
        that is still in flight are lost with it.
        """
        if self._job is None:
            return

        job, self._job = self._job, None
        await self._scheduler.cancel_and_wait(job)
        await self.flush()
