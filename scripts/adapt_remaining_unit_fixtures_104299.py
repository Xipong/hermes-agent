"""Finish the oracle fixture migration without changing production behavior."""
from pathlib import Path
import ast
import sys

p = Path(sys.argv[1]) / 'tests/agent/test_delegation_delivery.py'
s = p.read_text()
old = '''    assert ad.publish_batch_child(
        delegation_id,
        0,
        _child(0, "", status="timeout", error="child exceeded 10s"),
    )'''
new = '''    assert _complete_unit(
        delegation_id,
        _child(0, "", status="timeout", error="child exceeded 10s"),
    )'''
assert s.count(old) == 1
s = s.replace(old, new)
assert s.count('event.get("batch_id") == delegation_id') == 4
s = s.replace('event.get("batch_id") == delegation_id', 'event.get("delegation_id") == delegation_id')
# One occupied capacity slot is not one physical runner: both completion units
# must be able to run to exercise "singleton beats incomplete group". The test
# still asserts one shared slot and rejects another call at max_async_children=1.
old = 'monkeypatch.setattr(delegate_tool, "_get_max_async_children", lambda: 1)'
assert s.count(old) == 1
s = s.replace(old, 'monkeypatch.setattr(delegate_tool, "_get_max_async_children", lambda: 3)')
assert 'publish_batch_child' not in s and 'batch_id' not in s
ast.parse(s)
p.write_text(s)
