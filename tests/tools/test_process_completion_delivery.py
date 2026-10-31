"""Process event snapshots share claims without confusing retries or profile generations."""
from tools import process_completion_delivery as delivery
from tools.process_registry import ProcessRegistry


def test_snapshot_identity_and_stale_tokens_cannot_settle_a_retry():
    registry = ProcessRegistry()
    event = {"type": "completion", "profile_home": "profile-a", "session_id": "proc_one", "started_at": 123}
    snapshot = dict(event)
    first = delivery.claim(registry, event, "tool-boundary")
    assert first is not None
    assert delivery.claim(registry, snapshot, "fallback") is None
    assert not delivery.release(registry, event, "wrong-token")
    assert delivery.release(registry, event, first)
    second = delivery.claim(registry, snapshot, "fallback")
    assert second is not None and second != first
    assert not delivery.acknowledge(registry, event, first)
    assert not delivery.release(registry, event, first)
    assert delivery.acknowledge(registry, snapshot, second)
    assert delivery.delivered(registry, event)
    assert delivery.claim(registry, event, "stale-poller-snapshot") is None


def test_profile_and_process_generation_are_part_of_delivery_identity():
    registry = ProcessRegistry()
    events = [{"type": "completion", "profile_home": home, "session_id": "proc_one", "started_at": started}
              for home, started in [("profile-a", 123), ("profile-b", 123), ("profile-a", 124)]]
    for event in events:
        claim = delivery.claim(registry, event, "tool-boundary")
        assert claim is not None
        assert not delivery.delivered(registry, event)
        assert delivery.acknowledge(registry, event, claim)
    assert all(delivery.delivered(registry, event) for event in events)
