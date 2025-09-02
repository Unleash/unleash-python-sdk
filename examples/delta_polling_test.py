#!/usr/bin/env python3
"""
Test script for delta-polling functionality in Unleash Python SDK.
This is based on the streaming example but uses delta-polling mode instead.
"""
import os
import time
import json
import requests
from typing import Dict, Any

from UnleashClient import UnleashClient
from UnleashClient.events import UnleashEventType

# Configuration
# URL = "http://localhost:3063/api"
URL = "https://sandbox.getunleash.io/enterprise/api"
TOKEN = "hammer-1:development.4819f784fbe351f8a74982d43a68f53dcdbf74cdde554a5d0a81d997"
FLAG = "flag-page-hh"

headers = {"Authorization": TOKEN}

# Track events for testing
events_received = []
ready = False


def event_callback(event):
    """Callback to track events during delta-polling"""
    global ready, events_received
    events_received.append({"type": event.event_type.value, "timestamp": time.time()})

    print(f"Event received: {event.event_type.value}")

    if event.event_type == UnleashEventType.READY:
        ready = True
        print("✓ Client is ready after hydration")
    elif event.event_type == UnleashEventType.FETCHED:
        print("✓ Delta fetched successfully")


def test_direct_delta_api():
    """Test the delta API endpoint directly"""
    print("\n=== Testing Direct Delta API ===")

    delta_url = f"{URL}/client/delta"

    try:
        # First request (should get hydration event)
        print("Making initial delta request...")
        response = requests.get(delta_url, headers=headers, timeout=10)

        if response.status_code == 200:
            delta_data = response.json()
            etag = response.headers.get("etag", "")
            print(f"✓ Initial delta request successful")
            print(f"  Status: {response.status_code}")
            print(f"  ETag: {etag}")
            print(f"  Events count: {len(delta_data.get('events', []))}")

            # Check if we got hydration event
            events = delta_data.get("events", [])
            if events and any(event.get("type") == "hydration" for event in events):
                print("✓ Received hydration event")
            else:
                print("⚠ No hydration event found")

            # Second request with ETag (should get 304 Not Modified)
            if etag:
                print(f"\nMaking second request with ETag: {etag}")
                headers_with_etag = {**headers, "If-None-Match": etag}
                response2 = requests.get(
                    delta_url, headers=headers_with_etag, timeout=10
                )

                if response2.status_code == 304:
                    print("✓ Got 304 Not Modified as expected")
                else:
                    print(f"⚠ Expected 304, got {response2.status_code}")

        else:
            print(f"✗ Delta API request failed: {response.status_code}")
            print(f"  Response: {response.text}")

    except Exception as e:
        print(f"✗ Error testing delta API: {e}")


def test_delta_polling_client():
    """Test delta-polling using UnleashClient"""
    print("\n=== Testing Delta-Polling Client ===")

    # Create client with delta-polling experimental mode
    client = UnleashClient(
        url=URL,
        app_name="python-delta-polling-test",
        instance_id="test-instance",
        custom_headers=headers,
        experimental_mode={
            "type": "polling",  # Use polling mode
            "format": "delta",  # But with delta format
        },
        event_callback=event_callback,
        refresh_interval=2,  # 2 second intervals for testing
    )

    try:
        print("Initializing delta-polling client...")
        client.initialize_client()

        print("Waiting for hydration...")
        start_time = time.time()
        timeout = 30  # 30 second timeout

        # Wait for client to be ready
        while not client.is_initialized and (time.time() - start_time) < timeout:
            print("Client not initialized yet, waiting...")
            time.sleep(0.5)

        if not client.is_initialized:
            print("✗ Client failed to initialize within timeout")
            return

        print("✓ Client initialized successfully")

        # Wait for ready event
        while not ready and (time.time() - start_time) < timeout:
            print("Waiting for READY event...")
            time.sleep(0.5)

        if not ready:
            print("✗ Client failed to receive READY event within timeout")
            return

        print("✓ Client is ready")

        # Test feature flag evaluation
        print(f"\n=== Testing Feature Flag: {FLAG} ===")

        test_cycles = 5
        for i in range(test_cycles):
            enabled = client.is_enabled(FLAG, {"userId": f"test-user-{i}"})
            print(f"Cycle {i+1}: {FLAG} enabled? {enabled}")
            time.sleep(3)  # Wait 3 seconds between checks

        # Print event summary
        print(f"\n=== Event Summary ===")
        print(f"Total events received: {len(events_received)}")

        event_counts = {}
        for event in events_received:
            event_type = event["type"]
            event_counts[event_type] = event_counts.get(event_type, 0) + 1

        for event_type, count in event_counts.items():
            print(f"  {event_type}: {count}")

        # Test cache inspection
        print(f"\n=== Cache Inspection ===")
        features = client.feature_definitions()
        print(f"Features in cache: {len(features)}")

        if FLAG in features:
            feature_def = features[FLAG]
            print(f"✓ Found {FLAG} in cache")
            print(f"  Type: {feature_def.get('type', 'unknown')}")
            print(f"  Project: {feature_def.get('project', 'unknown')}")
        else:
            print(f"⚠ {FLAG} not found in cache")

    except Exception as e:
        print(f"✗ Error during delta-polling test: {e}")
        import traceback

        traceback.print_exc()

    finally:
        print("\nShutting down client...")
        client.destroy()


def test_cache_behavior():
    """Test cache behavior and ETag handling"""
    print("\n=== Testing Cache Behavior ===")

    # Create a client and check cache after initialization
    client = UnleashClient(
        url=URL,
        app_name="python-cache-test",
        instance_id="cache-test-instance",
        custom_headers=headers,
        experimental_mode={"type": "polling", "format": "delta"},
        event_callback=event_callback,
        refresh_interval=5,
    )

    try:
        client.initialize_client()

        # Wait for initialization
        start_time = time.time()
        while not client.is_initialized and (time.time() - start_time) < 15:
            time.sleep(0.5)

        if client.is_initialized:
            print("✓ Client initialized")

            # Check if ETag is stored in cache
            etag = client.cache.get("ETAG")
            if etag:
                print(f"✓ ETag found in cache: {etag}")
            else:
                print("⚠ No ETag found in cache")

            # Check features
            features = client.feature_definitions()
            print(f"✓ Features loaded: {len(features)}")

        else:
            print("✗ Client failed to initialize")

    except Exception as e:
        print(f"✗ Error testing cache behavior: {e}")
    finally:
        client.destroy()


def main():
    """Run all delta-polling tests"""
    print("🚀 Starting Delta-Polling Tests")
    print("=" * 50)

    # Test 1: Direct API call
    test_direct_delta_api()

    # Test 2: Delta-polling client
    test_delta_polling_client()

    # Test 3: Cache behavior
    test_cache_behavior()

    print("\n" + "=" * 50)
    print("✅ Delta-Polling Tests Complete")


if __name__ == "__main__":
    main()
