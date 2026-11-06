"""
Send the async client's requests with httpx instead of aiohttp.

An async transport only needs an ``async execute(Request) -> Response``
method. It sends each request once: the SDK retries feature fetches itself.
"""

import asyncio

import httpx

from UnleashClient import Request, Response
from UnleashClient.clients.async_unleash_client import AsyncUnleashClient


class HttpxAsyncTransport:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def execute(self, request: Request) -> Response:
        resp = await self._client.request(
            request.method,
            request.url,
            headers=dict(request.headers),
            params=dict(request.params),
            content=request.body,
        )
        return Response(
            status=resp.status_code, headers=resp.headers, body=resp.content
        )


async def main() -> None:
    async with httpx.AsyncClient(timeout=30) as http_client:
        async with AsyncUnleashClient(
            "https://unleash.example.com/api",
            "my-app",
            api_key="<API token>",
            transport=HttpxAsyncTransport(http_client),
        ) as client:
            print(client.is_enabled("new-checkout"))


if __name__ == "__main__":
    asyncio.run(main())
