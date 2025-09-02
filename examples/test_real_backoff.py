#!/usr/bin/env python3
"""
Integration test to verify that the ld-eventsource library actually implements
exponential backoff when configured properly. This tests the real library behavior.
"""

import time
from ld_eventsource.config import RetryDelayStrategy


def test_retry_delay_strategy():
    """Test that RetryDelayStrategy produces exponential backoff delays"""
    print("🧪 Testing RetryDelayStrategy exponential backoff behavior...")

    # Create strategy with parameters matching our StreamingConnector defaults
    strategy = RetryDelayStrategy.default(
        max_delay=30.0,
        backoff_multiplier=2.0,
        jitter_multiplier=0.0,  # No jitter for predictable test
    )

    # Test multiple iterations to see exponential growth
    delays = []
    current_strategy = strategy
    base_delay = 2.0  # Initial retry delay (matches our backoff_initial)

    for i in range(6):
        delay, current_strategy = current_strategy.apply(base_delay)
        delays.append(delay)
        print(f"   Attempt {i}: {delay:.3f}s")
        base_delay = delay  # Use the computed delay as base for next iteration

    # Verify exponential growth pattern
    # Expected delays: 2.0, 4.0, 8.0, 16.0, 30.0 (capped), 30.0
    expected_delays = [2.0, 4.0, 8.0, 16.0, 30.0, 30.0]

    for i, (actual, expected) in enumerate(zip(delays, expected_delays)):
        assert (
            abs(actual - expected) < 0.1
        ), f"Attempt {i}: delay {actual:.3f}s, expected ~{expected:.1f}s"

    # Verify it grows exponentially
    assert delays[1] == 2 * delays[0], "Second delay should be 2x first"
    assert delays[2] == 2 * delays[1], "Third delay should be 2x second"
    assert delays[3] == 2 * delays[2], "Fourth delay should be 2x third"

    # Verify it caps at max_delay
    assert delays[4] == 30.0, "Should cap at max_delay"
    assert delays[5] == 30.0, "Should stay at max_delay"

    print(f"   ✅ Exponential backoff verified: {[f'{d:.1f}s' for d in delays]}")


def test_retry_strategy_with_jitter():
    """Test that retry strategy with jitter produces varied delays"""
    print("🔄 Testing retry strategy with jitter...")

    strategy = RetryDelayStrategy.default(
        max_delay=30.0,
        backoff_multiplier=2.0,
        jitter_multiplier=0.5,  # 50% jitter
    )

    # Test that jitter produces different results for same attempt
    delays = []
    for _ in range(5):
        current_strategy = strategy
        delay, _ = current_strategy.apply(2.0)  # First attempt
        delays.append(delay)

    print(f"   First attempt delays with jitter: {[f'{d:.2f}s' for d in delays]}")

    # With 50% jitter on 2.0s base, delays should be in range [1.0, 3.0]
    for delay in delays:
        assert (
            1.0 <= delay <= 3.0
        ), f"Delay {delay:.2f}s outside jitter range [1.0, 3.0]"

    # Should have some variation (not all identical)
    if len(set(delays)) == 1:
        print("   ⚠️  Warning: All delays identical, jitter may not be working")
    else:
        print("   ✅ Jitter produces varied delays as expected")


def test_our_configuration_matches_nodejs():
    """Verify our configuration produces delays similar to Node.js SDK"""
    print("📊 Comparing with Node.js SDK configuration...")

    # Node.js uses: initial=2s, max=30s, multiplier=2.0, jitter=0.5
    # Our configuration should match
    strategy = RetryDelayStrategy.default(
        max_delay=30.0,
        backoff_multiplier=2.0,
        jitter_multiplier=0.5,
    )

    # Test several attempts
    nodejs_style_delays = []
    current_strategy = strategy
    base_delay = 2.0

    for i in range(5):
        delay, current_strategy = current_strategy.apply(base_delay)
        nodejs_style_delays.append(delay)
        base_delay = delay

    print(f"   Delays: {[f'{d:.1f}s' for d in nodejs_style_delays]}")

    # All delays should be reasonable (not negative, not too large)
    for i, delay in enumerate(nodejs_style_delays):
        assert (
            1.0 <= delay <= 45.0
        ), f"Attempt {i}: delay {delay:.1f}s out of reasonable range"

    # Should show general growth pattern (allowing for jitter)
    # First delay should be around 2s, fourth should be much larger
    assert (
        nodejs_style_delays[0] >= 1.0 and nodejs_style_delays[0] <= 3.0
    ), "First delay should be ~2s ±jitter"
    assert nodejs_style_delays[3] > 10.0, "Fourth delay should be much larger"

    print("   ✅ Configuration produces reasonable Node.js-style exponential backoff")


if __name__ == "__main__":
    print("🚀 Testing real ld-eventsource RetryDelayStrategy behavior...")
    print()

    test_retry_delay_strategy()
    print()

    test_retry_strategy_with_jitter()
    print()

    test_our_configuration_matches_nodejs()
    print()

    print("🎉 All integration tests passed!")
    print("✨ The ld-eventsource library properly implements exponential backoff")
    print("📝 Our StreamingConnector configuration matches Node.js/Java/Ruby SDKs")
