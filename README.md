# Unleash SDK for Python

![](https://github.com/unleash/unleash-python-sdk/workflows/CI/badge.svg?branch=main) [![Coverage Status](https://coveralls.io/repos/github/Unleash/unleash-python-sdk/badge.svg?branch=main)](https://coveralls.io/github/Unleash/unleash-python-sdk?branch=main) [![PyPI version](https://badge.fury.io/py/UnleashClient.svg)](https://badge.fury.io/py/UnleashClient) ![PyPI - Python Version](https://img.shields.io/pypi/pyversions/UnleashClient.svg) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Unleash is a private, secure, and scalable [feature management platform](https://www.getunleash.io/) built to reduce the risk of releasing new features and accelerate software development. This server-side Python SDK is designed to help you integrate with Unleash and evaluate feature flags inside your application.

You can use this client with [Unleash Enterprise](https://www.getunleash.io/pricing?utm_source=readme&utm_medium=python) or [Unleash Open Source](https://github.com/Unleash/unleash).

> **Migrating to v7**
>
> The client's settings are now grouped into option objects, and every argument after `url` and `app_name` is keyword-only. Read the [v7 migration guide](./v7_MIGRATION_GUIDE.md) before upgrading.

> **Migrating to v6**
>
> If you use custom strategies or access the `features` property on the Unleash Client, read the complete [migration guide](./v6_MIGRATION_GUIDE.md) before upgrading to v6.

## Getting Started

### Install the Unleash Client in your project

```bash
pip install UnleashClient
```

### Initialization

You must initialize the SDK before you use it. Note that until the SDK has synchronized with the API, all features will evaluate to `false` unless
you have a [bootstrapped configuration](#bootstrap) or you use [fallbacks](#fallback-function).

```python
from UnleashClient import UnleashClient

client = UnleashClient(
    url="https:<YOUR-API-URL>",
    app_name="my-python-app",
    api_key="<API token>")

client.initialize_client()
```

### Check features

Once the SDK is initialized, you can evaluate toggles using the `is_enabled` or `get_variant` methods.

```python
enabled = client.is_enabled("my_toggle")
print(enabled)
> True

variant = client.get_variant("variant_toggle")
print(variant)
> {
>    "name": "variant1",
>    "payload": {
>        "type": "string",
>        "value": "val1"
>        },
>    "enabled": True
> }

```

### Shutdown

If your program no longer needs the SDK, you can call `destroy()`, which shuts down the SDK and flushes any pending metrics to Unleash.

```python
client.destroy()
```

## Usage

### Context

Both the `is_enabled` and `get_variant` functions support [Unleash contexts](https://docs.getunleash.io/reference/unleash-context) as the second parameter.

``` python
app_context = {
    "userId": "test@email.com",
    "sessionId": "55845",
    "properties": {
        "custom-property": "some-value"
    }
}

client.is_enabled("user_id_toggle", app_context)
client.get_variant("variant_toggle", app_context)
```

The context values can be any type that has a `__str__` implementation. Types that are explicitly supported are:

- Numerics
- Strings
- Dates
- UUIDs

**Note**: Gradual rollout strategies require you to pass either a `userId` or a `sessionId` for [stickiness](https://docs.getunleash.io/reference/stickiness) to work correctly.

### Fallback function

You can specify a fallback function for cases where the client doesn't recognize the toggle by using the `fallback_function` keyword argument:

```python
def custom_fallback(feature_name: str, context: dict) -> bool:
    return True

client.is_enabled("my_toggle", fallback_function=custom_fallback)
```

The fallback function **must** accept the feature name and context as positional arguments in that order.

The client will evaluate the fallback function if the feature flag is not found or an exception occurs when calling the `is_enabled()` method.

### Configuration options

`url` and `app_name` are required. Everything else is a keyword argument, and related settings are grouped into option objects:

```python
from UnleashClient import (
    HttpOptions, IdentityOptions, MetricsOptions, PollingOptions, UnleashClient,
)

client = UnleashClient(
    url="https://YOUR-API-URL",
    app_name="my-python-app",
    identity=IdentityOptions(environment="production"),
    api_key="<API token>",
    http=HttpOptions(timeout=10),
    mode=PollingOptions(interval=30),
    metrics=MetricsOptions(disabled=True),
)
```

Settings can't be changed after the client is created.

| Parameter              | Description                                                                                                                               | Default             |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | ------------------- |
| url                    | URL of your Unleash server, e.g. `https://app.unleash-hosted.com/demo/api/`. Required.                                                    | —                   |
| app_name               | Name of the application using the client. Required.                                                                                       | —                   |
| api_key                | Client API token, sent as the `Authorization` header. | None                |
| identity               | How the client identifies itself. See [`IdentityOptions`](#identityoptions).                                                              | `IdentityOptions()` |
| http                   | How the client talks to the server. See [`HttpOptions`](#httpoptions).                                                                    | `HttpOptions()`     |
| mode                   | How the client receives flag updates: [`PollingOptions`](#pollingoptions) or [`StreamingOptions`](#streamingoptions).                     | `PollingOptions()`  |
| metrics                | How the client reports to the server. See [`MetricsOptions`](#metricsoptions).                                                            | `MetricsOptions()`  |
| verbose_log_level      | [Log level](https://docs.python.org/3/library/logging.html#logging-levels) for messages about unknown flags and failed impression events. | 30                  |
| custom_strategies      | Dict of `{name: strategy}` for custom activation strategies. See [custom strategies](#custom-strategies).                                 | None                |
| cache                  | Custom cache implementation (must extend `BaseCache`). See [custom cache](#custom-cache).                                                 | `FileCache`         |
| cache_directory        | Directory for the default `FileCache`. When unset, a platform-specific user cache directory is used. Ignored when `cache` is given.       | None                |
| scheduler              | Custom APScheduler instance. When unset, the client creates a `BackgroundScheduler`. Sync client only.                                    | None                |
| scheduler_executor     | Name of the executor to use on your custom `scheduler`. Required with `scheduler`. Sync client only.                                      | None                |
| multiple_instance_mode | How to handle multiple client instances (`BLOCK`, `WARN`, `SILENTLY_ALLOW`).                                                              | `WARN`              |
| event_callback         | Function that receives impression and lifecycle events. See [events and impression data](#events-and-impression-data).                    | None                |

#### `IdentityOptions`

| Parameter          | Description                                                                            | Default              |
| ------------------ | -------------------------------------------------------------------------------------- | -------------------- |
| environment        | Logical environment name. Deprecated: the environment is determined by your API token. | "default"            |
| instance_id        | Unique identifier for this client instance.                                            | "unleash-python-sdk" |
| sdk_flavor         | Identifier of an integration built on this SDK (e.g. an OpenFeature provider).         | None                 |
| sdk_flavor_version | Version of the integration named by `sdk_flavor`.                                      | None                 |

#### `HttpOptions`

| Parameter | Description                                                                                                                        | Default |
| --------- | ---------------------------------------------------------------------------------------------------------------------------------- | ------- |
| headers   | Extra HTTP headers sent with every request. Pass the API token as `api_key`; an `Authorization` header here raises `ValueError`.   | None    |
| options   | Extra keyword arguments for every [HTTP request](https://requests.readthedocs.io/en/latest/api/#main-interface). Sync client only. | None    |
| timeout   | HTTP request timeout (seconds).                                                                                                    | 30      |
| retries   | How many times a failed feature fetch is retried.                                                                                  | 3       |

#### `PollingOptions`

The default: the client fetches feature flags from the server on an interval.

| Parameter    | Description                                           | Default |
| ------------ | ----------------------------------------------------- | ------- |
| interval     | How often to fetch feature flags (seconds).           | 15      |
| jitter       | Maximum random delay added to each refresh (seconds). | None    |
| project_name | Only fetch the feature flags of this project.         | None    |

#### `StreamingOptions`

Experimental: the client keeps a streaming connection open and receives flag updates as they happen. Pass `mode=StreamingOptions()`. It has no settings yet. `AsyncUnleashClient` doesn't support streaming.

#### `MetricsOptions`

| Parameter            | Description                                                | Default |
| -------------------- | ---------------------------------------------------------- | ------- |
| interval             | How often to send metrics to Unleash (seconds).            | 60      |
| jitter               | Maximum random delay added to each metrics send (seconds). | None    |
| disabled             | Disable sending usage metrics.                             | False   |
| disable_registration | Disable client registration.                               | False   |

### Bootstrap

By default, the Python SDK fetches your feature flags from the Unleash API at startup. If you want to make your SDK more resilient (e.g., during network outages), you can bootstrap the client with a local or remote toggle config.

How it works:

- Use a FileCache (or your own BaseCache implementation).

- Pre-seed it with feature flags using bootstrap_from_dict, bootstrap_from_file, or bootstrap_from_url.

- Pass your cache to the UnleashClient on startup.

The default FileCache has built-in methods for bootstrapping from a dictionary, file, or URL.

#### Bootstrap from dict

```python
from UnleashClient.cache import FileCache
from UnleashClient import UnleashClient

# Create and seed the cache
cache = FileCache("MY_CACHE")
cache.bootstrap_from_dict({
    "version": 2,
    "features": [
        {
            "name": "my_toggle",
            "enabled": True,
            "strategies": [{"name": "default"}],
        }
    ]
})

client = UnleashClient(
    url="https://YOUR-API-URL",
    app_name="my-python-app",
    cache=cache
)

```

#### Bootstrap from file

```python
from pathlib import Path
from UnleashClient.cache import FileCache

cache = FileCache("MY_CACHE")
cache.bootstrap_from_file(Path("/path/to/your_bootstrap.json"))

client = UnleashClient(
    url="https://YOUR-API-URL",
    app_name="my-python-app",
    cache=cache
)
```

#### Bootstrap from URL

```python
from UnleashClient.cache import FileCache

cache = FileCache("MY_CACHE")
cache.bootstrap_from_url("https://your-server/bootstrap.json")

client = UnleashClient(
    url="https://YOUR-API-URL",
    app_name="my-python-app",
    cache=cache
)

```

### Custom strategies

The Python SDK lets you define [custom activation strategies](https://docs.getunleash.io/reference/custom-activation-strategies) if the built-in ones don’t cover your needs. This gives you more fine grained control over how your features evaluate.

A custom strategy is just a class that implements an apply method.

``` python

class ActiveForEmailStrategy:
    def apply(self, parameters: dict, context: dict = None) -> bool:
        # Decide if the feature is active for this context
        return context.get("email") in parameters

```

Once you’ve defined your strategy, register it when you initialize the client. The key must match the strategy name in Unleash exactly.

``` python
## You should have a custom strategy defined in Unleash called 'EmailStrategy'
my_custom_strategies = {
    "EmailStrategy": ActiveForEmailStrategy()
}

client = UnleashClient(

    url="https://YOUR-API-URL",
    app_name="my-python-app",
    api_key="<API token>",
    custom_strategies = my_custom_strategies
)

```

### Events and impression data

The Python SDK lets you tap into its behavior through [impression data](https://docs.getunleash.io/reference/impression-data) and lifecycle events.

**Note**: The SDK does not include a built-in event bus — you’ll need to provide your own. The example below shows how to use [Blinker](https://pypi.org/project/blinker/) to send signals.

#### Impression events

To use impression data:

- Enable impression data on your feature flags in the Unleash UI.
- Provide an event_callback function when you initialize the client.

Your callback must accept a single UnleashEvent. You can log it, store it, or send it to another system.

```python
from blinker import signal
from UnleashClient import UnleashClient
from UnleashClient.events import UnleashEvent

send_data = signal('send-data')

@send_data.connect
def receive_data(sender, **kw):
    print("Caught signal from %r, data %r" % (sender, kw))

def example_callback(event: UnleashEvent):
    send_data.send('anonymous', data=event)

client = UnleashClient(
    url="https://YOUR-API-URL",
    app_name="my-python-app",
    api_key="<API token>",
    event_callback=example_callback
)
client.initialize_client()
client.is_enabled("testFlag")

```

Impression callbacks run in-process — keep them fast to avoid blocking your app.

#### Lifecycle events

The same event_callback also delivers lifecycle events:

- FETCHED: triggered when a new version of feature flags is pulled from the Unleash server. (Does not trigger on 304 Not Modified). The FETCHED event includes a features property containing all the feature flags returned by that fetch.
- READY: triggered once when the SDK first loads feature flags from the Unleash server or a local backup.

```python
from blinker import signal
from UnleashClient import UnleashClient
from UnleashClient.events import UnleashEvent, UnleashEventType

send_data = signal('send-data')

@send_data.connect
def receive_data(sender, **kw):
    if kw["data"].event_type == UnleashEventType.READY:
        print("SDK is ready: toggles loaded from Unleash or backup")
    elif kw["data"].event_type == UnleashEventType.FETCHED:
        # Only FETCHED events have a 'features' property
        print("Fetched new feature flags:", kw["data"].features)

def example_callback(event: UnleashEvent):
    send_data.send('anonymous', data=event)

client = UnleashClient(
    url="https://YOUR-API-URL",
    app_name="my-python-app",
    api_key="<API token>",
    event_callback=example_callback
)
client.initialize_client()
client.is_enabled("testFlag")

```

### Impact metrics

Impact metrics are lightweight, application-level time-series metrics stored and visualized directly inside Unleash. They allow you to connect specific application data, such as request counts, error rates, or latency, to your feature flags and release plans.

These metrics help validate feature impact and automate release processes. For instance, you can monitor usage patterns or performance to determine if a feature meets its goals.

The SDK automatically attaches context labels to metrics: `appName` and `environment`.

#### Counters

Use counters for cumulative values that only increase (total requests, errors):

```python
client.impact_metrics.define_counter(
    "request_count",
    "Total number of HTTP requests processed"
)

client.impact_metrics.increment_counter("request_count")
```

#### Gauges

Use gauges for point-in-time values that can go up or down:

```python
client.impact_metrics.define_gauge(
    "total_users",
    "Total number of registered users"
)

client.impact_metrics.update_gauge("total_users", user_count)
```

#### Histograms

Histograms measure value distribution (request duration, response size):

```python
client.impact_metrics.define_histogram(
    "request_time_ms",
    "Time taken to process a request in milliseconds",
    [50, 100, 200, 500, 1000]
)

client.impact_metrics.observe_histogram("request_time_ms", 125)
```

Impact metrics are batched and sent using the same interval as standard SDK metrics.

### Custom cache

By default, the Python SDK stores feature flags in an on-disk cache using fcache. If you need a different storage backend, for example, Redis, memory-only, or a custom database, you can provide your own cache implementation.

Below is an example custom CustomCache using fcache under the hood.

```python
from typing import Optional, Any
from UnleashClient.cache import BaseCache
from fcache.cache import FileCache as _FileCache

class CustomCache(BaseCache):
    # This is specific for FileCache.  Depending on the cache you're using, this may look different!
    def __init__(self, name: str, directory: Optional[str] = None):
        self._cache = _FileCache(name, app_cache_dir=directory)

    def set(self, key: str, value: Any):
        self._cache[key] = value
        self._cache.sync()

    def mset(self, data: dict):
        self._cache.update(data)
        self._cache.sync()

    def get(self, key: str, default: Optional[Any] = None):
        return self._cache.get(key, default)

    def exists(self, key: str):
        return key in self._cache

    def destroy(self):
        return self._cache.delete()
```

Pass your cache instance to the client with the cache argument:

```python
client = UnleashClient(
    url="https://YOUR-API-URL",
    app_name="my-python-app",
    cache=CustomCache("my-cache")
)
```

## Running in multi-process setups

The Python SDK runs a background thread to keep feature flags in sync with the Unleash server. Some runtime environments, like WSGI servers and Celery workers, need extra setup to make sure the SDK works correctly.

### WSGI

When using WSGI servers (e.g., for Flask or Django apps), be aware that:

- Many WSGI setups disable threading by default. The SDK needs threads to poll for updates in the background.
- Make sure to set `enable-threads` in your WSGI config.

When running under uWSGI with multiple processes (using the `--processes` option), you may need to enable the `lazy-apps` option. This ensures each process gets a fresh SDK instance.

See [The Art of Graceful Reloading](https://uwsgi-docs.readthedocs.io/en/latest/articles/TheArtOfGracefulReloading.html#preforking-vs-lazy-apps-vs-lazy) for more details.

### Celery

When using the SDK in Celery tasks, make sure you initialize it inside the worker_process_init event. Otherwise, the worker may run but won’t poll for feature flag updates.

```python
from UnleashClient import UnleashClient
from celery.signals import worker_process_init

client = UnleashClient(
    url="https://YOUR-API-URL",
    app_name="my-python-app",
    api_key="<API token>"
)

@worker_process_init.connect
def configure_workers(sender=None, conf=None, **kwargs):
    client.initialize_client()
```

## Contributing and development

We love community input! If you’d like to report a bug, propose a feature, or improve the SDK, please read our [contribution guide](CONTRIBUTING.md) for how to get started.

For instructions on setting up your development environment, running tests, and publishing, see our [development documentation](DEVELOPMENT.md).

## License

This project is [MIT licensed](https://opensource.org/licenses/MIT).
