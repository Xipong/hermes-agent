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
