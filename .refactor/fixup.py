from __future__ import annotations

import re
from pathlib import Path

ROOT = Path.cwd()
API = ROOT / "web/src/lib/api.ts"
TYPES = ROOT / "web/src/lib/api-types.ts"
CONFIG = ROOT / "cli-config.yaml.example"
CONFIGURATION = ROOT / "website/docs/user-guide/configuration.md"
REFERENCE = ROOT / "website/docs/reference/advanced-provider-configuration.md"
OUTPUT = ROOT / "validation-output"

DOC_HEADING = "## Advanced Provider Credentials, Routing, and Deadlines"
NEXT_DOC_HEADING = "## Git Worktree Isolation"
CONFIG_START = "# Advanced provider credentials and request deadlines"
CONFIG_END = (
    "# =============================================================================\n"
    "# Kanban Review Dispatch"
)
API_TYPE_IMPORT = re.compile(
    r'import type \{\n(?P<body>.*?)\n\} from "@/lib/api-types";\n', re.DOTALL
)
TYPE_DECLARATION = re.compile(
    r"^(?P<export>export\s+)?(?P<kind>interface|type)\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)\b",
    re.MULTILINE,
)

COMPACT_REFERENCE = """# =============================================================================
# Advanced provider, timeout, OpenRouter, and worktree settings
# =============================================================================
# Full contracts and worked examples:
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
#   models: {"openai/gpt-6-astra": {only: ["openai"]}}
#
# openrouter: {response_cache: true, response_cache_ttl: 300}
# worktree: false                        # true = always isolate CLI sessions
# worktree_sync: true                    # false = branch from local HEAD

"""


def trim_runtime_type_import() -> None:
    api_text = API.read_text(encoding="utf-8")
    match = API_TYPE_IMPORT.search(api_text)
    if match is None:
        raise AssertionError("generated api-types import was not found")
    api_without_import = api_text[: match.start()] + api_text[match.end() :]

    types_text = TYPES.read_text(encoding="utf-8")
    declarations = list(TYPE_DECLARATION.finditer(types_text))
    used = [
        declaration.group("name")
        for declaration in declarations
        if re.search(
            rf"\b{re.escape(declaration.group('name'))}\b", api_without_import
        )
    ]
    if not used:
        raise AssertionError("runtime client did not reference any extracted types")

    for declaration in reversed(declarations):
        name = declaration.group("name")
        if name not in used or declaration.group("export"):
            continue
        start = declaration.start()
        types_text = types_text[:start] + "export " + types_text[start:]

    import_block = (
        "import type {\n"
        + "".join(f"  {name},\n" for name in used)
        + '} from "@/lib/api-types";\n'
    )
    API.write_text(
        api_text[: match.start()] + import_block + api_text[match.end() :],
        encoding="utf-8",
    )
    TYPES.write_text(types_text, encoding="utf-8")
    print("runtime DTO imports", len(used))


def move_inserted_docs_to_topical_file() -> None:
    text = CONFIGURATION.read_text(encoding="utf-8")
    start = text.index(DOC_HEADING)
    end = text.index(NEXT_DOC_HEADING, start)
    section = text[start:end].rstrip() + "\n"
    restored = text[:start] + text[end:]
    CONFIGURATION.write_text(restored, encoding="utf-8")

    section = section.replace(
        "[Git Worktree Isolation](#git-worktree-isolation)",
        "[Git Worktree Isolation](/user-guide/configuration#git-worktree-isolation)",
    )
    frontmatter = """---
title: Advanced Provider Configuration
sidebar_label: Advanced Provider Configuration
sidebar_position: 90
---

"""
    REFERENCE.write_text(frontmatter + section, encoding="utf-8")


def compact_example_reference() -> None:
    text = CONFIG.read_text(encoding="utf-8")
    start = text.index(CONFIG_START)
    end = text.index(CONFIG_END, start)
    CONFIG.write_text(text[:start] + COMPACT_REFERENCE + text[end:], encoding="utf-8")


def replace_manifest_entry(name: str, old: str, new: str) -> None:
    path = OUTPUT / name
    original = path.read_text(encoding="utf-8")
    if old not in original:
        raise AssertionError(f"{old} was not present in {name}")
    entries = [new if entry == old else entry for entry in original.splitlines()]
    path.write_text("\n".join(dict.fromkeys(entries)) + "\n", encoding="utf-8")


def main() -> None:
    trim_runtime_type_import()
    move_inserted_docs_to_topical_file()
    compact_example_reference()
    old = "website/docs/user-guide/configuration.md"
    new = "website/docs/reference/advanced-provider-configuration.md"
    replace_manifest_entry("config-files.txt", old, new)
    replace_manifest_entry("changed-files.txt", old, new)
    print("cli-config.yaml.example", len(CONFIG.read_text(encoding="utf-8").splitlines()))
    print(REFERENCE.relative_to(ROOT), len(REFERENCE.read_text(encoding="utf-8").splitlines()))
    assert CONFIGURATION.read_text(encoding="utf-8").find(DOC_HEADING) == -1


if __name__ == "__main__":
    main()
