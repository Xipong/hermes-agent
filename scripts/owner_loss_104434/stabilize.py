"""Make the generated owner-loss takeover fixture atomic and deterministic."""
from pathlib import Path
import sys

path = Path(sys.argv[1]) / "tests/agent/test_delegation_delivery.py"
text = path.read_text()
old = '''def _take_over_event_claim(delegation_id: str, claim_id: str) -> None:
    """Simulate another consumer winning an expired delivery lease."""
    with ad._DB_LOCK, ad._transaction() as conn:
        changed = conn.execute(
            "UPDATE async_delegations SET delivery_claimed_at=?, updated_at=? "
            "WHERE delegation_id=? AND delivery_state='pending'",
            (time.time() - 301, time.time(), delegation_id),
        ).rowcount
    assert changed == 1
    assert ad.claim_completion_delivery(delegation_id, claim_id)
'''
new = '''def _take_over_event_claim(delegation_id: str, claim_id: str) -> None:
    """Atomically simulate another consumer winning an expired delivery lease."""
    now = time.time()
    with ad._DB_LOCK, ad._transaction() as conn:
        changed = conn.execute(
            "UPDATE async_delegations SET delivery_claim=?, "
            "delivery_claimed_at=?, delivery_attempts=delivery_attempts+1, "
            "updated_at=? WHERE delegation_id=? AND delivery_state='pending'",
            (claim_id, now, now, delegation_id),
        ).rowcount
    assert changed == 1
'''
count = text.count(old)
assert count == 1, f"expected one takeover helper, found {count}"
path.write_text(text.replace(old, new, 1))
print("Made owner-loss takeover fixture atomic.")
