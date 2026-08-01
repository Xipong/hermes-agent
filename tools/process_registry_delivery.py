"""Bounded ready-set reservations and delayed retry for the process completion queue.

The registry owns the queue/locks; this mixin never formats a result or runs a model.
"""

import heapq
import logging
import threading
import time

logger = logging.getLogger("tools.process_registry")


class CompletionDeliveryMixin:
    """Shared queue protocol for CLI, gateway, API server, and TUI consumers."""

    @staticmethod
    def _deferred_completion_key(event: dict) -> tuple:
        raw_keys = event.get("delivery_event_keys")
        if isinstance(raw_keys, (list, tuple)):
            event_keys = tuple(str(key) for key in raw_keys if key)
        else:
            event_key = str(event.get("delivery_event_key") or "")
            event_keys = (event_key,) if event_key else ("aggregate",)
        return (
            "async_delegation",
            str(event.get("delegation_id") or ""),
            event_keys,
        )


    def defer_unclaimed_delivery(self, event: dict) -> bool:
        """Requeue a pending durable event after its competing lease expires.

        ``claim_event_delivery()`` returning ``None`` is not enough to drop the
        RAM copy: after a quick restart the old process's lease can still be
        live. Terminal duplicates return ``False`` and disappear; pending rows
        enter one deduplicated heap and wake under the routing lock.
        """

        try:
            from tools.async_delegation import get_event_delivery_retry_delay

            delay = get_event_delivery_retry_delay(event)
        except Exception:
            logger.exception("Could not classify unclaimed delegation event")
            return False
        if delay is None:
            return False

        key = self._deferred_completion_key(event)
        if not key[1]:
            return False
        deadline = time.monotonic() + max(0.05, float(delay))
        with self._deferred_completion_condition:
            existing = self._deferred_completion_deadlines.get(key)
            if existing is not None and existing <= deadline:
                return True
            self._deferred_completion_sequence += 1
            self._deferred_completion_deadlines[key] = deadline
            heapq.heappush(
                self._deferred_completion_heap,
                (
                    deadline,
                    self._deferred_completion_sequence,
                    key,
                    event,
                ),
            )
            thread = self._deferred_completion_thread
            if thread is None or not thread.is_alive():
                thread = threading.Thread(
                    target=self._deferred_completion_loop,
                    name="completion-lease-retry",
                    daemon=True,
                )
                self._deferred_completion_thread = thread
                thread.start()
            self._deferred_completion_condition.notify()
        return True


    def _deferred_completion_loop(self) -> None:
        while True:
            with self._deferred_completion_condition:
                while not self._deferred_completion_heap:
                    self._deferred_completion_condition.wait()
                deadline, _sequence, key, event = self._deferred_completion_heap[0]
                current = self._deferred_completion_deadlines.get(key)
                if current != deadline:
                    heapq.heappop(self._deferred_completion_heap)
                    continue
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    self._deferred_completion_condition.wait(timeout=remaining)
                    continue
                heapq.heappop(self._deferred_completion_heap)
                self._deferred_completion_deadlines.pop(key, None)

            try:
                with self.completion_routing_lock:
                    self.completion_queue.put(event)
            except Exception:
                logger.exception(
                    "Deferred completion requeue failed; rescheduling %r", key
                )
                # The heap entry was already removed. Reclassify the durable
                # row and schedule it again rather than silently losing the
                # only in-memory copy on a transient/custom queue failure.
                self.defer_unclaimed_delivery(event)


    def collect_ready_after_turn_siblings(self, seed: dict) -> dict:
        """Fold queued ready siblings into one transient after-turn envelope.

        The caller may already hold ``completion_routing_lock``; it is an RLock
        so this helper is safe at both direct-consumer and shared-drain seams.
        Only the bounded queue snapshot present at this delivery boundary is
        inspected. Foreign delegations and later arrivals remain queued.
        """

        from tools.async_delegation import coalesce_ready_after_turn_events

        def delivery_keys(event: dict) -> "list[str]":
            raw_keys = event.get("delivery_event_keys")
            if isinstance(raw_keys, (list, tuple)):
                return [str(key) for key in raw_keys if key]
            key = str(event.get("delivery_event_key") or "")
            return [key] if key else []

        delivery = str(seed.get("result_delivery") or "after_turn").strip().lower()
        seed_keys = delivery_keys(seed)
        delegation_id = str(seed.get("delegation_id") or "")
        if not (
            seed.get("type") == "async_delegation"
            and delivery == "after_turn"
            and bool(seed.get("is_batch"))
            and bool(seed_keys)
            and all(key.startswith("task:") for key in seed_keys)
            and delegation_id
        ):
            return seed

        siblings = [seed]
        requeue: "list[dict]" = []
        with self.completion_routing_lock:
            try:
                scan_count = self.completion_queue.qsize()
            except Exception:
                scan_count = 0
            for _ in range(max(0, scan_count)):
                try:
                    candidate = self.completion_queue.get_nowait()
                except Exception:
                    break
                candidate_keys = delivery_keys(candidate)
                if (
                    candidate.get("type") == "async_delegation"
                    and str(
                        candidate.get("result_delivery") or "after_turn"
                    ).strip().lower()
                    == "after_turn"
                    and bool(candidate.get("is_batch"))
                    and str(candidate.get("delegation_id") or "") == delegation_id
                    and bool(candidate_keys)
                    and all(key.startswith("task:") for key in candidate_keys)
                ):
                    siblings.append(candidate)
                else:
                    requeue.append(candidate)
            for candidate in requeue:
                self.completion_queue.put(candidate)
        return coalesce_ready_after_turn_events(siblings)[0]
