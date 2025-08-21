# ---
import logging
import os
import sys
import time

from UnleashClient import UnleashClient

root = logging.getLogger()
root.setLevel(logging.DEBUG)

handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
root.addHandler(handler)
# ---

api_url = os.getenv("UNLEASH_API_URL", "https://app.unleash-hosted.com/demo/api")
api_token = os.getenv(
    "UNLEASH_API_TOKEN",
    "demo-app:dev.9fc74dd72d2b88bea5253c04240b21a54841f08d9918046ed55a06b5",
)
flag = "example-flag"
use_streaming = os.getenv("USE_STREAMING", "true").lower() == "true"

client = UnleashClient(
    url=api_url,
    app_name="integration-python",
    custom_headers={"Authorization": api_token},
    experimental_mode={"type": "streaming"} if use_streaming else None,
    metrics_interval=1,
)

client.initialize_client()

while True:
    print(f"'{flag}' is enabled: {client.is_enabled(flag)}")
    time.sleep(3)
