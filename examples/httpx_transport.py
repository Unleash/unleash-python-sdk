"""
Send the SDK's requests with httpx instead of requests.

A transport only needs an ``execute(Request) -> Response`` method. It sends
each request once: the SDK retries feature fetches itself.
"""

import httpx

from UnleashClient import Request, Response, UnleashClient


class HttpxTransport:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def execute(self, request: Request) -> Response:
        resp = self._client.request(
            request.method,
            request.url,
            headers=dict(request.headers),
            params=dict(request.params),
            content=request.body,
        )
        return Response(
            status=resp.status_code, headers=resp.headers, body=resp.content
        )


if __name__ == "__main__":
    with httpx.Client(timeout=30) as http_client:
        with UnleashClient(
            "https://unleash.example.com/api",
            "my-app",
            api_key="<API token>",
            transport=HttpxTransport(http_client),
        ) as client:
            print(client.is_enabled("new-checkout"))
