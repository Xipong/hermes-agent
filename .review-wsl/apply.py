from pathlib import Path

ROOT = Path.cwd()

def edit(path, old, new):
    p = ROOT / path
    text = p.read_text(encoding='utf-8')
    assert text.count(old) == 1, (path, text.count(old), old[:80])
    p.write_text(text.replace(old, new), encoding='utf-8')

def function(path, name, replacement):
    import ast
    p = ROOT / path
    text = p.read_text(encoding='utf-8')
    node = next(n for n in ast.parse(text).body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name)
    lines = text.splitlines(keepends=True)
    lines[node.lineno-1:node.end_lineno] = [replacement.rstrip() + '\n']
    p.write_text(''.join(lines), encoding='utf-8')

edit('tools/computer_use/tool.py', 'from typing import Any, Callable, Dict, List, Optional, Tuple', 'from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple')
edit('tools/computer_use/tool.py', '\ndef release_computer_use_session(session_id: str) -> bool:', '''
@contextlib.contextmanager
def _backend_for_call(session_id: str = "") -> Iterator[ComputerUseBackend]:
    """Lease a live backend until dispatch completes; never retry an action.

    Lookup is not admission: a target/mode switch or release can retire the
    backend both before lock lookup and while this caller waits for its lock.
    Revalidate the pair AFTER acquiring the call lock. Teardown uses that same
    lock, so it cannot stop an admitted backend until the caller has finished.
    Never wait for a call lock while holding the global cache lock.
    """
    from tools.computer_use.cua_backend_driver import computer_use_selection_identity

    sid = _scoped_sid(session_id)
    while True:
        backend = _get_backend(session_id=session_id)
        with _backend_lock:
            if _backends.get(sid) is not backend:
                continue
            call_lock = _backend_call_locks[sid]
        with call_lock:
            with _backend_lock:
                if (_backends.get(sid) is not backend
                        or _backend_call_locks.get(sid) is not call_lock):
                    continue
                # A queued call can outlive a config change even if no other
                # caller has replaced the cached backend yet.
                if (_backend_permission_modes.get(sid) != _cua_permission_mode(str(session_id or ""))
                        or _backend_selection_identities.get(sid) != computer_use_selection_identity()):
                    continue
            yield backend
            return


def release_computer_use_session(session_id: str) -> bool:''')
edit('tools/computer_use/tool.py', '''    try:
        backend = _get_backend(session_id=session_id)
    except Exception as e:
        return json.dumps({"error": f"computer_use backend unavailable: {e}",
                           "hint": "If the cua-driver binary is missing, run `hermes computer-use install`. "
                                   "If a Python dependency is missing, the error above shows the exact install command."})
    try:
        with _backend_lock:
            call_lock = _backend_call_locks.setdefault(_scoped_sid(session_id), threading.RLock())
        with call_lock:
            return _dispatch(backend, action, args, session_id=session_id or None)
    except Exception as e:
        logger.exception("computer_use %s failed", action)
        return json.dumps({"error": f"{action} failed: {e}"})''', '''    try:
        with _backend_for_call(session_id) as backend:
            try:
                return _dispatch(backend, action, args, session_id=session_id or None)
            except Exception as e:
                logger.exception("computer_use %s failed", action)
                return json.dumps({"error": f"{action} failed: {e}"})
    except Exception as e:
        return json.dumps({"error": f"computer_use backend unavailable: {e}",
                           "hint": "If the cua-driver binary is missing, run `hermes computer-use install`. "
                                   "If a Python dependency is missing, the error above shows the exact install command."})''')
p = ROOT / 'tests/tools/test_computer_use.py'
s = p.read_text(encoding='utf-8')
assert s.count('patch.object(cu_tool, "_get_backend", return_value=') == 4
p.write_text(s.replace('patch.object(cu_tool, "_get_backend", return_value=', 'patch.object(cu_tool, "_new_backend", return_value='), encoding='utf-8')

edit('tools/computer_use/cua_backend_driver.py', '''@functools.lru_cache(maxsize=1)
def _wsl_windows_install_paths() -> List[str]:''', '''class _WslDiscoveryUnavailable(RuntimeError):
    """A transient or incomplete Windows install-location probe."""


@functools.lru_cache(maxsize=1)
def _cached_wsl_windows_install_paths() -> Tuple[str, ...]:''')
edit('tools/computer_use/cua_backend_driver.py', '''    powershell = shutil.which("powershell.exe")
    if not powershell:
        return []
    script =''', '''    powershell = shutil.which("powershell.exe")
    if not powershell:
        raise _WslDiscoveryUnavailable("PowerShell is unavailable through WSL interop")
    script =''')
edit('tools/computer_use/cua_backend_driver.py', '''    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return []

    def clean''', '''    except (OSError, subprocess.SubprocessError, ValueError, TypeError) as exc:
        raise _WslDiscoveryUnavailable("Windows install-location probe failed") from exc

    def clean''')
edit('tools/computer_use/cua_backend_driver.py', '''    local, profile = clean("LocalAppData"), clean("UserProfile")
    windows_paths = ([str(PureWindowsPath(local) / "Programs" / "Cua" / "cua-driver" / "bin" / "cua-driver.exe")]
                     if local else [])
    if profile:
        windows_paths.append(str(PureWindowsPath(profile) / ".local" / "bin" / "cua-driver.exe"))
    return [_wsl_windows_path_to_posix(path) for path in windows_paths]
''', '''    local, profile = clean("LocalAppData"), clean("UserProfile")
    if not local or not profile:
        raise _WslDiscoveryUnavailable("Windows install-location probe returned incomplete paths")
    windows_paths = [
        str(PureWindowsPath(local) / "Programs" / "Cua" / "cua-driver" / "bin" / "cua-driver.exe"),
        str(PureWindowsPath(profile) / ".local" / "bin" / "cua-driver.exe"),
    ]
    return tuple(_wsl_windows_path_to_posix(path) for path in windows_paths)


def _wsl_windows_install_paths() -> List[str]:
    """Cache successful discovery only; a failed interop probe remains retryable."""
    try:
        return list(_cached_wsl_windows_install_paths())
    except _WslDiscoveryUnavailable:
        return []
''')
p = ROOT / 'tests/computer_use/test_cua_target_selection.py'
s = p.read_text(encoding='utf-8')
p.write_text(s.replace('driver._wsl_windows_install_paths.cache_clear()', 'driver._cached_wsl_windows_install_paths.cache_clear()'), encoding='utf-8')

edit('hermes_cli/tools_config_cua.py', '''    return bool(_cua_driver_contract_status().get("ready")) and (
        sys.platform != "win32" or _cua_driver_autostart_registered_windows())''', '''    from tools.computer_use.cua_backend_driver import resolved_cua_driver_platform
    binary = _resolved_cua_driver_cmd()
    return bool(_cua_driver_contract_status(binary).get("ready")) and (
        (sys.platform != "win32" and resolved_cua_driver_platform(binary) != "windows")
        or _cua_driver_autostart_registered_windows())''')
edit('hermes_cli/tools_config_cua.py', '''    if contract.get("ready") and not upgrade:
        _print_success(f"    Windows-host cua-driver is ready: {binary}")
        return True
    if unattended:
        _print_info("    Windows-host installation from WSL requires an explicit computer-use install command.")
        return bool(contract.get("ready"))''', '''    if unattended:
        # Probing is safe; installing/elevating across the OS boundary is not
        # an unattended repair, even when the executable itself is compatible.
        if contract.get("ready") and _cua_driver_autostart_registered_windows():
            return True
        return _fail("    Windows-host setup requires an explicit computer-use install command.",
                     "    Run: hermes computer-use install")
    if contract.get("ready") and not upgrade:
        if not _repair_cua_driver_autostart_windows(binary, verbose=False):
            return _fail("    Windows-host cua-driver is compatible, but autostart repair failed.")
        _print_success(f"    Windows-host cua-driver is ready: {binary}")
        return True''')
edit('hermes_cli/tools_config_cua.py', '''    contract = _cua_driver_contract_status()
    if not contract.get("ready"):
        return _fail("    Windows installer exited, but the selected driver is not ready.",
                     str(contract.get("reason") or computer_use_target_error() or "Run hermes computer-use doctor."))
    _print_success("    Windows-host cua-driver installed and runtime contract verified.")''', '''    from tools.computer_use.cua_backend_driver import _cached_wsl_windows_install_paths
    _cached_wsl_windows_install_paths.cache_clear()
    binary = _resolved_cua_driver_cmd()
    contract = _cua_driver_contract_status(binary)
    if not binary or not contract.get("ready"):
        return _fail("    Windows installer exited, but the selected driver is not ready.",
                     str(contract.get("reason") or computer_use_target_error() or "Run hermes computer-use doctor."))
    if not _repair_cua_driver_autostart_windows(binary, verbose=False):
        return _fail("    Windows-host driver installed, but autostart registration is not ready.")
    _print_success("    Windows-host cua-driver installed; runtime contract and autostart verified.")''')
edit('hermes_cli/tools_config_cua.py', '''def _cua_driver_autostart_registered_windows() -> bool:
    """Return whether the Windows cua-driver scheduled task is registered."""
    if sys.platform != "win32":
        return False''', '''def _windows_host_accessible() -> bool:
    from hermes_constants import is_wsl
    return sys.platform == "win32" or (sys.platform == "linux" and is_wsl())


def _cua_driver_autostart_registered_windows() -> bool:
    """Probe the Windows host task, including when Python runs in WSL."""
    if not _windows_host_accessible():
        return False''')
edit('hermes_cli/tools_config_cua.py', '''    if sys.platform != "win32" or _cua_driver_autostart_registered_windows():
        return True
    binary = shutil.which(driver_cmd)
    if not binary:
        return False
    ps = shutil.which("powershell") or shutil.which("powershell.exe") or "powershell"
    ps_cmd =''', r'''    if not _windows_host_accessible() or _cua_driver_autostart_registered_windows():
        return True
    binary = shutil.which(driver_cmd)
    if not binary:
        return False
    if sys.platform != "win32":
        # PowerShell needs a Windows path, not /mnt/c/... or a POSIX symlink.
        # wslpath honors the configured automount root; never guess a drive.
        wslpath, ps = shutil.which("wslpath"), shutil.which("powershell.exe")
        if not wslpath or not ps:
            return _fail("    WSL autostart repair requires wslpath and powershell.exe.")
        try:
            converted = _run_text([wslpath, "-w", os.path.realpath(binary)], timeout=3,
                                  stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as exc:
            return _fail(f"    Could not translate the Windows driver path: {exc}")
        binary = (converted.stdout or "").strip()
        if (converted.returncode != 0 or not binary or re.search(r"[\x00-\x1f]", binary)
                or not (re.match(r"^[A-Za-z]:[\\/]", binary) or binary.startswith("\\\\"))):
            return _fail("    wslpath did not return an absolute Windows driver path.")
    else:
        ps = shutil.which("powershell") or shutil.which("powershell.exe") or "powershell"
    ps_cmd =''')
edit('hermes_cli/tools_config_cua.py', '''    if result.returncode == 0:
        return True
    _print_warning("    cua-driver autostart registration failed.")''', '''    if result.returncode == 0 and _cua_driver_autostart_registered_windows():
        return True
    _print_warning("    cua-driver autostart registration failed.")''')

edit('apps/desktop/src/app/settings/computer-use-panel.tsx', '''  onConfiguredChange?: () => void
  /** The exact''', '''  onConfiguredChange?: () => void
  /** Invalidate the sibling provider matrix after a target write succeeds. */
  onTargetChange?: () => void
  /** The exact''')
edit('apps/desktop/src/app/settings/computer-use-panel.tsx', "if (platform === 'darwin')", "if (platform === 'darwin' || platform === 'macos')")
edit('apps/desktop/src/app/settings/computer-use-panel.tsx', 'export function ComputerUsePanel({ onConfiguredChange, profile }: ComputerUsePanelProps)', 'export function ComputerUsePanel({ onConfiguredChange, onTargetChange, profile }: ComputerUsePanelProps)')
edit('apps/desktop/src/app/settings/computer-use-panel.tsx', '''        await refresh()
        onConfiguredChange?.()
      } catch (err)''', '''        onTargetChange?.()
        onConfiguredChange?.()
        await refresh()
      } catch (err)''')
edit('apps/desktop/src/app/settings/computer-use-panel.tsx', '[onConfiguredChange, profile, refresh, status?.target]', '[onConfiguredChange, onTargetChange, profile, refresh, status?.target]')
edit('apps/desktop/src/app/skills/index.tsx', '''  const label = toolsetDisplayLabel(toolset)

  return (''', '''  const label = toolsetDisplayLabel(toolset)
  const [computerUseConfigRevision, setComputerUseConfigRevision] = useState(0)

  return (''')
edit('apps/desktop/src/app/skills/index.tsx', '''        <ComputerUsePanel key={profileScopeKey(profile)} onConfiguredChange={onConfiguredChange} profile={profile} />''', '''        <ComputerUsePanel
          key={profileScopeKey(profile)}
          onConfiguredChange={onConfiguredChange}
          onTargetChange={() => void setComputerUseConfigRevision(revision => revision + 1)}
          profile={profile}
        />''')
edit('apps/desktop/src/app/skills/index.tsx', '''        onConfiguredChange={onConfiguredChange}
        profile={profile}
        toolset={toolset.name}''', '''        onConfiguredChange={onConfiguredChange}
        profile={profile}
        refreshKey={toolset.name === 'computer_use' ? computerUseConfigRevision : undefined}
        toolset={toolset.name}''')
edit('apps/desktop/src/app/settings/toolset-config-panel.tsx', '''interface ToolsetConfigPanelProps {
  toolset: string''', '''interface ToolsetConfigPanelProps {
  toolset: string
  /** Refetch backend truth without dropping in-progress provider setup. */
  refreshKey?: number''')
edit('apps/desktop/src/app/settings/toolset-config-panel.tsx', 'export function ToolsetConfigPanel({ toolset, onConfiguredChange, profile }: ToolsetConfigPanelProps)', 'export function ToolsetConfigPanel({ toolset, onConfiguredChange, profile, refreshKey }: ToolsetConfigPanelProps)')
edit('apps/desktop/src/app/settings/toolset-config-panel.tsx', '''  const mountedRef = useRef(true)

  // eslint-disable-next-line''', '''  const mountedRef = useRef(true)
  const configRequestRef = useRef(0)

  // eslint-disable-next-line''')
edit('apps/desktop/src/app/settings/toolset-config-panel.tsx', '''  const refresh = useCallback(async () => {
    setLoading(true)

    try {
      const next = await getToolsetConfig(toolset, profile)
      setCfg(next)''', '''  const refresh = useCallback(async () => {
    const request = ++configRequestRef.current

    try {
      const next = await getToolsetConfig(toolset, profile)

      if (!mountedRef.current || request !== configRequestRef.current) {
        return
      }

      setCfg(next)''')
edit('apps/desktop/src/app/settings/toolset-config-panel.tsx', '''    } catch (err) {
      notifyError(err, copy.failedLoad)
    } finally {
      setLoading(false)
    }
  }, [copy.failedLoad, toolset, profile])

  useEffect(() => {
    void refresh()
  }, [refresh])''', '''    } catch (err) {
      if (mountedRef.current && request === configRequestRef.current) {
        notifyError(err, copy.failedLoad)
      }
    } finally {
      if (mountedRef.current && request === configRequestRef.current) {
        setLoading(false)
      }
    }
  }, [copy.failedLoad, toolset, profile])

  // A scope change clears foreign data. Same-scope refreshes keep the provider
  // tree mounted, especially PostSetupRunner's live action and polling loop.
  // eslint-disable-next-line no-restricted-syntax -- invalidate requests from the old config scope
  useEffect(() => {
    setCfg(null)
    setLoading(true)

    return () => {
      configRequestRef.current += 1
    }
  }, [toolset, profile])

  useEffect(() => {
    void refresh()
  }, [refresh, refreshKey])''')
edit('apps/desktop/src/i18n/en.ts', 'Uses the existing resolution: the Windows host through WSL when available, otherwise this Linux guest.', 'Keeps the existing driver resolution. Select Windows host to discover its Windows installation explicitly.')
for locale, new in [('zh.ts', '沿用现有驱动解析方式。若要明确查找 Windows 中的安装，请选择 Windows 主机。'), ('zh-hant.ts', '沿用現有驅動程式解析方式。若要明確尋找 Windows 中的安裝，請選擇 Windows 主機。')]:
    import re
    p = ROOT / 'apps/desktop/src/i18n' / locale
    text = p.read_text(encoding='utf-8')
    text, count = re.subn(r"(targetAutomaticDescription:\s*)'[^']*'", lambda match: match[1] + repr(new), text)
    assert count == 1
    p.write_text(text, encoding='utf-8')
