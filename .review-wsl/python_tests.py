from pathlib import Path
p = Path.cwd()
f = p / 'tests/hermes_cli/test_computer_use_wsl_install.py'
s = f.read_text(encoding='utf-8')
s = s.replace('from types import SimpleNamespace', 'import subprocess\nfrom types import SimpleNamespace')
s = s.replace('\n\n@pytest.fixture', '\n\npytestmark = pytest.mark.linux_only\n\n\n@pytest.fixture', 1)
s = s.replace("    monkeypatch.setattr(install.platform, 'system', lambda: 'Linux')\n", '')
s = s.replace("    monkeypatch.setattr(install, '_resolved_cua_driver_cmd', lambda: None)\n", "    monkeypatch.setattr(install, '_resolved_cua_driver_cmd', Mock(side_effect=[None, '/mnt/c/cua-driver.exe']))\n    monkeypatch.setattr(install, '_cua_driver_autostart_registered_windows', lambda: True)\n", 1)
s = s.replace("    monkeypatch.setattr(install, '_run_text', Mock(side_effect=AssertionError('installer started')))\n    assert install.install_cua_driver(upgrade=True, require_confirmed_update=True)", "    monkeypatch.setattr(install, '_run_text', Mock(side_effect=AssertionError('installer started')))\n    monkeypatch.setattr(install, '_cua_driver_autostart_registered_windows', lambda: True)\n    assert install.install_cua_driver(upgrade=True, require_confirmed_update=True)")
s += r'''

@pytest.mark.parametrize("task_after_repair", [True, False])
@pytest.mark.parametrize("fresh_install", [False, True])
def test_wsl_readiness_and_install_require_host_autostart(
    windows_target, monkeypatch, tmp_path, task_after_repair, fresh_install
):
    """Status, compatible-install repair and fresh installation use one host contract."""
    exe = tmp_path / "cua-driver.exe"
    exe.write_text("test driver")
    exe.chmod(0o755)
    native_path = r"D:\Users\Alice O'Brien\Cua\cua-driver.exe"
    state = {"installed": not fresh_install, "task": False}
    calls = []

    def which(name):
        if name in ("powershell.exe", "wslpath"):
            return name
        return str(exe) if state["installed"] and name == str(exe) else None

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[0] == "schtasks.exe":
            return SimpleNamespace(returncode=0 if state["task"] else 1)
        if argv[0] == "wslpath":
            assert argv == ["wslpath", "-w", str(exe.resolve())]
            return SimpleNamespace(returncode=0, stdout=native_path, stderr="")
        assert argv[0] == "powershell.exe", argv
        script = argv[-1]
        if install._CUA_INSTALL_PS1_URL in script:
            assert fresh_install
            state["installed"] = True
        else:
            assert "-FilePath $exe" in script
            assert "-ArgumentList @('autostart','enable')" in script
            assert install._ps_single_quote(native_path) in script
            assert str(exe) not in script
            state["task"] = task_after_repair
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(install.shutil, "which", which)
    monkeypatch.setattr(install.subprocess, "run", run)
    monkeypatch.setattr(install, "_resolved_cua_driver_cmd", lambda: str(exe) if state["installed"] else None)
    monkeypatch.setattr(install, "_cua_driver_contract_status", lambda *args: {"ready": state["installed"]})
    assert not install._cua_driver_install_ready()
    assert install.install_cua_driver() is task_after_repair
    assert install._cua_driver_install_ready() is task_after_repair
    assert sum(install._CUA_INSTALL_PS1_URL in argv[-1] for argv, _ in calls) == int(fresh_install)
    # A Linux guest backend does not depend on a Windows scheduled task.
    monkeypatch.setattr(install, "_resolved_cua_driver_cmd", lambda: "/usr/bin/cua-driver")
    assert install._cua_driver_install_ready()


@pytest.mark.parametrize("failure", ["missing-task", "probe-timeout", "repair-denied", "repair-timeout"])
def test_wsl_autostart_failure_never_reports_success_or_elevates_unattended(
    windows_target, monkeypatch, tmp_path, failure
):
    exe = tmp_path / "cua-driver.exe"
    exe.write_text("driver")
    exe.chmod(0o755)
    calls = []
    monkeypatch.setattr(install, "_resolved_cua_driver_cmd", lambda: str(exe))
    monkeypatch.setattr(install, "_cua_driver_contract_status", lambda *args: {"ready": True})
    monkeypatch.setattr(install.shutil, "which", lambda name: str(exe) if name == str(exe) else name)

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[0] == "schtasks.exe":
            if failure == "probe-timeout":
                raise subprocess.TimeoutExpired(argv, 10)
            return SimpleNamespace(returncode=1)
        if argv[0] == "wslpath":
            return SimpleNamespace(returncode=0, stdout=r"C:\Cua\cua-driver.exe", stderr="")
        assert argv[0] == "powershell.exe"
        assert install._CUA_INSTALL_PS1_URL not in argv[-1], "compatible driver must not be downloaded again"
        if failure == "repair-timeout":
            raise subprocess.TimeoutExpired(argv, 300)
        return SimpleNamespace(returncode=1, stdout="", stderr="UAC denied")

    monkeypatch.setattr(install.subprocess, "run", run)
    assert not install.install_cua_driver(upgrade=True, require_confirmed_update=True)
    assert all(argv[0] == "schtasks.exe" for argv in calls)
    assert not install.install_cua_driver()
'''
f.write_text(s, encoding='utf-8')
f = p / 'tests/hermes_cli/test_install_cua_driver.py'
s = f.read_text(encoding='utf-8')
start = s.index('    def test_autostart_repair_quotes_username_space_path_via_file_path')
before, tail = s[:start], s[start:]
tail = tail.replace('return SimpleNamespace(returncode=1)\n            return SimpleNamespace(returncode=0, stdout="", stderr="")', 'return SimpleNamespace(returncode=0 if len(calls) > 1 else 1)\n            return SimpleNamespace(returncode=0, stdout="", stderr="")', 1)
f.write_text(before + tail, encoding='utf-8')
f = p / 'tests/computer_use/test_cua_target_selection.py'
s = f.read_text(encoding='utf-8').replace('import sys\n', 'import subprocess\nimport sys\n', 1)
s += r'''

@pytest.mark.parametrize("failure", ["timeout", "missing-powershell", "bad-json", "nonzero", "incomplete"])
def test_failed_windows_discovery_recovers_without_restart(monkeypatch, failure):
    from tools.computer_use import cua_backend_driver as driver

    available = [failure != "missing-powershell"]
    monkeypatch.setattr(driver.shutil, "which", lambda name: "powershell.exe" if available[0] else None)
    monkeypatch.setattr(driver, "_wsl_windows_path_to_posix", lambda path: "converted:" + path)
    monkeypatch.setattr(driver, "_cb", lambda: SimpleNamespace(sanitized_cua_driver_env=lambda: {}))
    success = SimpleNamespace(returncode=0, stdout='{"LocalAppData":"C:/Users/A/AppData/Local","UserProfile":"C:/Users/A"}')
    first = {
        "timeout": subprocess.TimeoutExpired("powershell.exe", 5),
        "bad-json": SimpleNamespace(returncode=0, stdout="not JSON"),
        "nonzero": SimpleNamespace(returncode=1, stdout="{}"),
        "incomplete": SimpleNamespace(returncode=0, stdout='{"UserProfile":"C:/Users/A"}'),
    }.get(failure)
    run = MagicMock(side_effect=[first, success] if first is not None else [success])
    monkeypatch.setattr(driver.subprocess, "run", run)
    driver._cached_wsl_windows_install_paths.cache_clear()
    try:
        assert driver._wsl_windows_install_paths() == []
        available[0] = True
        paths = driver._wsl_windows_install_paths()
        assert len(paths) == 2
        calls = run.call_count
        assert driver._wsl_windows_install_paths() == paths
        assert run.call_count == calls
    finally:
        driver._cached_wsl_windows_install_paths.cache_clear()


def test_auto_does_not_probe_windows_installation_or_change_existing_precedence(monkeypatch):
    from tools.computer_use import cua_backend_driver as driver

    monkeypatch.delenv("HERMES_CUA_DRIVER_CMD", raising=False)
    monkeypatch.setattr(driver.shutil, "which", lambda name: "/usr/bin/cua-driver" if name == "cua-driver" else None)
    monkeypatch.setattr(driver, "_wsl_windows_install_paths", MagicMock(side_effect=AssertionError("auto must preserve resolution")))
    with _target_config("auto"):
        assert driver._resolve_cua_driver_selection(runtime_host=("linux", True))[:3] == (
            "auto", "linux", "/usr/bin/cua-driver")
'''
f.write_text(s, encoding='utf-8')
