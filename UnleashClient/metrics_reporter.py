"""Metrics reporting, for the sync Unleash client."""

from yggdrasil_engine.engine import UnleashEngine

from UnleashClient.config import UnleashConfig
from UnleashClient.impact_metrics import ImpactMetrics
from UnleashClient.payloads import build_metrics_payload
from UnleashClient.scheduler import ScheduledJob, Scheduler
from UnleashClient.transport import Transport
from UnleashClient.utils import LOGGER


class MetricsReporter:
    """
    Owns the metrics send: the recurring job, the one-shot flush, and the shutdown
    flush that runs before the scheduler goes away.
    """

    def __init__(
        self,
        config: UnleashConfig,
        transport: Transport,
        scheduler: Scheduler,
        engine: UnleashEngine,
        impact_metrics: ImpactMetrics,
    ) -> None:
        self._config: UnleashConfig = config
        self._transport: Transport = transport
        self._scheduler: Scheduler = scheduler
        self._engine: UnleashEngine = engine
        self._impact_metrics: ImpactMetrics = impact_metrics
        self._job: ScheduledJob = None

    @property
    def job(self) -> ScheduledJob:
        """The registered job, or None before :meth:`start` and after :meth:`stop`."""
        return self._job

    @job.setter
    def job(self, value: ScheduledJob) -> None:
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
