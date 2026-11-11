# ruff: noqa: F401
from typing import TYPE_CHECKING

from ._requests_transport import RequestsTransport
from .clients import (
    INSTANCES,
    UnleashClient,
    build_ready_callback,
)
from .config import (
    HttpOptions,
    IdentityOptions,
    MetricsOptions,
    PollingOptions,
    StreamingOptions,
)
from .transport import AsyncTransport, Method, Request, Response, Transport

if TYPE_CHECKING:
    from ._aiohttp_transport import AiohttpTransport
    from .clients.async_unleash_client import AsyncUnleashClient


def __getattr__(name: str):
    if name == "AsyncUnleashClient":
        from .clients.async_unleash_client import AsyncUnleashClient  # noqa: PLC0415

        return AsyncUnleashClient
    if name == "AiohttpTransport":
        from ._aiohttp_transport import AiohttpTransport  # noqa: PLC0415

        return AiohttpTransport
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
