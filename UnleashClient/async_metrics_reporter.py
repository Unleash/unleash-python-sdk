"""Metrics reporting for the asynchronous Unleash client.

Importing this module requires the optional ``aiohttp`` dependency:
``pip install UnleashClient[async]``.
"""

from yggdrasil_engine.engine import UnleashEngine

from UnleashClient._async_scheduler import _AsyncScheduledJob, _AsyncScheduler
from UnleashClient.async_transport import AsyncTransport
from UnleashClient.config import UnleashConfig
from UnleashClient.impact_metrics import ImpactMetrics
from UnleashClient.payloads import build_metrics_payload
from UnleashClient.utils import LOGGER


class AsyncMetricsReporter:
    """
    Sends feature and impact metrics to Unleash on a recurring interval.

    :meth:`start` and :meth:`stop` must be awaited from the event loop the client runs
    on, and the loop must stay open for as long as metrics are being reported.

    The request is built from the :class:`~UnleashClient.config.UnleashConfig` at send
    time, so reassigning a client's ``unleash_*`` attributes takes effect from the next
    send.  ``metrics_interval`` and ``metrics_jitter`` are read once, by :meth:`start`.
    """

    def __init__(
        self,
        config: UnleashConfig,
        transport: AsyncTransport,
        scheduler: _AsyncScheduler,
        engine: UnleashEngine,
        impact_metrics: ImpactMetrics,
    ) -> None:
        """
        :param config: read on every send for the request body, and by :meth:`start`
                       for the interval and the jitter.
        :param transport: sends the request.
        :param scheduler: runs the recurring send.
        :param engine: read for the feature metrics bucket.  Separate from
                       ``impact_metrics``, which is a different set of numbers that
                       happens to be stored in the same engine.
        :param impact_metrics: drained for each send, and restored when a send fails.
        """
        self._config: UnleashConfig = config
        self._transport: AsyncTransport = transport
        self._scheduler: _AsyncScheduler = scheduler
        self._engine: UnleashEngine = engine
        self._impact_metrics: ImpactMetrics = impact_metrics
        self._job: _AsyncScheduledJob = None

    async def start(self) -> None:
        """Registers the recurring send with the scheduler."""
        self._job = self._scheduler.every(
            interval_seconds=int(self._config.metrics_interval),
            jitter_seconds=self._config.metrics_jitter,
            fn=self.flush,
        )

    async def flush(self) -> None:
        """
        Sends one bucket of feature and impact metrics.

        Sends nothing when neither has anything to report.  Impact metrics are handed
        back to the engine when the send fails, so the next send carries them instead.
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

        Does nothing when :meth:`start` was never called.  Metrics drained by a send
        that is still in flight are lost with it.
        """
        if self._job is None:
            return

        job, self._job = self._job, None
        await self._scheduler.cancel_and_wait(job)
        await self.flush()
