"""Process/delegation completion carriers compose on one append-only tool boundary."""
from copy import deepcopy

import pytest

from tests.agent.test_process_completion_inject import _rig, _complete, _complete_messages
from tests.agent.test_delegation_delivery import _record, _complete_unit, _child, _event_state


@pytest.mark.parametrize("persist", [True, False])
def test_process_and_delegation_receipts_share_commit_or_rollback(tmp_path, monkeypatch, persist):
    from agent.tool_executor import _flush_session_db_after_tool_progress
    from tools import async_delegation as ad
    from tools.process_completion_delivery import delivered
    ad._reset_for_tests()
    agent, registry = _rig(tmp_path, monkeypatch)
    from hermes_state import SessionDB
    agent._session_db.close()
    agent._session_db = SessionDB(db_path=ad._db_path())
    try:
        unit = _record(turn_id="turn-a", parent_session_id=agent.session_id)
        assert _complete_unit(unit, _child(0, "CHILD EVIDENCE"))
        _complete(registry, "proc_combined")
        event = list(registry.completion_queue.queue)[-1]
        messages = _complete_messages()
        original = deepcopy(messages)
        if not persist:
            monkeypatch.setattr(agent, "_flush_messages_to_session_db", lambda *args: False)
        assert _flush_session_db_after_tool_progress(agent, messages, stage="composed receipt") is persist
        if persist:
            assert "CHILD EVIDENCE" in messages[-1]["content"], {
                "events": list(registry.completion_queue.queue), "active": agent._active_turn_id,
                "pending": getattr(agent, "_pending_delegation_inject_claims", None)}
            assert "OUTPUT proc_combined" in messages[-1]["content"]
            metadata = messages[-1]["display_metadata"]
            assert metadata["delegation_event_ids"] == [unit]
            assert metadata["process_delivery"] == "tool_boundary"
            assert _event_state(unit)[0] == "delivered"
            assert delivered(registry, event)
            assert registry.completion_queue.empty()
        else:
            assert [m["content"] for m in messages if "content" in m] == [m["content"] for m in original if "content" in m]
            assert _event_state(unit)[0] == "pending"
            assert not delivered(registry, event)
            assert {e.get("delegation_id") or e.get("session_id") for e in registry.completion_queue.queue} == {unit, "proc_combined"}
    finally:
        agent._session_db.close()
        ad._reset_for_tests()


def test_receipt_requires_exact_process_carrier_after_delegation_rollback(tmp_path, monkeypatch):
    """A successful fallback DB append after a lost sibling claim is not process delivery."""
    from agent.tool_executor import _flush_session_db_after_tool_progress
    from tools import async_delegation as ad
    from tools.process_completion_delivery import delivered
    ad._reset_for_tests()
    agent, registry = _rig(tmp_path, monkeypatch)
    try:
        # The completion ledger is deliberately a different store: the canonical
        # writer rejects that claim, restores ordinary tool content and retries.
        unit = _record(turn_id="turn-a", parent_session_id=agent.session_id)
        assert _complete_unit(unit, _child(0, "UNPROVEN CHILD EVIDENCE"))
        _complete(registry, "proc_sibling_rollback")
        process = list(registry.completion_queue.queue)[-1]
        messages = _complete_messages()
        assert _flush_session_db_after_tool_progress(agent, messages, stage="lost sibling claim")
        assert messages[-1]["content"] == "second"
        assert not delivered(registry, process)
        assert process in list(registry.completion_queue.queue)
    finally:
        agent._session_db.close()
        ad._reset_for_tests()
