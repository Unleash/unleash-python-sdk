****************************************
Event Callbacks
****************************************

The Unleash Python client support event callbacks!

1. Create a function with the type `Callable[[UnleashEvent]]` and pass it to the Unleash client at initialization.
2. Enable `impression data <https://docs.getunleash.io/reference/impression-data#enabling-impression-data>`_ on feature flag configuration.

Example code using `blinker <https://github.com/pallets-eco/blinker>`_:

.. code-block:: python

    from blinker import signal
    from UnleashClient import UnleashClient
    from UnleashClient.events import UnleashEvent

    send_data = signal('send-data')

    @send_data.connect
    def receive_data(sender, **kw):
        print("Caught signal from %r, data %r" % (sender, kw))
        return kw

    def example_callback(event: UnleashEvent):
        send_data.send('anonymous', data=event)

    # Set up Unleash
    client = UnleashClient(
        "https://unleash.herokuapp.com/api",
        "My Program"
        event_callback=example_callback
    )
    client.initialize_client()
    client.is_enabled("testFlag")
