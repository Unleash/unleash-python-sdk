# ---
import logging
import random
import sys
import time

from UnleashClient import UnleashClient
from UnleashClient.impact_metrics import MetricFlagContext

root = logging.getLogger()
root.setLevel(logging.DEBUG)

handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
root.addHandler(handler)
# ---

my_client = UnleashClient(
    url="https://sandbox.getunleash.io/enterprise/api/",
    app_name="pyIvan",
    environment="development",
    custom_headers={
        "Authorization": "impact-metrics:development.6d70e55dd70dd79f5be3ce97835996000db94ed997c492421effe935"
    },
)

my_client.initialize_client()

# Define impact metrics
my_client.impact_metrics.define_counter("purchases", "Number of purchases made")
my_client.impact_metrics.define_gauge("active_users", "Current number of active users")
my_client.impact_metrics.define_histogram(
    "request_latency", "Request latency in seconds", [0.01, 0.05, 0.1, 0.5, 1.0, 5.0]
)

# Track active users count
active_users = 100

while True:
    time.sleep(10)
    print(f"Demo enabled: {my_client.is_enabled('Demo')}")

    # Create flag context for metrics (ties metrics to feature flag state)
    flag_context = MetricFlagContext(
        flag_names=["Demo"],
        context={"userId": "integration-test-user"},
    )

    # Increment counter (simulate a purchase)
    my_client.impact_metrics.increment_counter("purchases", 1, flag_context)
    print("Incremented purchases counter")

    # Update gauge (simulate active users changing)
    active_users += random.randint(-10, 15)
    active_users = max(0, active_users)  # Don't go negative
    my_client.impact_metrics.update_gauge("active_users", active_users, flag_context)
    print(f"Updated active_users gauge to {active_users}")

    # Observe histogram (simulate request latency)
    latency = random.uniform(0.01, 2.0)
    my_client.impact_metrics.observe_histogram("request_latency", latency, flag_context)
    print(f"Observed request_latency: {latency:.3f}s")
