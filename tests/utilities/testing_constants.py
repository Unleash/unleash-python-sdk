from UnleashClient.constants import FEATURES_URL

# General configs
APP_NAME = "pytest"
ENVIRONMENT = "unit"
INSTANCE_ID = "123"
CONNECTION_ID = "test-connection-id"
REFRESH_INTERVAL = 1
REFRESH_JITTER = None
METRICS_INTERVAL = 2
METRICS_JITTER = None
DISABLE_METRICS = True
DISABLE_REGISTRATION = True
CUSTOM_HEADERS = {"name": "My random header."}
CUSTOM_OPTIONS = {"verify": False}
REQUEST_TIMEOUT = 30
REQUEST_RETRIES = 3

# URLs
URL = "http://localhost:4242/api"
INTEGRATION_URL = "http://localhost:4242/api"
PROJECT_URL = f"{URL}{FEATURES_URL}?project=ivan"

# Constants
IP_LIST = (
    "69.208.0.0/29,70.208.1.1,2001:db8:1234::/48,2002:db8:1234:0000:0000:0000:0000:0001"
)
PROJECT_NAME = "ivan"
ETAG_VALUE = 'W/"730-v0ozrE11zfZK13j7rQ5PxkXfjYQ"'
