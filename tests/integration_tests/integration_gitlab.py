# ---
import logging
import sys
import time

from UnleashClient import UnleashClient
from UnleashClient.config import MetricsOptions, UnleashConfig

root = logging.getLogger()
root.setLevel(logging.DEBUG)

handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
root.addHandler(handler)
# ---


my_client = UnleashClient(
    UnleashConfig(
        url="https://gitlab.com/api/v4/feature_flags/unleash/32635317",
        app_name="pyIvan",
        instance_id="Sc5fv9aCyFPB4XcEFk-E",
        disable_registration=True,
        metrics=MetricsOptions(disabled=True),
    )
)

my_client.initialize_client()

while True:
    time.sleep(10)
    print(my_client.is_enabled("test"))
