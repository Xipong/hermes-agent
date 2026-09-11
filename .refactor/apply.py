from __future__ import annotations

import re
from pathlib import Path

ROOT = Path.cwd()
API_PATH = ROOT / "web/src/lib/api.ts"
TYPES_PATH = ROOT / "web/src/lib/api-types.ts"
CONFIG_PATH = ROOT / "cli-config.yaml.example"
CONFIG_DOC_PATH = ROOT / "website/docs/user-guide/configuration.md"

TYPE_TAIL_MARKER = "/** Identity payload returned by ``GET /api/auth/me``"
DASHBOARD_THEME_IMPORT = 'import type { DashboardTheme } from "@/themes/types";\n'


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise AssertionError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def split_api_types() -> set[str]:
    text = API_PATH.read_text(encoding="utf-8")
    marker_index = text.index(TYPE_TAIL_MARKER)
    head = text[:marker_index].rstrip() + "\n"
    tail = text[marker_index:].lstrip()

    exports = re.findall(
        r"^export\s+(?:interface|type)\s+([A-Za-z_$][\w$]*)", tail, re.MULTILINE
    )
    if len(exports) < 100:
        raise AssertionError(f"unexpectedly small API type surface: {len(exports)}")
    non_type_exports = re.findall(
        r"^export\s+(?!interface\b|type\b)([A-Za-z_$][\w$]*)", tail, re.MULTILINE
    )
    if non_type_exports:
        raise AssertionError(f"runtime exports found in API type tail: {non_type_exports}")

    head = replace_once(
        head,
        DASHBOARD_THEME_IMPORT,
        "",
        label="DashboardTheme import",
    )
    anchor = (
        'import {\n'
        '  attemptDashboardTokenReloadOnce,\n'
        '  clearDashboardTokenReloadAttempt,\n'
        '} from "@/lib/dashboard-auth-reload";\n'
    )
    type_import = (
        "import type {\n"
        + "".join(f"  {name},\n" for name in exports)
        + '} from "@/lib/api-types";\n'
    )
    head = replace_once(head, anchor, anchor + type_import, label="api import anchor")
    API_PATH.write_text(head, encoding="utf-8")

    header = (
        'import type { DashboardTheme } from "@/themes/types";\n\n'
        "/**\n"
        " * Data-transfer types used by the dashboard API client and its consumers.\n"
        " * Runtime request, authentication, profile-scoping and WebSocket behavior\n"
        " * remains owned by api.ts. Keep this module type-only.\n"
        " */\n"
    )
    TYPES_PATH.write_text(header + tail, encoding="utf-8")
    return set(exports)


MODULE_MAP = {
    "@/lib/api": "@/lib/api-types",
    "./api": "./api-types",
    "../lib/api": "../lib/api-types",
}
IMPORT_RE = re.compile(
    r"import\s+(?P<declaration_type>type\s+)?\{(?P<body>[^{}]*)\}\s+from\s+"
    r"(?P<quote>['\"])(?P<source>@/lib/api|\./api|\.\./lib/api)(?P=quote)\s*;?",
    re.DOTALL,
)
TYPE_IMPORT_RE_TEMPLATE = (
    r"import\s+type\s+\{(?P<body>[^{}]*)\}\s+from\s+['\"]{source}['\"]\s*;?"
)


def symbol_name(specifier: str) -> str:
    item = specifier.strip()
    if item.startswith("type "):
        item = item[5:].strip()
    return re.split(r"\s+as\s+", item, maxsplit=1)[0].strip()


def rewrite_import_declaration(match: re.Match[str], type_names: set[str]) -> str:
    body = match.group("body")
    specifiers = [part.strip() for part in body.split(",") if part.strip()]
    if not specifiers:
        return match.group(0)
    declaration_is_type = bool(match.group("declaration_type"))
    values: list[str] = []
    types: list[str] = []
    for specifier in specifiers:
        is_type = (
            declaration_is_type
            or specifier.startswith("type ")
            or symbol_name(specifier) in type_names
        )
        if is_type:
            types.append(specifier.removeprefix("type ").strip())
        else:
            values.append(specifier)

    quote = match.group("quote")
    source = match.group("source")
    type_source = MODULE_MAP[source]
    declarations: list[str] = []
    if values:
        declarations.append(
            f"import {{ {', '.join(values)} }} from {quote}{source}{quote};"
        )
    if types:
        declarations.append(
            f"import type {{ {', '.join(types)} }} from {quote}{type_source}{quote};"
        )
    return "\n".join(declarations)


def merge_duplicate_type_imports(text: str, source: str) -> str:
    pattern = re.compile(TYPE_IMPORT_RE_TEMPLATE.format(source=re.escape(source)), re.DOTALL)
    matches = list(pattern.finditer(text))
    if len(matches) <= 1:
        return text
    names: list[str] = []
    for match in matches:
        for part in match.group("body").split(","):
            item = part.strip()
            if item and item not in names:
                names.append(item)
    merged = f'import type {{ {", ".join(names)} }} from "{source}";'
    first = matches[0]
    chunks: list[str] = []
    cursor = 0
    for index, match in enumerate(matches):
        chunks.append(text[cursor : match.start()])
        if index == 0:
            chunks.append(merged)
        cursor = match.end()
    chunks.append(text[cursor:])
    return "".join(chunks)


def rewrite_type_imports(type_names: set[str]) -> list[str]:
    changed: list[str] = []
    candidates = sorted(
        {
            *ROOT.glob("web/**/*.ts"),
            *ROOT.glob("web/**/*.tsx"),
            *ROOT.glob("web/**/*.mts"),
            *ROOT.glob("web/**/*.cts"),
        }
    )
    for path in candidates:
        if "node_modules" in path.parts or path in {API_PATH, TYPES_PATH}:
            continue
        original = path.read_text(encoding="utf-8")
        rewritten = IMPORT_RE.sub(
            lambda match: rewrite_import_declaration(match, type_names), original
        )
        for source in set(MODULE_MAP.values()):
            rewritten = merge_duplicate_type_imports(rewritten, source)
        if rewritten != original:
            path.write_text(rewritten, encoding="utf-8")
            changed.append(str(path.relative_to(ROOT)))
    return changed


ADVANCED_PROVIDER_STUB = """# Advanced provider credentials and request deadlines
# ------------------------------------------------------------------
# Full contracts and worked examples live in:
#   website/docs/integrations/providers.md#command-minted-credentials-key_cmd
#   website/docs/user-guide/configuration.md
# `key_cmd` refreshes one provider credential during a session; it is distinct
# from `secrets.command`, which populates process-level environment variables at
# startup. Explicit CLI API keys still take precedence.
#
# providers:
#   my-gateway:
#     base_url: "https://gateway.internal.example.com/v1"
#     api_mode: chat_completions
#     key_cmd: "my-auth-cli print-token --profile prod"
#     request_timeout_seconds: 300
#     stale_timeout_seconds: 900
#     models:
#       slow-reasoning-model:
#         timeout_seconds: 600
#         stale_timeout_seconds: 1800

"""

UNIFIED_TIMEOUTS_STUB = """# =============================================================================
# Unified Timeouts (operation deadlines)
# =============================================================================
# Override internal operation deadlines by dotted path. Precedence is config,
# then the legacy HERMES_* environment variable, then the built-in default.
# Zero or a negative value disables a bound. See the configuration guide for
# the complete and evolving key list.
#
# timeouts:
#   tools:
#     concurrent_batch: 420
#     sequential_call: 420

"""

OPENROUTER_WORKTREE_STUB = """# =============================================================================
# OpenRouter Routing, Response Caching, and Git Worktree Isolation
# =============================================================================
# Detailed semantics and trade-offs are documented in:
#   website/docs/user-guide/configuration.md
#
# provider_routing:
#   sort: "throughput"                  # price | throughput | latency
#   only: ["anthropic", "google"]
#   ignore: ["deepinfra", "fireworks"]
#   order: ["anthropic", "google"]
#   require_parameters: true
#   data_collection: "deny"             # allow | deny
#   models:
#     "openai/gpt-6-astra":
#       only: ["openai"]
#
# openrouter:
#   response_cache: true
#   response_cache_ttl: 300              # 1-86400 seconds
#
# worktree: false                        # true = always isolate CLI sessions
# worktree_sync: true                    # false = branch from local HEAD

"""


def compact_config_example() -> None:
    text = CONFIG_PATH.read_text(encoding="utf-8")
    provider_start = "# Command-minted credentials (optional): key_cmd"
    unified_start = (
        "# =============================================================================\n"
        "# Unified Timeouts (operation deadlines)"
    )
    openrouter_start = (
        "# =============================================================================\n"
        "# OpenRouter Provider Routing (only applies when using OpenRouter)"
    )
    kanban_start = (
        "# =============================================================================\n"
        "# Kanban Review Dispatch"
    )

    first_start = text.index(provider_start)
    first_end = text.index(unified_start, first_start)
    text = text[:first_start] + ADVANCED_PROVIDER_STUB + text[first_end:]

    timeout_start = text.index(unified_start)
    timeout_end = text.index(openrouter_start, timeout_start)
    text = text[:timeout_start] + UNIFIED_TIMEOUTS_STUB + text[timeout_end:]

    routing_start = text.index(openrouter_start)
    routing_end = text.index(kanban_start, routing_start)
    text = text[:routing_start] + OPENROUTER_WORKTREE_STUB + text[routing_end:]
    CONFIG_PATH.write_text(text, encoding="utf-8")


OPENROUTER_DOC_SECTION = r"""
## Advanced Provider Credentials, Routing, and Deadlines

`cli-config.yaml.example` keeps these less-common options compact so a fresh
configuration remains navigable. This section is the full reference for the
provider, routing, and timeout settings represented by those stubs.

### Command-minted credentials (`key_cmd`)

Enterprise gateways often issue short-lived bearer tokens through SSO/OIDC,
cloud IAM, or an internal auth broker. A token copied into `.env` can expire
while a Hermes session is still running. A named provider can use `key_cmd` to
run a helper that prints a fresh token; Hermes caches it until shortly before
expiry and re-mints it as needed for primary and auxiliary model calls.

The helper must print only the token, either as a bare string or as JSON with an
`access_token` field. JSON may also include `expires_in`. An explicit CLI
`--api-key` still wins over `key_cmd`; otherwise `key_cmd` is preferred over
inline `api_key` and `key_env` for that provider.

```yaml
providers:
  my-gateway:
    base_url: "https://gateway.internal.example.com/v1"
    api_mode: chat_completions
    key_cmd: "my-auth-cli print-token --profile prod"
```

`key_cmd` is intentionally different from `secrets.command`. The latter runs
once at startup and returns a `KEY=VALUE` blob for process-level environment
variables. Use `key_cmd` when one provider credential must refresh during the
session. The [provider integration guide](../integrations/providers.md#command-minted-credentials-key_cmd)
contains additional authentication and provider setup details.

A gateway that exposes several wire protocols can share one credential helper:

```yaml
providers:
  dbx:
    base_url: "https://<workspace>.cloud.databricks.com/ai-gateway/mlflow/v1"
    api_mode: chat_completions
    model: databricks-claude-sonnet-4-6
    key_cmd: "databricks auth token -p MY-PROFILE"
  dbx-gpt:
    base_url: "https://<workspace>.cloud.databricks.com/ai-gateway/openai/v1"
    api_mode: codex_responses
    model: databricks-gpt-5-5
    key_cmd: "databricks auth token -p MY-PROFILE"
  dbx-claude:
    base_url: "https://<workspace>.cloud.databricks.com/ai-gateway/anthropic"
    api_mode: anthropic_messages
    model: databricks-claude-fable-5
    key_cmd: "databricks auth token -p MY-PROFILE"
```

### Provider and model request deadlines

Named providers accept `request_timeout_seconds` for the request deadline and
`stale_timeout_seconds` for the non-streaming no-progress detector. A model
entry can override either with `timeout_seconds` and
`stale_timeout_seconds`. The values apply to the primary client, fallback
clients, and client rebuilds after credential rotation.

```yaml
providers:
  ollama-local:
    request_timeout_seconds: 300
    stale_timeout_seconds: 900
  anthropic:
    request_timeout_seconds: 30
    models:
      claude-opus-4.6:
        timeout_seconds: 600
  openai-codex:
    models:
      gpt-5.4:
        stale_timeout_seconds: 1800
```

When omitted, Hermes retains the legacy defaults (`HERMES_API_TIMEOUT=1800`,
`HERMES_API_CALL_STALE_TIMEOUT=90`, and native Anthropic `900`). The implicit
non-stream stale detector is disabled for local endpoints and can scale upward
for very large contexts. These provider options do not currently configure the
AWS Bedrock boto3 transport.

The root `timeouts:` block is separate: it controls Hermes operation deadlines
such as tool batches rather than provider HTTP calls. Config values take
precedence over their legacy `HERMES_*` environment variables; zero or a
negative value disables the bound.

```yaml
timeouts:
  tools:
    concurrent_batch: 420
    sequential_call: 420
```

### OpenRouter provider routing

`provider_routing` is forwarded to OpenRouter's provider-selection controls.
Flat values apply globally; entries under `models` override only the matching
model and inherit any unspecified flat values.

```yaml
provider_routing:
  sort: "throughput"                  # price | throughput | latency
  only: ["anthropic", "google"]
  ignore: ["deepinfra", "fireworks"]
  order: ["anthropic", "google"]
  require_parameters: true
  data_collection: "deny"             # allow | deny
  models:
    "openai/gpt-6-astra":
      only: ["openai"]
    "anthropic/claude-fable-5.1":
      only: ["anthropic"]
```

### OpenRouter response caching

OpenRouter can cache identical requests at its edge. This is independent of
provider prompt caching. The cache key includes the model, messages, and
request parameters.

```yaml
openrouter:
  response_cache: true
  response_cache_ttl: 300  # 1-86400 seconds
```

For worktree behavior, including remote-tip synchronization and the
`worktree_sync` offline/pinned-base override, see
[Git Worktree Isolation](#git-worktree-isolation).

"""


def extend_configuration_docs() -> None:
    text = CONFIG_DOC_PATH.read_text(encoding="utf-8")
    if "## Advanced Provider Credentials, Routing, and Deadlines" in text:
        raise AssertionError("advanced provider documentation already exists")
    anchor = "## Git Worktree Isolation"
    index = text.index(anchor)
    text = text[:index] + OPENROUTER_DOC_SECTION + text[index:]
    CONFIG_DOC_PATH.write_text(text, encoding="utf-8")


def assert_import_boundaries(type_names: set[str]) -> None:
    if "export interface" in API_PATH.read_text(encoding="utf-8").split(
        "export const api =", 1
    )[-1]:
        raise AssertionError("DTO declarations remain in api.ts after the client")
    if re.search(r"export\s+type\s+\{.*api-types", API_PATH.read_text(encoding="utf-8"), re.S):
        raise AssertionError("api.ts must not re-export api-types")

    for path in sorted({*ROOT.glob("web/**/*.ts"), *ROOT.glob("web/**/*.tsx")}):
        if "node_modules" in path.parts or path == API_PATH:
            continue
        text = path.read_text(encoding="utf-8")
        for match in IMPORT_RE.finditer(text):
            declaration_is_type = bool(match.group("declaration_type"))
            for part in match.group("body").split(","):
                item = part.strip()
                if not item:
                    continue
                if declaration_is_type or item.startswith("type ") or symbol_name(item) in type_names:
                    raise AssertionError(
                        f"type import still points at api.ts: {path.relative_to(ROOT)}: {item}"
                    )


def write_manifests(import_files: list[str]) -> None:
    output = ROOT / "validation-output"
    output.mkdir(exist_ok=True)
    api_files = [
        "web/src/lib/api.ts",
        "web/src/lib/api-types.ts",
        *import_files,
    ]
    config_files = [
        "cli-config.yaml.example",
        "website/docs/user-guide/configuration.md",
    ]
    all_files = list(dict.fromkeys([*api_files, *config_files]))
    (output / "api-files.txt").write_text("\n".join(api_files) + "\n", encoding="utf-8")
    (output / "config-files.txt").write_text("\n".join(config_files) + "\n", encoding="utf-8")
    (output / "changed-files.txt").write_text("\n".join(all_files) + "\n", encoding="utf-8")
    ts_files = [path for path in api_files if path.endswith((".ts", ".tsx", ".mts", ".cts"))]
    (output / "ts-files.txt").write_text("\n".join(ts_files) + "\n", encoding="utf-8")


def main() -> None:
    type_names = split_api_types()
    import_files = rewrite_type_imports(type_names)
    compact_config_example()
    extend_configuration_docs()
    assert_import_boundaries(type_names)
    write_manifests(import_files)
    print("moved DTO exports", len(type_names))
    print("rewrote type-import files", len(import_files))
    for path in [API_PATH, TYPES_PATH, CONFIG_PATH, CONFIG_DOC_PATH]:
        print(path.relative_to(ROOT), len(path.read_text(encoding="utf-8").splitlines()))


if __name__ == "__main__":
    main()
