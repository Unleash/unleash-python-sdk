# ---
import logging
import sys
import time

from UnleashClient import UnleashClient
from UnleashClient.config import UnleashConfig

root = logging.getLogger()
root.setLevel(logging.DEBUG)

handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
root.addHandler(handler)
# ---

my_client = UnleashClient(
    UnleashConfig(url="http://localhost:4242/api", app_name="pyIvan")
)

my_client.initialize_client()

while True:
    time.sleep(10)
    print(my_client.is_enabled("Demo"))
