"""Validation-only patch builder for PR #115033; never included in its branch."""
from pathlib import Path
import sys

STATUS_TEST = '''"""Target resolution errors must remain diagnostic on the readiness surfaces (#115033)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from hermes_cli.config import save_config
from tools.computer_use import cua_backend_driver as driver, permissions


@pytest.mark.parametrize("target", ["mac", "unsupported-host"])
def test_target_errors_preserve_status_payload_and_recover(tmp_path, monkeypatch, capsys, target):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "profile"))
    # Exercise a native host without WSL interop, without pretending to be another OS.
    monkeypatch.setattr("hermes_constants.is_wsl", lambda: False)
    binary = str(tmp_path / "missing-driver")
    probe = Mock(side_effect=AssertionError("invalid or missing drivers must not be spawned"))
    monkeypatch.setattr(permissions, "_run", probe)
    monkeypatch.setattr(permissions.subprocess, "run", probe)
    save_config({"computer_use": {"target": "auto"}})
    missing = permissions.computer_use_status(binary)
    assert missing["installed"] is False and missing["ready"] is None
    assert missing["error"] is None
    if target == "unsupported-host":
        target = "windows" if sys.platform == "linux" else "linux"
    save_config({"computer_use": {"target": target}})
    with pytest.raises(ValueError) as invalid:
        driver.resolve_cua_driver_cmd(binary)
    diagnostic = str(invalid.value)
    status = permissions.computer_use_status(binary)
    assert list(status) == list(missing)
    assert status == {**missing, "error": diagnostic}
    if sys.platform == "darwin":
        assert permissions.request_permissions_grant(binary) == 2
        assert diagnostic in capsys.readouterr().err
    else:
        assert permissions.request_permissions_grant(binary) == 64
    save_config({"computer_use": {"target": "auto"}})
    assert permissions.computer_use_status(binary) == missing
    probe.assert_not_called()
'''

DAEMON_TEST = '''

@pytest.mark.linux_only
@pytest.mark.parametrize("failure", ["nonzero", "empty", "multiline", "missing", "timeout"])
def test_manifest_translation_failure_is_a_retryable_tool_error(interop, tmp_path, monkeypatch, failure):
    """The existing tool boundary must refuse startup, not drop the manifest or cache a broken backend."""
    from hermes_cli.config import save_config

    host, _, _ = interop
    manifest = tmp_path / "capabilities.yaml"
    manifest.write_text("version: 3\\n")
    save_config({"computer_use": {"target": "windows", "permission_mode": "bounded",
                                  "capability_manifest": str(manifest)}})
    real_run = cb._run_quiet
    translations = []

    def failed_translation(argv, **kwargs):
        if argv[:2] == ["wslpath", "-w"]:
            translations.append(argv)
            if failure == "missing":
                raise FileNotFoundError("wslpath is unavailable")
            if failure == "timeout":
                raise driver.subprocess.TimeoutExpired(argv, 3.0)
            output = {"nonzero": "ignored", "empty": "", "multiline": "first\\nsecond"}[failure]
            return SimpleNamespace(returncode=1 if failure == "nonzero" else 0, stdout=output)
        return real_run(argv, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(cb, "_run_quiet", failed_translation)
        result = json.loads(registry.dispatch("computer_use", {"action": "capture", "app": "screen"},
                                              session_id="manifest-error"))
    assert translations == [["wslpath", "-w", str(manifest)]]
    assert "computer_use backend unavailable:" in result["error"], result
    message = "wslpath" if failure in {"missing", "timeout"} else "Cannot translate the capability manifest"
    assert message in result["error"], result
    assert not tool._backends
    launches = [json.loads(line) for line in host.with_suffix(".log").read_text().splitlines()]
    assert not any(args[0] in {"serve", "mcp"} for args in launches)

    # Retrying through the same public entry point succeeds once translation recovers.
    result = json.loads(registry.dispatch("computer_use", {"action": "list_windows"}, session_id="manifest-error"))
    assert result["windows"][0]["app_name"] == "HOST", result
    launches = [json.loads(line) for line in host.with_suffix(".log").read_text().splitlines()]
    serve = [args for args in launches if args[0] == "serve"]
    assert len(serve) == 1
    args = serve[0]
    assert args[args.index("--capability-manifest") + 1] == r"\\\\wsl.localhost\\Ubuntu\\manifest.yaml"
    assert "--approve-capability-manifest" in args
'''


def replace_once(text, before, after):
    assert text.count(before) == 1, before
    return text.replace(before, after, 1)


def prepare_tests():
    path = Path("tests/tools/test_computer_use_target_status.py")
    assert not path.exists()
    path.write_text(STATUS_TEST, encoding="utf-8", newline="\n")
    path = Path("tests/tools/test_computer_use_wsl_host.py")
    text = path.read_text(encoding="utf-8")
    assert "test_manifest_translation_failure_is_a_retryable_tool_error" not in text
    path.write_text(text + DAEMON_TEST, encoding="utf-8", newline="\n")


def prepare_source():
    path = Path("tools/computer_use/permissions.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(text,
        '    plat, binary = sys.platform, resolve_cua_driver_cmd(driver_cmd)\n',
        '    plat = sys.platform\n')
    text = replace_once(text,
        '                           "installed": bool(binary), "version": None, "ready": None, "can_grant": plat == "darwin",\n',
        '                           "installed": False, "version": None, "ready": None, "can_grant": plat == "darwin",\n')
    text = replace_once(text,
        '                           "checks": [], "source": None, "error": None, **{k: None for k in _BOOLS}}\n    if not binary:\n',
        '                           "checks": [], "source": None, "error": None, **{k: None for k in _BOOLS}}\n'
        '    try:\n'
        '        binary = resolve_cua_driver_cmd(driver_cmd)\n'
        '    except ValueError as exc:\n'
        '        out["error"] = str(exc)\n'
        '        return out\n'
        '    out["installed"] = bool(binary)\n'
        '    if not binary:\n')
    text = replace_once(text,
        '    the binary is missing, 64 on a non-macOS platform (no TCC model to grant)."""\n',
        '    the binary is missing or the target is invalid, 64 on a non-macOS platform (no TCC model to grant)."""\n')
    text = replace_once(text,
        '    binary = resolve_cua_driver_cmd(driver_cmd)\n    if not binary:\n',
        '    try:\n'
        '        binary = resolve_cua_driver_cmd(driver_cmd)\n'
        '    except ValueError as exc:\n'
        '        print(f"cua-driver permissions grant failed: {exc}", file=sys.stderr)\n'
        '        return 2\n'
        '    if not binary:\n')
    path.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    {"tests": prepare_tests, "source": prepare_source}[sys.argv[1]]()
