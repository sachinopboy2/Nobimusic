"""Unit tests for the API endpoint registry + health system."""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.utils.api_registry import Endpoint, EndpointRegistry

passed = 0


def check(label, condition):
    global passed
    tag = "PASS" if condition else "FAIL"
    print(f"{tag}  {label}")
    if not condition:
        raise AssertionError(label)
    passed += 1


with tempfile.NamedTemporaryFile(suffix=".enc", delete=False) as f:
    tmpfile = f.name

try:
    reg = EndpointRegistry(filepath=tmpfile, secret="test-secret-123")

    # Add endpoints
    ep1 = reg.add_endpoint("https://api1.example.com", api_key="key1", provider="primary", priority=10)
    ep2 = reg.add_endpoint("https://api2.example.com", api_key="key2", provider="backup", priority=50)
    check("add 2 endpoints", len(reg.endpoints) == 2)

    # Active is highest priority (lowest number)
    check("active is priority 10", reg.active.url == "https://api1.example.com")

    # Record success
    reg.record_success("https://api1.example.com")
    check("success recorded", reg.endpoints[0].last_success > 0)
    check("success total_requests", reg.endpoints[0].total_requests == 1)

    # Record failures up to threshold
    for i in range(5):
        reg.record_failure("https://api1.example.com")
    check("ep1 unhealthy after 5 fails", not reg.endpoints[0].healthy)
    check("ep1 has cooldown", reg.endpoints[0].cooldown_until > time.time())
    check("ep1 fail_count=5", reg.endpoints[0].fail_count == 5)

    # Failover to ep2
    check("active failover to ep2", reg.active.url == "https://api2.example.com")

    # Restore ep1
    reg.restore_endpoint("https://api1.example.com")
    check("ep1 restored healthy", reg.endpoints[0].healthy)
    check("ep1 fail_count reset", reg.endpoints[0].fail_count == 0)
    check("active back to ep1", reg.active.url == "https://api1.example.com")

    # Persist and reload
    reg.save()
    reg2 = EndpointRegistry(filepath=tmpfile, secret="test-secret-123")
    reg2.load()
    check("reload preserves count", len(reg2.endpoints) == 2)
    check("reload preserves url", reg2.endpoints[0].url == "https://api1.example.com")
    check("reload preserves key", reg2.endpoints[0].api_key == "key1")

    # Wrong secret can't decrypt
    reg3 = EndpointRegistry(filepath=tmpfile, secret="wrong-secret")
    loaded = reg3.load()
    check("wrong secret fails to load", not loaded)

    # Remove endpoint
    removed = reg.remove_endpoint("https://api2.example.com")
    check("remove returns True", removed)
    check("1 endpoint left", len(reg.endpoints) == 1)

    # Dedup on add
    reg.add_endpoint("https://api1.example.com", api_key="new-key", provider="updated")
    check("dedup updates existing", len(reg.endpoints) == 1)
    check("dedup updates key", reg.endpoints[0].api_key == "new-key")

    # All endpoints down
    for i in range(5):
        reg.record_failure("https://api1.example.com")
    reg.endpoints[0].cooldown_until = time.time() + 9999
    check("all down returns None", reg.active is None)

    # Recovery log
    check("recovery log has entries", len(reg.recovery_log) > 0)

finally:
    os.unlink(tmpfile)

print(f"\n{passed}/{passed} passed")
