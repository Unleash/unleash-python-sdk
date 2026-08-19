"""Metrics reporting, the sync half of one colored leaf."""

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

    :meth:`flush` performs I/O through the :class:`~UnleashClient.transport.Transport`,
    which makes this a colored object -- an asyncio client needs its own implementation
    rather than this one, and gets it in a later step.  Everything on the boundary is
    shared: the payload comes from
    :func:`~UnleashClient.payloads.build_metrics_payload`, the job registration from
    :class:`~UnleashClient.scheduler.Scheduler`.

    The config is read on every send rather than captured at construction, because the
    client's ``unleash_*`` setters write through it.  The interval and jitter are the
    exception: they are read once, when the job is registered, since that is what
    registering a trigger means.
    """

    def __init__(
        self,
        config: UnleashConfig,
        transport: Transport,
        scheduler: Scheduler,
        engine: UnleashEngine,
        impact_metrics: ImpactMetrics,
    ) -> None:
        """
        :param engine: read for the toggle metrics bucket.  Separate from
                       ``impact_metrics``, which is a different set of numbers that
                       happens to be stored in the same engine.
        :param impact_metrics: collected from and restored to, so this object is the
                               only one that touches the engine's impact metrics.
        """
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
        """
        Registers the recurring send.

        ``int()`` on the interval, because the metrics call site has always coerced it
        and ``Scheduler.every`` deliberately does not.
        """
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
        metrics disabled and for one that was destroyed without being initialized.  The
        check is on truthiness rather than ``is None``: a custom scheduler's ``add_job``
        may return nothing.
        """
        if not self._job:
            return

        self.flush()
        self._scheduler.cancel(self._job)
        self._job = None
