from pathlib import Path
root=Path.cwd()
p=root/'tests/hermes_cli/test_tools_config.py';s=p.read_text();a=s.index('# ── Checklist diff scope: non-configurable toolsets (kanban)');b=s.index('def test_vision_picker_custom_endpoint',a)
s=s[:a]+'''# Kanban now participates in the checklist: an explicit deselection must be
# both visible in the diff and durable in the platform selection.
def test_kanban_checklist_reports_and_persists_explicit_removal():
    config = {"platform_toolsets": {"telegram": ["kanban", "web", "terminal"]}}
    current = _get_platform_tools(config, "telegram", include_default_mcp_servers=False)
    universe = _checklist_toolset_keys("telegram")
    new_enabled = current - {"kanban"}
    assert ((current - new_enabled) & universe) == {"kanban"}
    with patch("hermes_cli.tools_config.save_config"):
        _save_platform_tools(config, "telegram", new_enabled)
    assert "kanban" not in _get_platform_tools(config, "telegram", include_default_mcp_servers=False)
    assert {"web", "terminal"} <= set(config["platform_toolsets"]["telegram"])


'''+s[b:];p.write_text(s)
p=root/'tests/hermes_cli/test_kanban_worker_spawn_toolsets.py';s=p.read_text().replace('    assert "kanban" in resolved  # recovered worker lifecycle surface','''    # Opt-in is no longer inferred for ordinary chats. The dispatcher-owned
    # worker gets lifecycle tools at schema assembly, independently of the
    # assignee's saved chat selection.
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_spawn_tools")
    from model_tools import get_tool_definitions
    names = {t["function"]["name"] for t in get_tool_definitions(resolved, quiet_mode=True, skip_tool_search_assembly=True)}
    assert "kanban_complete" in names
    assert "kanban_list" not in names''');p.write_text(s)
p=root/'tests/tools/test_kanban_toolset_opt_in.py';s=p.read_text().replace('''        assert "file" in selected()
        from agent.skill_utils''','''        assert "file" in selected()
        # A second profile in the same process must not borrow this grant or
        # poison the first profile's cached schema on return.
        from hermes_constants import set_hermes_home_override, reset_hermes_home_override
        other_home = tmp_path / "profiles" / "observer"
        token = set_hermes_home_override(other_home)
        try:
            save_config({"platform_toolsets": {"cli": ["file"]}})
            assert not _names(selected())
        finally:
            reset_hermes_home_override(token)
        assert _names(selected()) == enabled_names
        from agent.skill_utils''');p.write_text(s)
