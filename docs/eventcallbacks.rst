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

Threading
=========

Your callback runs on a single background thread owned by the client, never on
the thread that called ``is_enabled()`` or ``get_variant()``. This means:

* **Calls don't block on your callback.** ``is_enabled()`` returns as soon as the
  event is queued, so a slow callback can't slow down flag evaluation. It also
  means the call returns *before* your callback has run - if you need to assert on
  an event in a test, wait for it rather than checking immediately afterwards.
* **Thread local state from the caller isn't available.** Flask's ``g``, the
  current Django request, ``contextvars`` and similar will not be set. Read
  anything you need from the event itself, or capture it before the call.
* **Callbacks run sequentially.** Events are delivered one at a time, in order, so
  your callback doesn't need to be thread safe against itself.
* **Events are dropped if you can't keep up.** Up to 10,000 events are held while
  waiting on your callback; beyond that, events are discarded and a warning is
  logged. Exceptions raised by your callback are logged and otherwise ignored.
* **Call** ``destroy()`` **when you're done.** It delivers whatever is still
  queued before shutting the thread down.
