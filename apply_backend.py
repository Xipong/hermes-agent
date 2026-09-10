from pathlib import Path
import shutil
root = Path.cwd()
def replace(path, old, new):
    p=root/path; text=p.read_text(); assert text.count(old)==1, (path,text.count(old)); p.write_text(text.replace(old,new))
(root/'tools/kanban_toolset_context.py').write_text('''"""Explicit Kanban selection during one model-schema build.

The registry's ordinary availability cache is profile-wide, while a gateway
can build schemas for several platforms in the same profile concurrently.
Carry only the explicit selection through a ContextVar, never process env.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterable, Iterator, Optional

_requested: ContextVar[Optional[bool]] = ContextVar("kanban_toolset_requested", default=None)


def kanban_toolset_requested() -> Optional[bool]:
    """None outside schema assembly; otherwise whether Kanban was named explicitly."""
    return _requested.get()


@contextmanager
def scoped_kanban_toolset_selection(toolsets: Optional[Iterable[str]]) -> Iterator[None]:
    """An all/default selection is not an explicit workflow opt-in."""
    token = _requested.set("kanban" in (toolsets or ()))
    try:
        yield
    finally:
        _requested.reset(token)
''')
replace('tools/kanban_tools.py','from tools.registry import registry, tool_error','from tools.registry import no_cache_check_fn, registry, tool_error')
replace('tools/kanban_tools.py','''    # load_config() is mtime-cached and check_fn results are TTL-cached (~30s).
    try:
        return "kanban" in load_config().get("toolsets", [])
    except Exception:
        return False
''','''    from tools.kanban_toolset_context import kanban_toolset_requested

    requested = kanban_toolset_requested()
    if requested:
        return True
    try:
        config = load_config()
        # Preserve the legacy profile-wide opt-in for callers using bundles.
        if "kanban" in (config.get("toolsets") or []):
            return True
        if requested is not None:
            # Never borrow another platform's opt-in during schema assembly.
            return False
        # Offer-time skill discovery has no platform selection. A saved opt-in
        # makes the playbook relevant; actual schemas still use the scope above.
        from hermes_cli.tools_config import _get_platform_tools

        platforms = config.get("platform_toolsets") or {}
        return any(
            "kanban" in _get_platform_tools(config, platform, include_default_mcp_servers=False)
            for platform, names in platforms.items() if isinstance(names, list)
        )
    except Exception:
        return False
''')
for name in ('_check_kanban_mode', '_check_kanban_orchestrator_mode'):
    replace('tools/kanban_tools.py',f'def {name}() -> bool:',f'@no_cache_check_fn\ndef {name}() -> bool:')
replace('model_tools.py','''    # Registry returns only tools whose check_fn passes.
    filtered_tools = _apply_dynamic_schemas(registry.get_definitions(tools_to_include, quiet=quiet_mode))
''','''    # Selection is per schema, not per process/profile. Kanban's local checks
    # are uncached; the outer definitions cache already keys on this selection.
    from tools.kanban_toolset_context import scoped_kanban_toolset_selection
    with scoped_kanban_toolset_selection(enabled_toolsets):
        filtered_tools = _apply_dynamic_schemas(registry.get_definitions(tools_to_include, quiet=quiet_mode))
''')
replace('hermes_cli/tools_config.py','''    ("todo",            "📋 Task Planning",             "todo_list"),''','''    ("todo",            "📋 Task Planning",             "todo_list"),
    ("kanban",          "📌 Kanban",                    "opt-in task board tools for this platform"),''')
replace('hermes_cli/tools_config.py','''"video_gen", "x_search", "a2a"}''','''"video_gen", "x_search", "a2a", "kanban"}''')
replace('hermes_cli/tools_config.py','''read-time-resolved toolsets (``kanban``, recovered composites, MCP names) are NOT here.''','''read-time-resolved toolsets (recovered composites, MCP names) are NOT here.''')
replace('hermes_cli/tools_config.py','''read-time toolsets (``kanban``) the user never''','''read-time toolsets (MCP names) the user never''')
replace('hermes_cli/tools_config.py','''    # agent.disabled_toolsets is a global suppression list (#86661) and runs LAST so it overrides everything
''','''    # Legacy profile opt-in is a fallback only. A saved platform list (even
    # empty) is authoritative, so a later disable cannot silently re-enable it.
    if not explicitly_configured and "kanban" in (config.get("toolsets") or []):
        enabled_toolsets.add("kanban")

    # agent.disabled_toolsets is a global suppression list (#86661) and runs LAST so it overrides everything
''')
replace('tui_gateway/server.py','''        return sorted(enabled | _gui_surface_toolsets(session_platform)) if enabled else None''','''        # An explicitly empty selection is not "all". Keep only client-surface
        # affordances instead of resurrecting legacy opt-ins via the None path.
        return sorted(enabled | _gui_surface_toolsets(session_platform))''')
replace('website/docs/user-guide/features/kanban.md','## How workers interact with the board','''## Enabling tools for a chat profile

The Desktop Kanban plugin displays the board; it does not grant the chat agent
permission to manage tasks. Enable the `kanban` toolset for the profile and
platform that should orchestrate work:

```bash
hermes -p planner tools enable kanban
```

This saves `platform_toolsets.cli`, used by CLI, TUI and Desktop chats. Other
messaging platforms have independent selections. Start a new chat after changing
this setting; existing conversations retain their tool schemas and prompt cache.
Explicitly empty selections and `agent.disabled_toolsets` remain authoritative.
Legacy top-level `toolsets: [kanban]` remains a fallback when no platform selection
was saved; `all` alone is not a Kanban opt-in.

Dispatcher-owned workers receive their task lifecycle tools automatically.
`delegate_task` children do not gain permission to mutate the board.

## How workers interact with the board''')
shutil.copyfile(Path(__file__).with_name('test_kanban_toolset_opt_in.py'), root/'tests/tools/test_kanban_toolset_opt_in.py')
