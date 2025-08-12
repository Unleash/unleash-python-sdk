import os
import re
import time

from UnleashClient import UnleashClient
from UnleashClient.events import UnleashEventType

URL = "https://sandbox.getunleash.io/enterprise/api"
TOKEN = "hammer-1:development.4819f784fbe351f8a74982d43a68f53dcdbf74cdde554a5d0a81d997"
FLAG = "flag-page-hh"

headers = {"Authorization": TOKEN}

ready = False


def event_callback(event):
    global ready
    if event.event_type == UnleashEventType.READY:
        ready = True


client = UnleashClient(
    url=URL,
    app_name="python-streaming-example",
    instance_id="example-instance",
    custom_headers=headers,
    experimental_mode={"type": "streaming"},
    event_callback=event_callback,
)

client.initialize_client()

print("Waiting for hydration via streaming... (Ctrl+C to exit)")

try:
    while True:
        if not client.is_initialized:
            print("Client not initialized yet, waiting...")
            time.sleep(0.2)
            continue
        if not ready:
            # FIXME: check if for other modes this works in the same way
            print("Waiting for hydration via streaming... (Ctrl+C to exit)")
            time.sleep(0.2)
            continue
        enabled = client.is_enabled(FLAG, {"userId": "example"})
        print(f"{FLAG} enabled? {enabled}")
        time.sleep(1)
except KeyboardInterrupt:
    pass
finally:
    client.destroy()
