"""Reviewed finalization; orchestration remains outside the product PR."""
import os

import pr120894_apply as a

base_patch = a.patch_runtime
base_patch_sources = a.patch_sources


def patch_runtime(text):
    text = base_patch(text)
    text = a.replace(text,
        '    def on_event(note: dict) -> None:\n        if not isinstance(note, dict):',
        '    def on_event(note: dict) -> None:\n        nonlocal previous_reasoning_source, active_reasoning_item_id\n        if not isinstance(note, dict):')
    text = a.replace(text,
        '        params = params if isinstance(params, dict) else {}\n        # The session has already filtered foreign thread/turn notifications.',
        '        params = params if isinstance(params, dict) else {}\n        # The bridge belongs to a reusable app-server session, not a single turn.\n        # A later turn must not inherit separators or unfinished native source IDs.\n        if method in {"turn/started", "turn/completed"}:\n            previous_reasoning_source = None\n            active_reasoning_item_id = None\n            reasoning_sources.clear()\n        # The session has already filtered foreign thread/turn notifications.')
    return text


def patch_sources():
    base_patch_sources()
    # Current main moved these shared fixture writers out of e2e/fixtures.ts.
    # Adapt our spec to the canonical helper, not a new re-export or a copied writer.
    spec = a.CANDIDATE / "apps/desktop/e2e/codex-commentary-hydration.spec.ts"
    text = a.replace(spec.read_text(),
        "import { type MockServer, startMockServer } from '../../../tests-js/scripts/mock-server'",
        "import { writeEnvFile, writeMockProviderConfig } from '../../../tests-js/scripts/mock-provider-config'\nimport { type MockServer, startMockServer } from '../../../tests-js/scripts/mock-server'")
    text = a.replace(text,
        "  waitForAppReady,\n  writeEnvFile,\n  writeMockProviderConfig\n",
        "  waitForAppReady\n")
    spec.write_text(text)


def main():
    # Explicit disposable PM interpreter for the existing Electron fixture contract.
    os.environ["HERMES_DESKTOP_PYTHON"] = os.environ["HERMES_PYTHON"]
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
    a.patch_sources = patch_sources
    a.main()


if __name__ == "__main__":
    main()
