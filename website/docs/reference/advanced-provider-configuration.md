---
title: Advanced Provider Configuration
sidebar_label: Advanced Provider Configuration
sidebar_position: 90
---

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
[Git Worktree Isolation](/user-guide/configuration#git-worktree-isolation).
