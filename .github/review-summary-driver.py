import ast
import importlib.util
from pathlib import Path
import runpy
import sys

spec = importlib.util.spec_from_file_location('builder', '/tmp/build_review_pr.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
original = module.swap

def swap(path, old, new):
    if path == 'hermes_state_messages.py' and 'return [{k: v for k, v in message.items()' in old:
        old = old.replace('            include_ancestors=', '            rows, session_id=session_id, include_ancestors=')
        new = new.replace('            include_ancestors=', '            rows, session_id=session_id, include_ancestors=')
    if path == 'agent/turn_context.py':
        p = Path(path)
        text = p.read_text()
        node = next(n for n in ast.walk(ast.parse(text)) if isinstance(n, ast.FunctionDef) and n.name == 'build_turn_context')
        first = node.body[0]
        line = first.end_lineno if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str) else first.lineno - 1
        lines = text.splitlines(keepends=True)
        lines[line:line] = ['    # Hosts may supply raw display history instead of the model projection.\n', '    if conversation_history:\n', '        conversation_history = [m for m in conversation_history if m.get("display_kind") != "review_summary"]\n']
        p.write_text(''.join(lines))
        return
    return original(path, old, new)

module.swap = swap
module.tests()
if '--apply' in sys.argv:
    module.apply()
runpy.run_path('/tmp/refine_review_patch.py', run_name='__main__')
