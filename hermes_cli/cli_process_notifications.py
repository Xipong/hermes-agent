"""CLI notification ownership, structured queueing and last-moment consumption."""


class CLIProcessNotificationsMixin:
    def _owns_process_notification(self, event: dict) -> bool:
        """Whether this session owns a delegation event (pre-compression keys resolve to their continuation; fail closed)."""
        event_key = str(event.get("session_key") or "")
        current_key = str(getattr(self, "session_id", "") or "")
        if not event_key or not current_key:
            return False
        if event_key == current_key:
            return True
        try:
            session_db = getattr(self, "_session_db", None)
            resolved_key = (
                session_db.resolve_resume_session_id(event_key) if session_db is not None else event_key
            ) or event_key
        except Exception:
            resolved_key = event_key
        return str(resolved_key) == current_key

    def _background_notifications_suppressed(self) -> bool:
        """Whether ``display.background_process_notifications`` is ``off`` for this CLI session.

        The key gates the gateway's completion injection (#9290) but the CLI drain never consulted
        it, so the documented ``off`` escape hatch silently did nothing here (#123114). Mirrors the
        gateway semantics: events are still drained, claimed and acknowledged — only the
        turn-starting injection is suppressed."""
        try:
            from cli import CLI_CONFIG
            mode = str((CLI_CONFIG.get("display") or {}).get("background_process_notifications") or "").strip().lower()
        except Exception:
            return False
        return mode == "off"

    def _drain_process_notifications(self, consumer: str) -> None:
        from hermes_cli.gateway_tools_notify import gateway_store, queue_admitted_turn
        store = gateway_store(self)
        if store is not None:
            # The process registry and its delivery claims live in the gateway, which admits the
            # notification turn itself; this viewer only paints it (IPS-086).
            queue_admitted_turn(self, store)
            return
        if getattr(self, "_last_turn_interrupted", False):
            return  # Stop holds automatic wakes until a genuine user turn clears the latch.
        from tools.process_registry import process_registry
        from tools.async_delegation import claim_event_delivery, complete_event_delivery
        from tools.process_registry_notifications import (
            HEARTBEAT_DISPLAY_KIND, ProcessNotificationBatch, TimelineNotification, group_process_notifications,
            heartbeat_display_text)

        claimed = []
        for event, text in process_registry.drain_notifications(
            session_key=getattr(self, "session_id", "") or "", owns_event=self._owns_process_notification,
            skip_poll_observed=False,
        ):
            if event.get("type", "completion") == "completion":
                # Keep identity in the queued batch; enqueueing is not a model-delivery receipt.
                claimed.append((event, text))
                continue
            claim = claim_event_delivery(event, consumer)
            if claim is None:
                continue
            claimed.append((event, text))
            complete_event_delivery(event, claim)
        if self._background_notifications_suppressed():
            # Subagent results are not process notifications: they still land.
            claimed = [(event, text) for event, text in claimed if event.get("type") == "async_delegation"]
        for notifications in group_process_notifications(claimed):
            event, text = notifications[0]
            evt_type = event.get("type", "completion")
            if evt_type == "completion":
                pending = ProcessNotificationBatch(notifications)
            elif evt_type == "heartbeat":
                pending = TimelineNotification(text, heartbeat_display_text(event), HEARTBEAT_DISPLAY_KIND)
            else:
                pending = TimelineNotification.for_delegation(text, event) if evt_type == "async_delegation" else text
                from agent.notification_presentation import diagnostic_process_event
                if diagnostic_process_event(event) and not isinstance(pending, TimelineNotification):
                    pending = TimelineNotification(text, text, "internal_notification", "diagnostic")
            self._pending_input.put(pending)

    def _run_process_notification(self, notice, run):
        """Keep process identities until the receiving turn confirms its canonical input."""
        batch = getattr(notice, "process_batch", None)
        if batch is None:
            return run(notice)
        from tools.process_registry import process_registry
        from tools import process_completion_delivery as delivery
        from tools.process_registry_notifications import ProcessNotificationBatch, TimelineNotification

        if getattr(self, "_last_turn_interrupted", False):
            delivery.requeue_front(process_registry, [event for event, _ in batch._live(process_registry)])
            return None
        claims = []
        committed = False
        try:
            for event, text in batch._live(process_registry):
                token = delivery.claim(process_registry, event, "cli-notification-turn")
                if token is not None:
                    claims.append((event, text, token))
            current = ProcessNotificationBatch(tuple((e, text) for e, text, _ in claims))
            text = current.render(process_registry)
            if text is None:
                return None
            current_notice = TimelineNotification(text, current.display_text(process_registry), notice.display_kind)
            self._last_turn_result = None
            result = run(current_notice)
            turn = self._last_turn_result or {}
            from agent.notification_delivery import notification_input_committed
            committed = notification_input_committed(turn, text, notice.display_kind)
            return result
        finally:
            if committed:
                for event, _text, token in claims:
                    delivery.acknowledge(process_registry, event, token)
            else:
                for event, _text, token in claims:
                    delivery.release(process_registry, event, token)
                delivery.requeue_front(process_registry, [event for event, _text, _ in claims])

    def _tui_unwrap_input(self, user_input):
        """Unwrap ``_VoiceInputMessage`` / ``_SeededQueryMessage`` -> ``(text_or_tuple, is_voice_input, is_seeded_query)``."""
        from cli import _VoiceInputMessage, _SeededQueryMessage
        from tools.process_registry import process_registry
        from tools.process_registry_notifications import (
            PROCESS_COMPLETE_DISPLAY_KIND, ProcessNotificationBatch, TimelineNotification)
        if isinstance(user_input, ProcessNotificationBatch):
            batch = user_input
            rendered = batch.render(process_registry)
            user_input = rendered and TimelineNotification(
                rendered, batch.display_text(process_registry), PROCESS_COMPLETE_DISPLAY_KIND)
            if user_input:
                user_input.process_batch = batch
        # Voice-transcribed messages arrive wrapped in a sentinel so only genuine STT output gets the voice
        # prefix (#65827).
        is_voice_input = isinstance(user_input, _VoiceInputMessage)
        if is_voice_input:
            user_input = user_input.text
        is_seeded_query = isinstance(user_input, _SeededQueryMessage)
        if is_seeded_query:
            from hermes_cli.gateway_tools_notify import arm_adopted
            arm_adopted(self, user_input)
            user_input = (user_input.text, user_input.images) if user_input.images else user_input.text
        return user_input, is_voice_input, is_seeded_query

