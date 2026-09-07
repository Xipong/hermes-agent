"""Review fault probes: real SQLite and production flush path."""
import sqlite3
from tests.agent.test_delegation_delivery import (
    _clean_async_state, _record, _complete_unit, _child, _make_loop_agent,
    _tool_boundary_agent, _event_state, _queue_contents,
)
from agent.tool_executor import _flush_session_db_after_tool_progress
from tools import async_delegation as ad


def _messages():
    return [
        {"role": "assistant", "tool_calls": [{"id": "tc", "type": "function",
          "function": {"name": "terminal", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "tc", "tool_name": "terminal", "content": "original"},
    ]


def test_lost_delivery_claim_cannot_commit_a_tool_carrier(tmp_path, monkeypatch):
    monkeypatch.setattr(ad, "_db_path", lambda: tmp_path / "state.db")
    agent = _make_loop_agent(tmp_path)
    agent._active_turn_id = "turn-current"
    unit = _record(parent_session_id=agent.session_id)
    assert _complete_unit(unit, _child(0, "EXCLUSIVE_EVIDENCE"))
    original_flush = agent._flush_messages_to_session_db
    foreign = {}

    def resume_after_lease_expiry(messages):
        entry = agent._pending_delegation_inject_claims[0]
        heartbeat = agent._delegation_inject_claim_heartbeat
        heartbeat["stop"].set()
        heartbeat["thread"].join(timeout=2)
        with ad._DB_LOCK, ad._transaction() as conn:
            conn.execute("UPDATE async_delegations SET delivery_claimed_at=0 WHERE delegation_id=?", (unit,))
        foreign["claim"] = ad.claim_event_delivery(entry["event"], "other-consumer")
        assert foreign["claim"] is not None
        return original_flush(messages)

    monkeypatch.setattr(agent, "_flush_messages_to_session_db", resume_after_lease_expiry)
    messages = _messages()
    try:
        _flush_session_db_after_tool_progress(agent, messages, stage="lease takeover")
        with ad._DB_LOCK, ad._transaction() as conn:
            rows = conn.execute("SELECT content FROM messages WHERE session_id=? AND role='tool'", (agent.session_id,)).fetchall()
            claim = conn.execute("SELECT delivery_claim FROM async_delegations WHERE delegation_id=?", (unit,)).fetchone()[0]
        assert claim == foreign["claim"]
        assert not any("EXCLUSIVE_EVIDENCE" in str(row) for row in rows), rows
    finally:
        agent._session_db.close()


def test_candidate_status_read_failure_preserves_all_queue_or_claim_owners(monkeypatch):
    first = _record()
    second = _record()
    assert _complete_unit(first, _child(0, "first evidence"))
    assert _complete_unit(second, _child(0, "second evidence"))
    events = {evt["delegation_id"]: evt for evt in _queue_contents()}
    assert ad.claim_event_delivery(events[second], "competing-consumer") is not None
    real_state = ad.get_event_delivery_state

    def fail_status_read(evt):
        if evt["delegation_id"] == second:
            raise sqlite3.OperationalError("database is locked")
        return real_state(evt)

    agent = _tool_boundary_agent()
    agent._flush_messages_to_session_db = lambda messages: None
    monkeypatch.setattr(ad, "get_event_delivery_state", fail_status_read)
    _flush_session_db_after_tool_progress(agent, _messages(), stage="status read failure")
    queued = {evt["delegation_id"] for evt in _queue_contents()}
    owned = {entry["event_id"] for entry in agent._pending_delegation_inject_claims}
    assert first in queued | owned, {"queued": queued, "owned": owned, "durable_first": _event_state(first)}
