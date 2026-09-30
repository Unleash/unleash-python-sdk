# ruff: noqa: F401
from typing import TYPE_CHECKING

from .clients import (
    INSTANCES,
    ExperimentalMode,
    UnleashClient,
    build_ready_callback,
)

if TYPE_CHECKING:
    from .clients.async_unleash_client import AsyncUnleashClient


def __getattr__(name: str):
    if name == "AsyncUnleashClient":
        from .clients.async_unleash_client import AsyncUnleashClient  # noqa: PLC0415

        return AsyncUnleashClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
