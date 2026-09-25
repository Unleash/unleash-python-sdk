"""
Errors raised by the Unleash client.

The errors form a three-layer hierarchy, so callers can choose how broadly to
catch:

1. :class:`UnleashClientError` is the base of every error this SDK raises.
   Catching it handles all of them without catching :class:`Exception`.
2. Each module has one ``<ModuleName>Error``, such as
   :class:`InstanceRegistryError`, that groups the errors coming from that
   module.
3. Specific errors, such as :class:`MultipleInstancesNotAllowedError`, derive
   from their module's error and carry a message that tells the user what went
   wrong and what to do about it.

Example::

    from UnleashClient import UnleashClient
    from UnleashClient.errors import (
        InstanceRegistryError,
        MultipleInstancesNotAllowedError,
        UnleashClientError,
    )
    from UnleashClient.utils import InstanceAllowType

    try:
        client = UnleashClient(
            url="https://unleash.example.com/api",
            app_name="my-app",
            multiple_instance_mode=InstanceAllowType.BLOCK,
        )
    except MultipleInstancesNotAllowedError:
        ...  # this specific error
    except InstanceRegistryError:
        ...  # any other error from the instance registry
    except UnleashClientError:
        ...  # any other error from this SDK
"""


class UnleashClientError(Exception):
    """
    Base class for every error raised by the Unleash client.

    Example::

        try:
            client.initialize_client()
        except UnleashClientError as error:
            LOGGER.error("Unleash client failed: %s", error)
    """


class InstanceRegistryError(UnleashClientError):
    """
    Base class for errors raised while registering a client instance.

    Example::

        try:
            client = UnleashClient(url=url, app_name=app_name)
        except InstanceRegistryError as error:
            LOGGER.error("Could not register the Unleash client: %s", error)
    """


class MultipleInstancesNotAllowedError(InstanceRegistryError):
    """
    Raised when a client is built with a configuration that another live client
    already uses, and ``multiple_instance_mode`` is
    :attr:`~UnleashClient.utils.InstanceAllowType.BLOCK`.

    Example::

        first = UnleashClient(
            url=url, app_name=app_name, multiple_instance_mode=InstanceAllowType.BLOCK
        )

        try:
            second = UnleashClient(
                url=url,
                app_name=app_name,
                multiple_instance_mode=InstanceAllowType.BLOCK,
            )
        except MultipleInstancesNotAllowedError:
            second = first
    """
