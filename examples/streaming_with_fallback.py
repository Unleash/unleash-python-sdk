import os
import re
import time
import requests

from UnleashClient import UnleashClient
from UnleashClient.events import UnleashEventType

URL = "http://localhost:3063/api"
TOKEN = "hammer-1:development.4819f784fbe351f8a74982d43a68f53dcdbf74cdde554a5d0a81d997"
FLAG = "flag-page-hh"

headers = {"Authorization": TOKEN}

ready = False


def event_callback(event):
    global ready
    if event.event_type == UnleashEventType.READY:
        ready = True


def check_streaming_support(url, headers):
    """Check if the Unleash server supports streaming mode."""
    try:
        response = requests.get(f"{url}/client/streaming", headers=headers, timeout=5)
        if response.status_code == 200:
            return True
        elif (
            response.status_code == 403
            and "only enabled in streaming mode" in response.text
        ):
            return False
        else:
            return False
    except Exception:
        return False


# Check if streaming is supported
streaming_supported = check_streaming_support(URL, headers)
print(f"Streaming support detected: {streaming_supported}")

if streaming_supported:
    print("Using streaming mode")
    client = UnleashClient(
        url=URL,
        app_name="python-streaming-example",
        instance_id="example-instance",
        custom_headers=headers,
        experimental_mode={"type": "streaming"},
        event_callback=event_callback,
    )
    mode_description = "streaming"
else:
    print("Streaming not supported, falling back to polling mode")
    client = UnleashClient(
        url=URL,
        app_name="python-streaming-example",
        instance_id="example-instance",
        custom_headers=headers,
        event_callback=event_callback,
    )
    mode_description = "polling"

client.initialize_client()

print(f"Waiting for hydration via {mode_description} (Ctrl+C to exit)")

try:
    while True:
        if not client.is_initialized:
            print("Client not initialized yet, waiting...")
            time.sleep(0.2)
            continue
        if not ready:
            print(f"Waiting for hydration via {mode_description}... (Ctrl+C to exit)")
            time.sleep(0.2)
            continue
        enabled = client.is_enabled(FLAG, {"userId": "example"})
        print(f"{FLAG} enabled? {enabled}")
        time.sleep(1)
except KeyboardInterrupt:
    pass
finally:
    client.destroy()
