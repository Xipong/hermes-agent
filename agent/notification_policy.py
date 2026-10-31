"""Reply policy for runtime-typed notification turns, independent of any surface."""

from typing import Any


# Runtime-authored row metadata, never inferred from notification-looking text.
NOTIFICATION_DISPLAY_KINDS = frozenset({"internal_notification", "process_complete", "async_delegation_complete"})
NOTIFICATION_REPLY_CONTRACT = (
    "[INTERNAL NOTIFICATION REPLY POLICY: Handle only the new results in this notification. "
    "If they do not materially change or correct an answer already delivered, respond exactly "
    "NO_REPLY. Do not send an acknowledgement merely to say results were received or unchanged. "
    "Report useful new findings, failures, corrections and decisions requiring attention. "
    "A blank response is not NO_REPLY.]"
)


def is_notification_message(message: Any) -> bool:
    return isinstance(message, dict) and message.get("display_kind") in NOTIFICATION_DISPLAY_KINDS


def silence_delivery_text(response: Any, *, successful: bool) -> Any:
    """Filter only the delivered copy; failures and replay bytes remain intact."""
    from gateway.response_filters import is_intentional_silence_response, strip_trailing_silence_marker

    if not successful:
        return response
    return "" if is_intentional_silence_response(response) else strip_trailing_silence_marker(response)


def project_notification_silence(messages: list[dict]) -> list[dict]:
    """Apply the typed current-turn policy to display history, never stored/model history."""
    projected = []
    notification = False
    for message in messages:
        if not isinstance(message, dict):
            projected.append(message)
            continue
        if message.get("role") == "user":
            notification = is_notification_message(message)
        if (not notification or message.get("role") != "assistant" or message.get("tool_calls")
                or message.get("display_kind") == "hidden"):
            projected.append(message)
            continue
        text = message.get("display_content", message.get("content", message.get("text")))
        successful = message.get("finish_reason") in (None, "stop") and not any(
            message.get(key) for key in ("failed", "error", "partial", "interrupted"))
        visible = silence_delivery_text(text, successful=successful)
        if visible == text:
            projected.append(message)
        else:
            projected.append({**message, "display_content": visible,
                              **({"display_kind": "hidden"} if visible == "" else {})})
    return projected
