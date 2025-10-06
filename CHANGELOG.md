## v6.4.0
* (Minor) Added experimental streaming support.
* (Bugfix) The SDK should shutdown gracefully in a threaded environment, rather than raising an error.

## v6.3.0
* (Minor) Added 'fetch' and 'ready' lifecycle events.

## v6.2.2
* (Bugfix) Arbitrary properties are now allowed in context fields, so long as they have a reasonable string representation.

## v6.2.1
* (Bugfix) Flush metrics if `destroy()`ing client.

## v6.2.0
* (Minor) add unleash interval headers and connection id to payloads

## v6.1.0
* (Minor) standardised client identification headers

## v6.0.1
* (Minor) Use PyPi Publish Github actions
* (Bugfix) Fix permissions for doc publishing
* (Bugfix) custom context properties are respected during evaluation

## v6.0.0
* (Major) swap core for yggdrasil
* (Documentation) v6 migration guide
* (Bugfix) handle cases where the response from upstream is a bad

## v5.12.3
* (Bugfix) Current time context field will automatically populate with UTC aware time ([#324](https://github.com/Unleash/unleash-client-python/pull/324)). Thanks @jacob-indigo!

## v5.12.2
* (Patch) Metrics are extended with richer metadata about runtime

## v5.12.1
* (Bugfix) Packaged wheel no longer includes tests

## v5.12.0
* (Minor) Switch back to mmh3 for Python 3.12 support.

## v5.11.2
* (Bugfix) Metrics counting for dependent feature flags (the previous implementation was incorrect) ([#300](https://github.com/Unleash/unleash-client-python/pull/300) and [#304](https://github.com/Unleash/unleash-client-python/pull/304))

## v5.11.1
* (Minor) Add missing parenthesis
* (Bugfix) Fix/double execution result
* (Documentation) Update readme with developer instructions

## v5.11.0
* (Minor) Configurable timeout and retries

## v5.10.1
* (Minor) Typos in request timeout
* (Minor) Bump client spec

## v5.10.0
* (Minor) add is_feature_enabled to variant response

## v5.9.2
* (Bugfix) Update variants to use a seed value for their hash.  This fixes an issue with variant distribution & gradual rollouts where users were seeing very non-random distributions.

## v5.9.1
* (Minor) Add support for Semver 3 while maintaining backwards compatibility.  Thanks @@chaitanya-parsana!

## v5.9.0
* (Major) Support for dependent features.  Thanks @Tymek!
* (Major) Add request timeout and request retrie paremeters/overides.  Thanks @snosratiershad!
* (Bugfix) Make `check_date_operators` works with dateutil < 2.9.1.
* (Bugfix) Update responses mock for etag test.  Thanks @yjabri!
* (Bugfix) Fix broken link in client spec ddocs.  Thanks @sjaanus!

## v5.8.0
* (Major) Added support for Strategy Variants.

## v5.7.1
* (Bugfix) Fix dependency issue.

## v5.7.0
* (Major) Metrics are now recorded for each variant whenever get_variant is called.
* (Major) Track metrics for unknown features and their variants.
* (Minor) Add docstring for the Unleash client's disable_registration option. Thanks @Lujeni!
* (Minor) Fix a typo in the Cache docstring.
* (Minor) Switch to ruff for linting and black for formatting.

## v5.6.0
* (Major) Add support for event callbacks.

## v5.5.0
* (Minor) SDK now warns when multiple instances are created
* (Bugfix) Fix an issue where the NOT_IN operator behaves incorrectly when inverted and no context is passed

## v5.4.1
* (Bugfix) Fix an issue where custom stickiness fail to calculate correctly
* (Bugfix) Fix floats not working correctly in constraints
* (Bugfix) Fix an issue where timezones would be incorrectly handled in constraints
* (Bugfix) Fix for NOT_IN constraint to handle failure case correctly as per spec
* (Bugfix) Update murmurhash library to resolve correctly on Python 3.10+ without gcc

## v5.4.0
* (Minor) Allow users to pass in an [apscheduler](https://github.com/agronholm/apscheduler) scheduler & executor name.
* (Minor) Remove vestigial reference to `bootstraped` parameter.  Thanks @koffie !

## v5.3.0
* (Minor) Add retries to GET /features.  Thanks @janboll!
* (Minor) Add global segments.  Thanks @sighphyre!
* (Minor) Documentation updates and tweaks.  Thanks @inirudebwoy, @sighphyre, @thomasheartman !

## v5.2.0
* (Minor) Add support for bootstrapping UnleashClient with an initial configuration.
* (Minor) Add flag to disable toggle polling from server.  Thanks @povilasb!

## v5.1.2
* (Bugfix) Clarify logging if Unleash server doesn't return feature provisioning (i.e. HTTP 304).

## v5.1.1
* (Minor) Move UnleashClient logging to the `UnleashClient` logger.
* (Bugfix) Fix logging for UnleashClient.

## v5.1.0
* (Major) Support new constraint operators.
* (Major) Add cache abstraction.  Thanks @walison17!
* (Minor) Refactor `unleash-client-python` to modernize tooling (`setuptools_scm` and centralizing tool config in `pyproject.toml`).
* (Minor) Migrate documentation to Sphinx.

## v5.0.1
* (Bugfix) Fix HTTP 304 handling on `/client/feature` for Gitlab.  Thanks @janLo!

## v5.0.0
* (Breaking) Modify client initialization to allow jitter configuration on refresh/background refresh intervals.  May break code when parameters to UnleashClient are not used as keyword arguments.  Thanks @dryobates and @jstolarski!
* (Major) If client is already initialized, calling `initialize_client()` again won't re-run initialization.
* (Minor) Support HTTP 304 on `/client/feature` endpoint.
* (Minor) Rename `master` to `main`.
* (Documentation) Document running UnleashClient in uWSGI.  Thanks @sighphyre!
* (Documentation) Fix links and formatting.  Thanks @thomasheartman & @sighphyre!

## v4.4.1
* (Minor) Include py.typed to mark package as type-friendly!  Thanks @wbolster!
* (Minor) Fix API url sanitization.  Thanks @romulorosa!

## v4.4.0
* (Minor) Support running Unleash client as a context manager.  Thanks @Piojo !

## v4.3.0
* (Minor) `initialize_client()` will raise exception if UnleashClient is configured with an invalid URL.
* (Minor) Exclude test package from dist & wheel.  Thanks @ameyajoshi99!
* (Minor) Allow users to specify log-level for when `is_enabled()` or `get_varients()` calls fail.

## v4.2.0
* (Minor) Support custom stickiness for FlexibleRollout strategy and variants.

## v4.1.0
* (Minor) Support project-based feature flag loading.

## v4.0.0
* (Major) Deprecate the `default_value` argument in the `is_enabled()` method.
* (Major) Drop Python 3.5 support.
* (Minor) Remove dependencies versions constraints.  Thanks @wbolster and @isra17!
* (Bugfix) Don't use mutable defaults.  Thanks @aviau!

## v3.6.2
* (Minor) Only send metrics to API if feature toggle is in-use (i.e. has been resolved to True/False).  Thanks @fwpheckel!
* (Minor) Remove dangling `variations` reference in favor of `variants` verbiage.

## v3.6.1
* (Major) Fix bug where loader didn't properly refresh variants. Thanks @simenaasland!

## v3.6.0
* (Minor) Add Python 3.9 support.
* (Minor) Only log errors generated when strategy loading fails once.
* (Minor) Errors submitting metrics will be logged as warnings and not exceptions.
* (Minor) Update apscheduler version to 3.7.0

## v3.5.1
* (Minor) Better error handling and typo fixes.  Thanks @vgerak!
* (Minor) Update requests version to 2.25.1.

## v3.5.0
* (Major) Stop using the `default_value` argument in the `is_enabled()` method (as it can cause counter-intuitive behavior) and add deprecation warning.  This argument will be removed in the next major version upgrade!
    * We recommend using the `fallback_function` argument instead.  If you need a blanket True in case of an exception, you can pass in a lambda like: `lambda x, y: True`.
* (Minor) Add better logging for API errors.
* (Minor) Update requests version to v2.25.0.


## v3.4.1, v3.4.2

**General**
* (Minor) Move CI to Github Actions, add auto-publishing.

## v3.4.0

**Bugfixes**
* (Major) Fallback function will only be called if exception (feature flag not found, general exception) occurs when calling `is_enabled()`.  It will not be called on successful execution of the method.

## v3.3.0

**General**
* (Major) Add support for variants on feature toggles.

**Bugfixes**
* (Minor) Fixed issue with applying custom constraints to non-standard parameters in context.

## v3.2.0

**General**

* (Major) Allow users to supply a fallback function to customize the default value of a feature flag.

## v3.1.1

**Bugfixes**

* Custom constraints check should check for values in the `properties` sub-property in the context as specified by [Unleash context documentation](https://unleash.github.io/docs/unleash_context).

## v3.1.0

**General**

* (Minor) Add official-ish support for Python 3.8.

## v3.0.0

**General**

* (Major) Support constraints on all default strategies.
    * This is a breaking change!  To update your custom strategy, please checkout the [custom strategy migration guide](https://unleash.github.io/unleash-client-python/customstrategies/).
* (Major) Added flexibleRollout strategy.

## v2.6.0

**General**

* (Minor) Add ability to add request kwargs when initializing the client.  These will be used when registering the client, fetching feature flags, and sending metrics.

## v2.5.0

**General**

* (Minor) Unleash client will not error if cache is not present and Unleash server not accessible during initialization.

## v2.4.0

**General**

* (Minor) Added static context values (app name, env) in preparation for Unleash v4 features.

## v2.3.0

**General**

* (Minor) Add option to disable metrics on client initialization.

**Bugfix**

* (Minor) Fixed issue where `disable_metrics` arugment wasn't honored.

## v2.2.1

**Bugfixes**

* (Major) Date/time sent to Unleash (in register, metrics, etc) is correctly in UTC w/timestamp format.

## v2.2.0

* Allow configuration of the cache directory.

## v2.1.0

**General**

* (Major) Support for Python 3.5, 3.6, and 3.7.  (Credit to [Baaym](https://github.com/baaym) for 3.5 support!)

## v2.0.1

**Bugfixes**

* (Major) Fix issue where `bucket.start` value sent to Unleash was never updated. Credit to Calle for bug report/proposed solution! =)

## v2.0.0

**Bugfixes**

* (Major) Removed hard-coded `/api/` in Unleash server URLs. Before upgrading, please adjust your server URL accordingly (i.e. changing http://unleash.heroku.com to http://unleash.heroku.com/api).

## v1.0.2

**General**

* unleash-client-python has moved under the general Unleash project!

**Bugfixes**

* (Minor) Updated requests version to address security issue in dependency.

## v1.0.0
**General**

* Implemented custom strategies.

## v0.3.0

**General**

* Implemented [client specification](https://github.com/Unleash/client-specification) tests.
* Cache changed to use Instance ID as key.

**Bugfixes**

* (Major) Fixed interposed arguments in normalized_hash() (aka MurmerHash3 wrapper).  Python client will now do the same thing as the other clients!
* (Major) Fixed issues with logic in random strategies.

## v0.2.0

**General**

* Changed cache implementation.  Instead of caching {feature toggle name: provisioning} we'll now cache the entire API response (and use it if the fetch fails in any way).

## v0.1.1

**General**

* Fixed Github link on pypi.
* Removed unused sphinx documentation.
* Added documentation using mkdocs

## v0.1.0

**General**

* First implementation of the Unleash Python client!  Woo!
