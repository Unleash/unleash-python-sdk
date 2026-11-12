# ruff: noqa: F401
from typing import TYPE_CHECKING

from .clients import (
    INSTANCES,
    UnleashClient,
    build_ready_callback,
)
from .config import (
    IdentityOptions,
    MetricsOptions,
    PollingOptions,
    StreamingOptions,
)
from .transport import AsyncTransport, Method, Request, Response, Transport
from .transport._requests import RequestsTransport

if TYPE_CHECKING:
    from .clients.async_unleash_client import AsyncUnleashClient
    from .transport._aiohttp import AiohttpTransport


def __getattr__(name: str):
    if name == "AsyncUnleashClient":
        from .clients.async_unleash_client import AsyncUnleashClient  # noqa: PLC0415

        return AsyncUnleashClient
    if name == "AiohttpTransport":
        from .transport._aiohttp import AiohttpTransport  # noqa: PLC0415

        return AiohttpTransport
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
