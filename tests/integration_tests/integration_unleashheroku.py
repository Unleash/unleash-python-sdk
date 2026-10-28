# ---
import logging
import sys
import time

from UnleashClient import UnleashClient
from UnleashClient.config import IdentityOptions

root = logging.getLogger()
root.setLevel(logging.DEBUG)

handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
root.addHandler(handler)
# ---

my_client = UnleashClient(
    url="https://unleash.herokuapp.com/api",
    app_name="pyIvan",
    identity=IdentityOptions(environment="staging"),
)

my_client.initialize_client()

while True:
    time.sleep(10)
    context = {"userId": "1", "sound": "woof"}
    print(f"ivantest: {my_client.is_enabled('ivantest', context)}")
