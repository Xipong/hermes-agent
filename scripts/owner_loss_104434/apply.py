"""Apply the owner-loss/stale-latch fix to the exact PR #104434 head."""
from __future__ import annotations

from pathlib import Path
import re
import sys

ROOT = Path(sys.argv[1])


def read(path: str) -> str:
    return (ROOT / path).read_text()


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    assert count == 1, f"{label}: expected one match, found {count}"
    return text.replace(old, new, 1)


def replace_function(text: str, name: str, next_name: str, new: str) -> str:
    pattern = rf"def {re.escape(name)}\(.*?(?=\ndef {re.escape(next_name)}\()"
    updated, count = re.subn(pattern, new.rstrip() + "\n\n", text, count=1, flags=re.S)
    assert count == 1, f"function {name}: expected one match, found {count}"
    return updated


# ---------------------------------------------------------------------------
# agent/delegation_inject.py
# ---------------------------------------------------------------------------
path = "agent/delegation_inject.py"
s = read(path)
s = replace_once(
    s,
    '_CLAIM_HEARTBEAT_INTERVAL_SECONDS = 60.0\n',
    '_CLAIM_HEARTBEAT_INTERVAL_SECONDS = 60.0\n'
    '_CLAIM_ABANDONED_KEY = "_delegation_local_claim_abandoned"\n',
    "claim marker",
)

helpers = '''def _entry_is_renewable(agent: Any, entry: dict[str, Any]) -> bool:
    """Whether this RAM claim may still be renewed for the active parent turn.

    A claim is useful only to the turn that created its carrier. Once a cached
    agent advances, retaining or renewing the old local latch can only delay the
    durable fallback and must never block a new carrier.
    """
    if entry.get(_CLAIM_ABANDONED_KEY):
        return False
    active_turn_id = str(getattr(agent, "_active_turn_id", "") or "")
    entry_turn_id = str(entry.get("turn_id") or "")
    if active_turn_id and entry_turn_id and entry_turn_id != active_turn_id:
        entry[_CLAIM_ABANDONED_KEY] = True
        return False
    return True


def _claim_status(entry: dict[str, Any]) -> tuple[str | None, bool]:
    """Return durable state and whether this exact local token still owns it."""
    from tools.async_delegation import get_event_delivery_claim_status

    return get_event_delivery_claim_status(entry["event"], entry["claim_id"])


'''
s = replace_once(
    s,
    'def _stop_claim_heartbeat_if_idle(agent: Any) -> None:\n',
    helpers + 'def _stop_claim_heartbeat_if_idle(agent: Any) -> None:\n',
    "claim helpers",
)
s = replace_once(
    s,
    '''def _stop_claim_heartbeat_if_idle(agent: Any) -> None:
    if getattr(agent, _PENDING_CLAIMS_ATTR, None):
        return
''',
    '''def _stop_claim_heartbeat_if_idle(agent: Any) -> None:
    pending = list(getattr(agent, _PENDING_CLAIMS_ATTR, []) or [])
    if any(_entry_is_renewable(agent, entry) for entry in pending):
        return
''',
    "heartbeat idle predicate",
)

ensure_fn = '''def ensure_pending_inject_heartbeat(agent: Any) -> bool:
    """Renew live same-turn claims throughout provider retries and backoff."""

    pending = list(getattr(agent, _PENDING_CLAIMS_ATTR, []) or [])
    if not any(_entry_is_renewable(agent, entry) for entry in pending):
        _stop_claim_heartbeat_if_idle(agent)
        return False
    existing = getattr(agent, _CLAIM_HEARTBEAT_ATTR, None)
    if isinstance(existing, dict):
        thread = existing.get("thread")
        existing_stop = existing.get("stop")
        if (
            isinstance(thread, threading.Thread)
            and thread.is_alive()
            and isinstance(existing_stop, threading.Event)
            and not existing_stop.is_set()
        ):
            return True

    stop = threading.Event()

    def _heartbeat() -> None:
        from tools.async_delegation import renew_event_delivery

        try:
            while not stop.wait(_CLAIM_HEARTBEAT_INTERVAL_SECONDS):
                pending = list(getattr(agent, _PENDING_CLAIMS_ATTR, []) or [])
                renewable = [
                    entry for entry in pending if _entry_is_renewable(agent, entry)
                ]
                if not renewable:
                    break
                for entry in renewable:
                    try:
                        renewed = renew_event_delivery(
                            entry["event"], entry["claim_id"]
                        )
                    except Exception:
                        logger.warning(
                            "Failed to renew same-turn delegation claim %s",
                            entry.get("event_id"),
                            exc_info=True,
                        )
                        continue
                    if renewed:
                        continue
                    # A False UPDATE is authoritative: the row is terminal/missing
                    # or another token owns it. Stop presenting this RAM entry as
                    # live. Cleanup restores an uncommitted carrier without touching
                    # the row now owned by another consumer.
                    entry[_CLAIM_ABANDONED_KEY] = True
                    logger.warning(
                        "Lost ownership of same-turn delegation claim %s; "
                        "retiring its local latch",
                        entry.get("event_id"),
                    )
                if not any(_entry_is_renewable(agent, entry) for entry in pending):
                    break
        finally:
            stop.set()

    from tools.thread_context import propagate_context_to_thread

    thread = threading.Thread(
        target=propagate_context_to_thread(_heartbeat),
        daemon=True,
        name="delegation-inject-claim-heartbeat",
    )
    setattr(agent, _CLAIM_HEARTBEAT_ATTR, {"stop": stop, "thread": thread})
    thread.start()
    return True
'''
s = replace_function(
    s,
    "ensure_pending_inject_heartbeat",
    "acknowledge_pending_injects",
    ensure_fn,
)

ack_fn = '''def acknowledge_pending_injects(agent: Any, *, turn_id: str | None = None) -> int:
    """Acknowledge tool-boundary claims after durable transcript persistence."""

    from tools.async_delegation import complete_event_delivery

    pending = list(getattr(agent, _PENDING_CLAIMS_ATTR, []) or [])
    keep: list[dict[str, Any]] = []
    settled_messages: list[dict[str, Any]] = []
    acknowledged = 0
    for entry in pending:
        if turn_id is not None and str(entry.get("turn_id") or "") != str(turn_id):
            keep.append(entry)
            continue
        message = entry.get("message")
        # A successful no-op flush (persistence-disabled agents) is NOT a receipt.
        if not isinstance(message, dict) or message.get("_db_persisted") is not True:
            keep.append(entry)
            continue
        try:
            committed = complete_event_delivery(entry["event"], entry["claim_id"])
        except Exception:
            logger.warning("Could not acknowledge persisted delegation carrier", exc_info=True)
            committed = False
        if committed:
            acknowledged += 1
            settled_messages.append(message)
            continue
        try:
            state, still_owned = _claim_status(entry)
        except Exception:
            keep.append(entry)
            logger.warning(
                "Could not classify failed delegation acknowledgement %s; "
                "retaining local claim for retry",
                entry.get("event_id"),
                exc_info=True,
            )
            continue
        if still_owned:
            keep.append(entry)
            logger.warning(
                "Delegation carrier persisted but durable event ack did not commit: %s",
                entry.get("event_id"),
            )
            continue
        entry[_CLAIM_ABANDONED_KEY] = True
        settled_messages.append(message)
        logger.warning(
            "Retired stale local delegation claim %s after failed acknowledgement "
            "(durable state=%s)",
            entry.get("event_id"),
            state,
        )
    setattr(agent, _PENDING_CLAIMS_ATTR, keep)
    still_pending_ids = {str(entry.get("event_id") or "") for entry in keep}
    for message in settled_messages:
        if not (_message_event_ids(message) & still_pending_ids):
            _clear_carrier_metadata(message)
    _stop_claim_heartbeat_if_idle(agent)
    return acknowledged
'''
s = replace_function(
    s,
    "acknowledge_pending_injects",
    "release_pending_injects",
    ack_fn,
)

release_fn = '''def release_pending_injects(
    agent: Any,
    messages: list[dict[str, Any]],
    *,
    turn_id: str | None = None,
) -> int:
    """Roll back unconsumed RAM injects, preserving already-durable copies."""

    from tools.async_delegation import (
        complete_event_delivery,
        get_event_delivery_state,
        release_event_delivery,
    )
    from tools.process_registry import process_registry

    pending = list(getattr(agent, _PENDING_CLAIMS_ATTR, []) or [])
    keep: list[dict[str, Any]] = []
    removable_event_ids: set[str] = set()
    settled_messages: list[dict[str, Any]] = []
    settled = 0
    for entry in pending:
        if turn_id is not None and str(entry.get("turn_id") or "") != str(turn_id):
            keep.append(entry)
            continue
        event = entry["event"]
        event_id = str(entry["event_id"])
        if _durable_event_is_in_history(messages, event_id):
            if complete_event_delivery(event, entry["claim_id"]):
                settled += 1
                message = entry.get("message")
                if isinstance(message, dict):
                    settled_messages.append(message)
                continue
            try:
                state, still_owned = _claim_status(entry)
            except Exception:
                keep.append(entry)
                logger.warning(
                    "Could not classify failed durable carrier settlement %s; "
                    "retaining local claim for retry",
                    event_id,
                    exc_info=True,
                )
                continue
            if still_owned:
                keep.append(entry)
                continue
            entry[_CLAIM_ABANDONED_KEY] = True
            settled += 1
            message = entry.get("message")
            if isinstance(message, dict):
                settled_messages.append(message)
            logger.warning(
                "Retired stale local delegation claim %s while preserving its "
                "durable carrier (state=%s)",
                event_id,
                state,
            )
            continue

        # Remove the unconsumed marker by durable identity even when compression
        # replaced the Python dict object.
        removable_event_ids.add(event_id)
        committed = release_event_delivery(event, entry["claim_id"])
        state = get_event_delivery_state(event)
        if committed:
            # At the attempt cap release transitions to dropped, not pending.
            if state == "pending":
                with process_registry.completion_routing_lock:
                    process_registry.completion_queue.put(event)
            settled += 1
            continue
        if state == "delivered":
            settled += 1
            continue
        try:
            state, still_owned = _claim_status(entry)
        except Exception:
            keep.append(entry)
            logger.warning(
                "Could not classify failed delegation release %s; "
                "retaining local claim for retry",
                event_id,
                exc_info=True,
            )
            continue
        if still_owned:
            keep.append(entry)
            continue
        entry[_CLAIM_ABANDONED_KEY] = True
        settled += 1
        logger.warning(
            "Retired stale local delegation claim %s after ownership moved "
            "elsewhere (durable state=%s)",
            event_id,
            state,
        )

    if removable_event_ids:
        retained: list[dict[str, Any]] = []
        for message in messages:
            if not (_message_event_ids(message) & removable_event_ids):
                retained.append(message)
                continue
            if "_delegation_delivery_original_content" in message:
                message["content"] = deepcopy(
                    message["_delegation_delivery_original_content"]
                )
                _remove_carrier_identity(message)
            retained.append(message)
        messages[:] = retained
        agent._session_messages = messages
    still_pending_ids = {str(entry.get("event_id") or "") for entry in keep}
    for message in settled_messages:
        if not (_message_event_ids(message) & still_pending_ids):
            _clear_carrier_metadata(message)
    setattr(agent, _PENDING_CLAIMS_ATTR, keep)
    _stop_claim_heartbeat_if_idle(agent)
    return settled
'''
s = replace_function(
    s,
    "release_pending_injects",
    "_normal_budget_available",
    release_fn,
)

s = replace_once(
    s,
    '''    if not _normal_budget_available(agent):
        return 0
    if getattr(agent, _PENDING_CLAIMS_ATTR, None):
        return 0
''',
    '''    if not _normal_budget_available(agent):
        return 0

    # The single-flight latch is scoped to the carrier's originating turn. A
    # cached agent may retain an older entry after an uncertain DB failure, but
    # that obsolete local bookkeeping must never disable injection forever.
    pending = list(getattr(agent, _PENDING_CLAIMS_ATTR, []) or [])
    for entry in pending:
        _entry_is_renewable(agent, entry)  # marks prior-turn entries abandoned
    _stop_claim_heartbeat_if_idle(agent)
    if any(
        str(entry.get("turn_id") or "") in {"", active_turn_id}
        for entry in pending
    ):
        return 0
''',
    "turn-scoped latch",
)
write(path, s)


# ---------------------------------------------------------------------------
# tools/async_delegation.py
# ---------------------------------------------------------------------------
path = "tools/async_delegation.py"
s = read(path)
claim_status_fn = '''def get_event_delivery_claim_status(
    evt: Dict[str, Any], claim_id: str,
) -> tuple[Optional[str], bool]:
    """Return durable state and ownership of one exact delivery token.

    Callers use the pair after a failed UPDATE to distinguish a transient/local
    failure (the token still owns a pending row) from definitive owner loss. A
    stale RAM claimant must not release or requeue a row owned by another consumer.
    """
    if evt.get("type") != "async_delegation":
        return None, False
    delegation_id = str(evt.get("delegation_id") or "")
    if not delegation_id:
        return None, False
    with _DB_LOCK, _transaction() as conn:
        row = conn.execute(
            "SELECT delivery_state, delivery_claim FROM async_delegations "
            "WHERE delegation_id=?",
            (delegation_id,),
        ).fetchone()
    if row is None:
        return None, False
    return row[0], bool(
        claim_id
        and row[0] == "pending"
        and row[1] == claim_id
    )


'''
s = replace_once(
    s,
    'def renew_event_delivery(evt: Dict[str, Any], claim_id: str) -> bool:\n',
    claim_status_fn + 'def renew_event_delivery(evt: Dict[str, Any], claim_id: str) -> bool:\n',
    "durable claim status API",
)
write(path, s)


# ---------------------------------------------------------------------------
# tests/agent/test_delegation_delivery.py
# ---------------------------------------------------------------------------
path = "tests/agent/test_delegation_delivery.py"
s = read(path)
claim_helper = '''def _take_over_event_claim(delegation_id: str, claim_id: str) -> None:
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
s = replace_once(
    s,
    'def _loop_response(*, content, finish_reason="stop", tool_calls=None):\n',
    claim_helper + 'def _loop_response(*, content, finish_reason="stop", tool_calls=None):\n',
    "takeover helper",
)

new_tests = '''def test_owner_loss_retires_local_latch_and_next_turn_can_inject(monkeypatch):
    """A foreign takeover cannot strand this cached parent after its old turn."""
    monkeypatch.setattr(
        inject, "_CLAIM_HEARTBEAT_INTERVAL_SECONDS", 0.01, raising=False
    )
    first_id = _record(turn_id="turn-old")
    assert _complete_unit(first_id, _child(0, "old carrier"))
    agent = _tool_boundary_agent()
    agent._active_turn_id = "turn-old"
    old_messages = [
        {"role": "tool", "tool_call_id": "old", "content": "old original"}
    ]
    agent._session_messages = old_messages

    assert attach_ready_injects_to_tool_results(
        agent, old_messages, num_tool_msgs=1, turn_id="turn-old"
    ) == 1
    old_entry = agent._pending_delegation_inject_claims[0]
    foreign_claim = "other-consumer:999:takeover"
    _take_over_event_claim(first_id, foreign_claim)

    deadline = time.monotonic() + 1
    while (
        not old_entry.get(inject._CLAIM_ABANDONED_KEY)
        and time.monotonic() < deadline
    ):
        time.sleep(0.005)
    assert old_entry.get(inject._CLAIM_ABANDONED_KEY) is True
    heartbeat = agent._delegation_inject_claim_heartbeat
    heartbeat["thread"].join(timeout=1)
    assert not heartbeat["thread"].is_alive()

    # Old-turn finalization restores the uncommitted result but neither releases
    # nor requeues the row now owned by the foreign consumer.
    assert release_pending_injects(agent, old_messages, turn_id="turn-old") == 1
    assert old_messages == [
        {"role": "tool", "tool_call_id": "old", "content": "old original"}
    ]
    assert not agent._pending_delegation_inject_claims
    assert process_registry.completion_queue.empty()
    assert _event_state(first_id) == ("pending", 2)
    assert ad.complete_completion_delivery(first_id, foreign_claim)

    # The same cached parent starts another turn. Its next result must not be
    # rejected by the dead latch from turn-old.
    agent._active_turn_id = "turn-next"
    second_id = _record(turn_id="turn-next")
    assert _complete_unit(second_id, _child(0, "new turn evidence"))
    new_messages = [
        {"role": "tool", "tool_call_id": "new", "content": "new original"}
    ]
    agent._session_messages = new_messages
    assert attach_ready_injects_to_tool_results(
        agent, new_messages, num_tool_msgs=1, turn_id="turn-next"
    ) == 1
    assert "new turn evidence" in new_messages[0]["content"]
    new_messages[0]["_db_persisted"] = True
    assert acknowledge_pending_injects(agent, turn_id="turn-next") == 1
    agent._delegation_inject_claim_heartbeat["thread"].join(timeout=1)


def test_failed_ack_after_owner_loss_prunes_stale_local_entry():
    """A persisted carrier does not retain a token now owned by another consumer."""
    delegation_id = _record(turn_id="turn-current")
    assert _complete_unit(delegation_id, _child(0, "persisted stale carrier"))
    agent = _tool_boundary_agent()
    messages = [
        {"role": "tool", "tool_call_id": "tc", "content": "original"}
    ]
    agent._session_messages = messages
    assert attach_ready_injects_to_tool_results(
        agent, messages, num_tool_msgs=1, turn_id="turn-current"
    ) == 1
    heartbeat = agent._delegation_inject_claim_heartbeat
    heartbeat["stop"].set()
    heartbeat["thread"].join(timeout=1)

    foreign_claim = "other-consumer:999:ack-takeover"
    _take_over_event_claim(delegation_id, foreign_claim)
    messages[0]["_db_persisted"] = True

    assert acknowledge_pending_injects(agent, turn_id="turn-current") == 0
    assert not agent._pending_delegation_inject_claims
    assert "persisted stale carrier" in messages[0]["content"]
    assert "_delegation_delivery_original_content" not in messages[0]
    assert "_delegation_event_ids" not in messages[0]
    assert _event_state(delegation_id) == ("pending", 2)
    assert ad.complete_completion_delivery(delegation_id, foreign_claim)


def test_uncertain_previous_turn_claim_does_not_block_current_turn(monkeypatch):
    """Even a conservatively retained old entry is not a process-lifetime latch."""
    first_id = _record(turn_id="turn-old")
    assert _complete_unit(first_id, _child(0, "old uncertain carrier"))
    agent = _tool_boundary_agent()
    agent._active_turn_id = "turn-old"
    old_messages = [
        {"role": "tool", "tool_call_id": "old", "content": "old original"}
    ]
    agent._session_messages = old_messages
    assert attach_ready_injects_to_tool_results(
        agent, old_messages, num_tool_msgs=1, turn_id="turn-old"
    ) == 1
    old_entry = agent._pending_delegation_inject_claims[0]
    heartbeat = agent._delegation_inject_claim_heartbeat
    heartbeat["stop"].set()
    heartbeat["thread"].join(timeout=1)

    # A transient release failure is uncertain: retain the exact token for retry.
    with monkeypatch.context() as scoped:
        scoped.setattr(ad, "release_event_delivery", lambda *_args: False)
        assert release_pending_injects(
            agent, old_messages, turn_id="turn-old"
        ) == 0
    assert agent._pending_delegation_inject_claims == [old_entry]

    agent._active_turn_id = "turn-next"
    second_id = _record(turn_id="turn-next")
    assert _complete_unit(second_id, _child(0, "current turn evidence"))
    new_messages = [
        {"role": "tool", "tool_call_id": "new", "content": "new original"}
    ]
    agent._session_messages = new_messages
    assert attach_ready_injects_to_tool_results(
        agent, new_messages, num_tool_msgs=1, turn_id="turn-next"
    ) == 1
    assert old_entry.get(inject._CLAIM_ABANDONED_KEY) is True
    assert "current turn evidence" in new_messages[0]["content"]
    assert len(agent._pending_delegation_inject_claims) == 2

    new_messages[0]["_db_persisted"] = True
    assert acknowledge_pending_injects(agent, turn_id="turn-next") == 1
    assert agent._pending_delegation_inject_claims == [old_entry]
    agent._delegation_inject_claim_heartbeat["thread"].join(timeout=1)

    # Settle the retained row and let ordinary cleanup remove its RAM entry.
    assert ad.complete_event_delivery(old_entry["event"], old_entry["claim_id"])
    assert release_pending_injects(agent, old_messages, turn_id="turn-old") == 1
    assert not agent._pending_delegation_inject_claims


'''
s = replace_once(
    s,
    'def test_run_conversation_inject_transport_normalize_and_ack(monkeypatch, tmp_path):\n',
    new_tests
    + 'def test_run_conversation_inject_transport_normalize_and_ack(monkeypatch, tmp_path):\n',
    "owner-loss regressions",
)
write(path, s)

print("Applied owner-loss latch fix and three regression tests.")
