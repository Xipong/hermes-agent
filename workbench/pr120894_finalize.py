"""Reviewed second pass; orchestration remains outside the product PR."""
import pr120894_apply as a

base_patch = a.patch_runtime


def patch_runtime(text):
    text = base_patch(text)
    text = a.replace(text,
        '    def on_event(note: dict) -> None:\n        if not isinstance(note, dict):',
        '    def on_event(note: dict) -> None:\n        nonlocal previous_reasoning_source, active_reasoning_item_id\n        if not isinstance(note, dict):')
    text = a.replace(text,
        '        params = params if isinstance(params, dict) else {}\n        # The session has already filtered foreign thread/turn notifications.',
        '        params = params if isinstance(params, dict) else {}\n        # The bridge belongs to a reusable app-server session, not a single turn.\n        # A later turn must not inherit separators or unfinished native source IDs.\n        if method in {"turn/started", "turn/completed"}:\n            previous_reasoning_source = None\n            active_reasoning_item_id = None\n            reasoning_sources.clear()\n        # The session has already filtered foreign thread/turn notifications.')
    return text


def main():
    timeline = a.ROOT / "workbench/pr120894_boundary_test.ts"
    timeline.write_text(a.replace(timeline.read_text(), "}, 'start')[0]", "}, 'running')[0]"))
    tests = a.ROOT / "workbench/pr120894_segments_test.py"
    tests.write_text(tests.read_text() + '''
    # The event bridge survives multiple turns; reset source state on either turn boundary.
    for boundary in ("turn/completed", "turn/started"):
        bridge({"method": boundary, "params": {"turn": {"id": "next-turn"}}})
        wire.clear()
        observers.clear()
        fresh = {"type": "reasoning", "id": "rs_fresh_" + boundary}
        bridge({"method": "item/started", "params": {"item": fresh}})
        bridge({"method": method, "params": {"itemId": fresh["id"], index_key: 0, "delta": "Fresh"}})
        bridge({"method": "item/completed", "params": {"item": fresh}})
        assert _flat(wire) == "Fresh"
        assert _observed(observers) == "Fresh"
''')
    a.patch_runtime = patch_runtime
    a.main()


if __name__ == "__main__":
    main()
