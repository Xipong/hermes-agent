"""Fork-only RED/GREEN validation for the PR #107713 authority regression."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path.cwd()
INPUT = Path(__file__).resolve().parents[1]
PATCHER = INPUT.parent / "patch-input" / ".mcp-regression" / "apply.py"
OUT = ROOT / "validation-output"
OUT.mkdir(exist_ok=True)

PYTHON_CHANGED = [
    "acp_adapter/server.py",
    "hermes_cli/mcp_catalog.py",
    "hermes_cli/mcp_config.py",
    "hermes_cli/subcommands/mcp.py",
    "hermes_cli/web_server_mcp.py",
    "tests/hermes_cli/test_mcp_network_surfaces.py",
    "tests/tools/test_mcp_network_oauth.py",
    "tests/tools/test_mcp_windows.py",
    "tests/tools/test_mcp_windows_policy.py",
    "tools/mcp_oauth_manager.py",
    "tools/mcp_schema_cache.py",
    "tools/mcp_tool_server_run.py",
    "tools/mcp_tool_transport.py",
    "tools/mcp_windows.py",
]
TS_CHANGED = [
    "apps/desktop/src/api/mcp-network.test.ts",
    "apps/desktop/src/api/mcp.ts",
    "apps/desktop/src/lib/mcp-probe-cache.test.ts",
    "apps/desktop/src/lib/mcp-probe-cache.ts",
    "web/src/components/McpNetworkFields.tsx",
    "web/src/lib/mcp-network.test.ts",
    "web/src/lib/mcp-server-create.test.ts",
    "web/src/lib/mcp-server-create.ts",
]


def run(label: str, argv: list[str], *, cwd: Path = ROOT) -> int:
    env = {**os.environ, "HERMES_TEST_FILE_RETRIES": "0", "NO_COLOR": "1"}
    log_path = OUT / f"{label}.log"
    print(label, argv, flush=True)
    with log_path.open("w", encoding="utf-8") as log:
        result = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=900,
            check=False,
        )
    print(log_path.read_text(encoding="utf-8", errors="replace")[-18000:], flush=True)
    return result.returncode


def apply_patch(*, tests_only: bool = False) -> None:
    command = [sys.executable, str(PATCHER)]
    if tests_only:
        command.append("--tests-only")
    subprocess.run(command, check=True)


def reset() -> None:
    subprocess.run(["git", "reset", "--hard", "HEAD"], check=True)


def update_existing_web_expectations() -> None:
    """New structured entries explicitly persist auto; update old exact-object tests."""
    path = ROOT / "web/src/lib/mcp-server-create.test.ts"
    text = path.read_text(encoding="utf-8")
    replacements = {
        '      url: "https://mcp.linear.app/mcp",\n      auth:': (
            '      url: "https://mcp.linear.app/mcp",\n      network: "auto",\n      auth:'
        ),
        '      url: "https://example.com/mcp",\n      auth: "oauth",': (
            '      url: "https://example.com/mcp",\n      network: "auto",\n      auth: "oauth",'
        ),
        '      name: "public",\n      url: "https://example.com/mcp",\n    });': (
            '      name: "public",\n      url: "https://example.com/mcp",\n'
            '      network: "auto",\n    });'
        ),
    }
    for old, new in replacements.items():
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")


def format_python() -> dict[str, int]:
    results = {
        "ruff-format-write": run(
            "ruff-format-write", ["uv", "run", "--no-sync", "ruff", "format", *PYTHON_CHANGED]
        )
    }
    results["ruff-format-check"] = run(
        "ruff-format-check",
        ["uv", "run", "--no-sync", "ruff", "format", "--check", *PYTHON_CHANGED],
    )
    results["ruff"] = run(
        "ruff", ["uv", "run", "--no-sync", "ruff", "check", *PYTHON_CHANGED]
    )
    return results


def format_frontend() -> dict[str, int]:
    results = {
        "prettier-write": run(
            "prettier-write",
            ["node", "node_modules/prettier/bin/prettier.cjs", "--write", *TS_CHANGED],
        ),
        "eslint-fix": run(
            "eslint-fix",
            ["node", "node_modules/eslint/bin/eslint.js", "--fix", *TS_CHANGED],
        ),
    }
    results["prettier-check"] = run(
        "prettier-check",
        ["node", "node_modules/prettier/bin/prettier.cjs", "--check", *TS_CHANGED],
    )
    results["eslint-check"] = run(
        "eslint-check",
        [
            "node",
            "node_modules/eslint/bin/eslint.js",
            "--max-warnings",
            "0",
            *TS_CHANGED,
        ],
    )
    return results


mode = sys.argv[1]
results: dict[str, int] = {}
bash = (
    str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git/bin/bash.exe")
    if sys.platform == "win32"
    else "bash"
)
pytest = [bash, "scripts/run_tests.sh", "-j", "4", "--file-timeout", "180"]

if mode == "python":
    apply_patch(tests_only=True)
    red_tests = [
        "tests/hermes_cli/test_mcp_network_surfaces.py::test_disk_schema_cache_cannot_replay_another_networks_tools",
    ]
    if sys.platform != "win32":
        red_tests += [
            "tests/tools/test_mcp_windows_policy.py::test_wsl_legacy_omission_stays_local_and_explicit_auto_or_windows_can_bridge",
            "tests/tools/test_mcp_windows.py::test_legacy_omission_never_opens_windows_bridge_or_sends_authorization",
            "tests/tools/test_mcp_network_oauth.py::test_legacy_omitted_network_device_oauth_sends_nothing_to_windows_canary",
        ]
    results["red"] = run("red", pytest + red_tests + ["-q", "--tb=short"])
    reset()
    apply_patch()
    update_existing_web_expectations()
    results.update(format_python())

    selection = [
        "tests/tools/test_mcp_windows.py",
        "tests/tools/test_mcp_windows_policy.py",
        "tests/tools/test_mcp_network_oauth.py",
        "tests/hermes_cli/test_mcp_network_surfaces.py",
        "tests/tools/test_mcp_preflight_content_type.py",
        "tests/tools/test_mcp_sse_transport.py",
        "tests/tools/test_mcp_oauth_manager.py",
        "tests/tools/test_mcp_device_flow.py",
        "tests/hermes_cli/test_mcp_config.py",
        "tests/hermes_cli/test_mcp_catalog.py",
        "tests/hermes_cli/test_agent_import.py",
        "tests/acp_adapter/test_acp_mcp_discovery.py",
    ]
    if sys.platform != "win32":
        selection.append("tests/tools/test_mcp_schema_cache.py")
    results["green"] = run("green", pytest + selection + ["-q", "--tb=short"])
elif mode == "ui":
    apply_patch(tests_only=True)
    results["red-desktop"] = run(
        "red-desktop",
        [
            "node",
            "../../node_modules/vitest/vitest.mjs",
            "run",
            "--project",
            "ui",
            "src/api/mcp-network.test.ts",
            "src/lib/mcp-probe-cache.test.ts",
        ],
        cwd=ROOT / "apps/desktop",
    )
    results["red-web"] = run(
        "red-web",
        ["node", "../node_modules/vitest/vitest.mjs", "run", "src/lib/mcp-network.test.ts"],
        cwd=ROOT / "web",
    )
    reset()
    apply_patch()
    update_existing_web_expectations()
    results.update(format_python())
    results.update(format_frontend())

    results["green-desktop"] = run(
        "green-desktop",
        [
            "node",
            "../../node_modules/vitest/vitest.mjs",
            "run",
            "--project",
            "ui",
            "src/api",
            "src/lib/mcp-probe-cache.test.ts",
            "src/lib/mcp-import.test.ts",
            "src/lib/mcp-servers.test.ts",
        ],
        cwd=ROOT / "apps/desktop",
    )
    results["green-web"] = run(
        "green-web",
        [
            "node",
            "../node_modules/vitest/vitest.mjs",
            "run",
            "src/lib/mcp-network.test.ts",
            "src/lib/mcp-server-create.test.ts",
            "src/lib/mcp-oauth.test.ts",
        ],
        cwd=ROOT / "web",
    )
    results["desktop-typecheck"] = run(
        "desktop-typecheck",
        ["node", "node_modules/typescript/bin/tsc", "-p", "apps/desktop", "--noEmit"],
    )
    results["web-typecheck"] = run(
        "web-typecheck",
        ["node", "node_modules/typescript/bin/tsc", "-p", "web", "--noEmit"],
    )
else:
    raise ValueError(mode)

results["diff-check"] = run("diff-check", ["git", "diff", "--check"])
(OUT / "candidate.patch").write_bytes(subprocess.check_output(["git", "diff", "--binary"]))
(OUT / "python.patch").write_bytes(
    subprocess.check_output(["git", "diff", "--binary", "--", "*.py"])
)
(OUT / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
(OUT / "stat.txt").write_text(
    subprocess.check_output(["git", "diff", "--stat"], text=True), encoding="utf-8"
)
print(results, flush=True)
assert all(value != 0 for key, value in results.items() if key.startswith("red")), results
assert all(value == 0 for key, value in results.items() if not key.startswith("red")), results
