from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path.cwd()
API = ROOT / "web/src/lib/api.ts"
TYPES = ROOT / "web/src/lib/api-types.ts"
SESSIONS = ROOT / "web/src/pages/SessionsPage.tsx"
SESSION_MESSAGES = ROOT / "web/src/components/SessionMessageList.tsx"
CONFIG = ROOT / "cli-config.yaml.example"
DOC = ROOT / "website/docs/reference/advanced-provider-configuration.md"
OUTPUT = ROOT / "validation-output"

TYPE_TAIL_MARKER = "/** Identity payload returned by ``GET /api/auth/me``"
DASHBOARD_THEME_IMPORT = 'import type { DashboardTheme } from "@/themes/types";\n'
API_IMPORT_ANCHOR = (
    'import {\n'
    '  attemptDashboardTokenReloadOnce,\n'
    '  clearDashboardTokenReloadAttempt,\n'
    '} from "@/lib/dashboard-auth-reload";\n'
)
SESSION_MESSAGES_START = "function ToolCallBlock({"
SESSION_MESSAGES_END = "function SessionRow({"
SESSION_MARKDOWN_IMPORT = 'import { Markdown } from "@/components/Markdown";\n'
SESSION_MESSAGES_IMPORT = (
    'import { MessageList } from "@/components/SessionMessageList";\n'
)
CONFIG_START = "# Command-minted credentials (optional): key_cmd"
CONFIG_END = (
    "# =============================================================================\n"
    "# Kanban Review Dispatch"
)

DECLARATION_RE = re.compile(
    r"^(?P<export>export\s+)?(?P<kind>interface|type)\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)\b",
    re.MULTILINE,
)
IMPORT_RE = re.compile(
    r"^import(?P<declaration_type>[ \t]+type)?[ \t]*\{"
    r"(?P<body>[^}]*)\}[ \t]*from[ \t]*"
    r"(?P<quote>['\"])(?P<source>@/lib/api|\./api|\.\./lib/api)(?P=quote)"
    r"(?P<semi>;?)",
    re.MULTILINE,
)
TYPE_IMPORT_RE = re.compile(
    r"^import[ \t]+type[ \t]*\{(?P<body>[^}]*)\}[ \t]*from[ \t]*"
    r"(?P<quote>['\"])(?P<source>@/lib/api-types|\./api-types|\.\./lib/api-types)(?P=quote)"
    r"(?P<semi>;?)",
    re.MULTILINE,
)
TYPE_SOURCE = {
    "@/lib/api": "@/lib/api-types",
    "./api": "./api-types",
    "../lib/api": "../lib/api-types",
}


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise AssertionError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def imported_name(specifier: str) -> str:
    value = specifier.strip()
    if value.startswith("type "):
        value = value[5:].strip()
    return re.split(r"\s+as\s+", value, maxsplit=1)[0].strip()


def split_specifiers(body: str) -> list[str]:
    if "//" in body or "/*" in body:
        raise AssertionError("commented import specifiers require an AST-preserving move")
    return [item.strip() for item in body.split(",") if item.strip()]


def format_import(
    specifiers: list[str],
    source: str,
    quote: str,
    semi: str,
    *,
    type_only: bool,
    multiline: bool,
) -> str:
    prefix = "import type" if type_only else "import"
    if multiline:
        body = "\n".join(f"  {item}," for item in specifiers)
        return f"{prefix} {{\n{body}\n}} from {quote}{source}{quote}{semi}"
    return f"{prefix} {{ {', '.join(specifiers)} }} from {quote}{source}{quote}{semi}"


def split_api_types() -> set[str]:
    text = API.read_text(encoding="utf-8")
    marker = text.index(TYPE_TAIL_MARKER)
    head = text[:marker].rstrip() + "\n"
    tail = text[marker:].lstrip()

    declarations = list(DECLARATION_RE.finditer(tail))
    exported = {
        match.group("name") for match in declarations if match.group("export")
    }
    if len(exported) < 100:
        raise AssertionError(f"unexpectedly small exported DTO surface: {len(exported)}")
    if re.search(r"^export\s+(?:const|function|class|enum)\b", tail, re.MULTILINE):
        raise AssertionError("runtime export found in the DTO tail")

    head = replace_once(
        head, DASHBOARD_THEME_IMPORT, "", "DashboardTheme import"
    )
    runtime_used = [
        match.group("name")
        for match in declarations
        if re.search(rf"\b{re.escape(match.group('name'))}\b", head)
    ]
    runtime_names = set(runtime_used)

    def export_runtime_helper(match: re.Match[str]) -> str:
        if match.group("name") in runtime_names and not match.group("export"):
            return "export " + match.group(0)
        return match.group(0)

    tail = DECLARATION_RE.sub(export_runtime_helper, tail)
    exported.update(runtime_names)
    type_import = (
        "import type {\n"
        + "".join(f"  {name},\n" for name in runtime_used)
        + '} from "@/lib/api-types";\n'
    )
    head = replace_once(
        head, API_IMPORT_ANCHOR, API_IMPORT_ANCHOR + type_import, "API import anchor"
    )
    API.write_text(head, encoding="utf-8")
    TYPES.write_text(
        'import type { DashboardTheme } from "@/themes/types";\n\n'
        "/**\n"
        " * Data-transfer types shared by the dashboard API client and consumers.\n"
        " * Runtime requests, authentication, profile scoping and WebSocket behavior\n"
        " * remain in api.ts. Keep this module type-only.\n"
        " */\n"
        + tail,
        encoding="utf-8",
    )
    print("extracted exported DTOs", len(exported))
    print("runtime DTO imports", len(runtime_used))
    return exported


def rewrite_import(match: re.Match[str], type_names: set[str]) -> str:
    original = match.group(0)
    source = match.group("source")
    target = TYPE_SOURCE[source]
    quote = match.group("quote")
    semi = match.group("semi")
    declaration_is_type = bool(match.group("declaration_type"))
    specifiers = split_specifiers(match.group("body"))

    if declaration_is_type:
        return original.replace(f"{quote}{source}{quote}", f"{quote}{target}{quote}")

    values: list[str] = []
    types: list[str] = []
    for specifier in specifiers:
        if specifier.startswith("type ") or imported_name(specifier) in type_names:
            types.append(specifier.removeprefix("type ").strip())
        else:
            values.append(specifier)
    if not types:
        return original

    multiline = "\n" in match.group("body")
    parts: list[str] = []
    if values:
        parts.append(
            format_import(
                values,
                source,
                quote,
                semi,
                type_only=False,
                multiline=multiline,
            )
        )
    parts.append(
        format_import(
            types,
            target,
            quote,
            semi,
            type_only=True,
            multiline=multiline,
        )
    )
    return "\n".join(parts)


def merge_type_imports(text: str, source: str) -> str:
    matches = [match for match in TYPE_IMPORT_RE.finditer(text) if match.group("source") == source]
    if len(matches) <= 1:
        return text

    names: list[str] = []
    for match in matches:
        for specifier in split_specifiers(match.group("body")):
            if specifier not in names:
                names.append(specifier)
    first = matches[0]
    replacement = format_import(
        names,
        source,
        first.group("quote"),
        first.group("semi"),
        type_only=True,
        multiline=("\n" in first.group("body") or len(names) > 4),
    )
    for match in reversed(matches[1:]):
        text = text[: match.start()] + text[match.end() :]
    return text[: first.start()] + replacement + text[first.end() :]


def rewrite_consumer_type_imports(type_names: set[str]) -> list[str]:
    changed: list[str] = []
    candidates = sorted(
        {
            *ROOT.glob("web/src/**/*.ts"),
            *ROOT.glob("web/src/**/*.tsx"),
            *ROOT.glob("web/src/**/*.mts"),
            *ROOT.glob("web/src/**/*.cts"),
        }
    )
    for path in candidates:
        if path in {API, TYPES}:
            continue
        original = path.read_text(encoding="utf-8")
        rewritten = IMPORT_RE.sub(lambda match: rewrite_import(match, type_names), original)
        for source in TYPE_SOURCE.values():
            rewritten = merge_type_imports(rewritten, source)
        if rewritten != original:
            path.write_text(rewritten, encoding="utf-8")
            changed.append(str(path.relative_to(ROOT)))
    return changed


def split_session_message_list() -> None:
    text = SESSIONS.read_text(encoding="utf-8")
    start = text.index(SESSION_MESSAGES_START)
    end = text.index(SESSION_MESSAGES_END, start)
    block = text[start:end].rstrip()
    block = replace_once(
        block,
        "function MessageList({",
        "export function MessageList({",
        "MessageList export",
    )
    header = """import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { ListItem } from "@nous-research/ui/ui/components/list-item";

import { Markdown } from "@/components/Markdown";
import { useI18n } from "@/i18n";
import type { SessionMessage } from "@/lib/api-types";
import { timeAgo } from "@/lib/utils";

"""
    SESSION_MESSAGES.write_text(header + block + "\n", encoding="utf-8")
    text = text[:start] + text[end:]
    text = replace_once(
        text,
        SESSION_MARKDOWN_IMPORT,
        SESSION_MESSAGES_IMPORT,
        "SessionsPage message-list import",
    )
    SESSIONS.write_text(text, encoding="utf-8")


def move_advanced_config_reference() -> None:
    text = CONFIG.read_text(encoding="utf-8")
    start = text.index(CONFIG_START)
    end = text.index(CONFIG_END, start)
    moved = text[start:end].rstrip()
    compact = """# Advanced provider, timeout, OpenRouter, and worktree settings
# ------------------------------------------------------------------
# Full contracts and examples, moved verbatim from this file:
#   website/docs/reference/advanced-provider-configuration.md
#
# providers:
#   my-gateway:
#     key_cmd: "my-auth-cli print-token --profile prod"
#     request_timeout_seconds: 300
#     stale_timeout_seconds: 900
#     models:
#       slow-reasoning-model:
#         timeout_seconds: 600
#         stale_timeout_seconds: 1800
#
# timeouts:
#   tools: {concurrent_batch: 420, sequential_call: 420}
#
# provider_routing:
#   sort: "throughput"                  # price | throughput | latency
#   only: ["anthropic", "google"]
#   data_collection: "deny"             # allow | deny
#
# openrouter: {response_cache: true, response_cache_ttl: 300}
# worktree: false                        # true = always isolate CLI sessions
# worktree_sync: true                    # false = branch from local HEAD

"""
    CONFIG.write_text(text[:start] + compact + text[end:], encoding="utf-8")
    DOC.write_text(
        "---\n"
        "title: Advanced Provider Configuration\n"
        "sidebar_label: Advanced Provider Configuration\n"
        "sidebar_position: 90\n"
        "---\n\n"
        "This reference preserves the advanced provider, timeout, OpenRouter, and\n"
        "worktree examples formerly embedded in `cli-config.yaml.example`. The\n"
        "example file now keeps a compact index while this page retains every\n"
        "setting and explanatory comment.\n\n"
        "```yaml\n"
        + moved
        + "\n```\n",
        encoding="utf-8",
    )


def assert_import_boundaries(type_names: set[str]) -> None:
    if "export type {" in API.read_text(encoding="utf-8"):
        raise AssertionError("api.ts must not re-export the extracted DTO module")
    types = TYPES.read_text(encoding="utf-8")
    if re.search(r"^export\s+(?:const|function|class|enum)\b", types, re.MULTILINE):
        raise AssertionError("api-types.ts contains a runtime export")

    for path in sorted({*ROOT.glob("web/src/**/*.ts"), *ROOT.glob("web/src/**/*.tsx")}):
        if path == API:
            continue
        text = path.read_text(encoding="utf-8")
        for match in IMPORT_RE.finditer(text):
            declaration_is_type = bool(match.group("declaration_type"))
            for specifier in split_specifiers(match.group("body")):
                if (
                    declaration_is_type
                    or specifier.startswith("type ")
                    or imported_name(specifier) in type_names
                ):
                    raise AssertionError(
                        f"type import still points at api.ts: {path.relative_to(ROOT)}: {specifier}"
                    )


def git_numstat(paths: list[str]) -> dict[str, tuple[int, int]]:
    output = subprocess.check_output(
        ["git", "diff", "--numstat", "--", *paths], text=True, encoding="utf-8"
    )
    result: dict[str, tuple[int, int]] = {}
    for line in output.splitlines():
        added, deleted, path = line.split("\t", 2)
        result[path] = (int(added), int(deleted))
    return result


def write_manifests(consumers: list[str]) -> None:
    OUTPUT.mkdir(exist_ok=True)
    session_path = str(SESSIONS.relative_to(ROOT))
    message_path = str(SESSION_MESSAGES.relative_to(ROOT))
    api_files = [
        "web/src/lib/api.ts",
        "web/src/lib/api-types.ts",
        message_path,
        *consumers,
    ]
    config_files = [
        "cli-config.yaml.example",
        "website/docs/reference/advanced-provider-configuration.md",
    ]
    changed = list(dict.fromkeys([*api_files, *config_files]))
    for name, entries in {
        "api-files.txt": api_files,
        "config-files.txt": config_files,
        "changed-files.txt": changed,
        "ts-files.txt": api_files,
    }.items():
        (OUTPUT / name).write_text("\n".join(entries) + "\n", encoding="utf-8")

    stats = git_numstat(changed)
    consumer_churn = 0
    for path in consumers:
        added, deleted = stats.get(path, (0, 0))
        churn = added + deleted
        limit = 450 if path == session_path else 40
        if churn > limit:
            raise AssertionError(
                f"unexpected non-import churn in {path}: +{added}/-{deleted}"
            )
        if path != session_path:
            consumer_churn += churn
    if consumer_churn > 500:
        raise AssertionError(f"consumer import churn is too large: {consumer_churn}")
    (OUTPUT / "numstat.txt").write_text(
        "\n".join(f"{a}\t{d}\t{p}" for p, (a, d) in stats.items()) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    type_names = split_api_types()
    consumers = rewrite_consumer_type_imports(type_names)
    split_session_message_list()
    move_advanced_config_reference()
    assert_import_boundaries(type_names)
    write_manifests(consumers)
    for path in [API, TYPES, SESSIONS, SESSION_MESSAGES, CONFIG, DOC]:
        print(path.relative_to(ROOT), len(path.read_text(encoding="utf-8").splitlines()))
    print("consumer type-import files", len(consumers))


if __name__ == "__main__":
    main()
