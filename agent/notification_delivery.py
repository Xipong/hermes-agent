"""Current typed-input receipts, independent of the receiving model's success."""

from agent.persisted_turn_receipt import committed_row_id


def export_notification_input_delivery(agent, result):
    """Export only the staged input that survived this turn's durable transcript.

    A historical text match, an admitted thread, or a successful summary is not a
    delivery receipt. Retain the staged row's identity across early error returns;
    if rollback removed it, fail closed even when identical old input survives.
    """
    staged = getattr(agent, "_notification_turn_input", None)
    if not isinstance(result, dict) or not isinstance(staged, tuple):
        return
    turn_id, original = staged
    if turn_id != result.get("turn_id"):
        return
    original_id = committed_row_id(original)
    for row in result.get("messages", ()):
        if not isinstance(row, dict) or not (
            row is original or (original_id is not None and committed_row_id(row) == original_id)
        ):
            continue
        if (row.get("_db_persisted") is True and row.get("role") == "user"
                and row.get("display_kind") == original.get("display_kind")
                and row.get("content") == original.get("content")):
            result["input_delivery"] = {
                "turn_id": turn_id, "content": row["content"], "display_kind": row["display_kind"]}
        return


def notification_input_committed(result, text, display_kind):
    """Whether this exact typed input landed, not whether its summary succeeded."""
    receipt = result.get("input_delivery")
    return bool(
        not result.get("interrupted") and result.get("status") != "cancelled"
        and isinstance(receipt, dict) and receipt.get("turn_id")
        and receipt["turn_id"] == result.get("turn_id")
        and receipt.get("content") == text and receipt.get("display_kind") == display_kind)
