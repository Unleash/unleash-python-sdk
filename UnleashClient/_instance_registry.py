"""Duplicate-instance detection, shared by the sync and async Unleash clients."""

import threading
from typing import Dict

from UnleashClient.config import UnleashConfig, redact_to_print_safely
from UnleashClient.errors import MultipleInstancesNotAllowedError
from UnleashClient.utils import LOGGER, InstanceAllowType


def _instance_identifier(config: UnleashConfig) -> str:
    """The key a client is registered under.  Redacts the API key."""
    return f"apiKey:{redact_to_print_safely(config.api_key)} appName:{config.app_name} instanceId:{config.identity.instance_id}"


class _InstanceRegistry:
    """
    Counts live client configurations and applies the duplicate-instance policy.

    Clients are keyed by :func:`_instance_identifier`, which redacts the API
    key. A client rejected under
    :attr:`~UnleashClient.utils.InstanceAllowType.BLOCK` is not counted, so the
    count only ever covers clients that were actually built.

    Example::

        registry = _get_instance_registry()
        identifier = _instance_identifier(config)
        registry.register(identifier=identifier, mode=InstanceAllowType.WARN)
        registry.count(key=identifier)
    """

    def __init__(self) -> None:
        self.instances: Dict[str, int] = {}
        self.lock = threading.RLock()

    def register(self, identifier: str, mode: InstanceAllowType) -> None:
        """
        Record a client under ``identifier`` and apply ``mode`` if it repeats.

        Raises on :attr:`~UnleashClient.utils.InstanceAllowType.BLOCK`, logs an
        error on :attr:`~UnleashClient.utils.InstanceAllowType.WARN`, and is
        silent on :attr:`~UnleashClient.utils.InstanceAllowType.SILENTLY_ALLOW`.

        :raises MultipleInstancesNotAllowedError: if ``identifier`` is already
            registered and ``mode`` is
            :attr:`~UnleashClient.utils.InstanceAllowType.BLOCK`.
        """
        with self.lock:
            if identifier in self:
                msg = f"You already have {self.count(identifier)} instance(s) configured for this config: {identifier}, please double check the code where this client is being instantiated."
                if mode == InstanceAllowType.BLOCK:
                    raise MultipleInstancesNotAllowedError(msg)
                if mode == InstanceAllowType.WARN:
                    LOGGER.error(msg)
            self.increment(identifier)

    def __contains__(self, key: str) -> bool:
        with self.lock:
            return key in self.instances

    def count(self, key: str) -> int:
        with self.lock:
            return self.instances.get(key, 0)

    def increment(self, key: str) -> None:
        with self.lock:
            self.instances[key] = self.instances.get(key, 0) + 1

    def _reset(self) -> None:
        with self.lock:
            self.instances = {}


_REGISTRY = _InstanceRegistry()


def _get_instance_registry() -> _InstanceRegistry:
    """Return the process-wide registry every Unleash client registers into."""
    return _REGISTRY
