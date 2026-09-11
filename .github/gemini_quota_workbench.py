"""Fork-only workbench; publish only the verified production/test diff."""
from pathlib import Path
import os
import subprocess
import tempfile

BASE = "bf51fee548ceaa28d2c299a41c0f65066c04c061"
BRANCH = "fix/gemini-model-quota-108656"
TEST = "tests/agent/test_gemini_quota_recovery.py"

TEST_SOURCE = r'''"""Native Gemini quota scope and retry timing across the real recovery boundaries."""
from functools import partial
from types import SimpleNamespace
import time

import httpx
import pytest

from agent.agent_runtime_helpers import extract_api_error_context, recover_with_credential_pool
from agent.credential_pool import CredentialPool, PooledCredential, STATUS_EXHAUSTED, load_pool, _normalize_error_context
from agent.error_classifier import FailoverReason, classify_api_error
from agent.fallback_cooldown import _arm_rate_limit_cooldown
from agent.gemini_native_adapter import GeminiAPIError, GeminiNativeClient, gemini_http_error
from agent.turn_recovery import compute_error_backoff, recover_after_classification
from agent.turn_retry_state import TurnRetryState

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
MODEL = "gemini-test-pro"


def quota_body(*, limit=0, scope="model", delay="3.6787s"):
    violation = {
        "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_input_token_count",
        "quotaId": "GenerateContentInputTokensPerModelPerMinute-FreeTier",
        "quotaDimensions": {"model": MODEL, "location": "global"},
        "quotaValue": str(limit),
    }
    violations = [violation]
    if scope == "mixed":
        violations.append({"quotaMetric": "project_requests", "quotaDimensions": {"project": "offline"}})
    if scope == "unknown":
        violation.pop("quotaDimensions")
    return {"error": {
        "code": 429, "status": "RESOURCE_EXHAUSTED",
        "message": f"Quota exceeded for metric: generate_content_free_tier_input_token_count, limit: {limit}. Please retry in 3.6787s.",
        "details": [
            {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": violations},
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay},
        ],
    }}


def recovery_agent(pool=None):
    agent = SimpleNamespace(
        provider="gemini", model=MODEL, base_url=BASE_URL, _credential_pool=pool,
        _credential_pool_entry_id=None, api_key="offline-key", _fallback_activated=False,
        _primary_runtime={"provider": "gemini", "model": MODEL}, _rate_limit_backoff_count=3,
        _buffer_status=lambda message: None, _emit_status=lambda message: None,
        _client_log_context=lambda: "offline Gemini regression",
    )
    agent._recover_with_credential_pool = partial(recover_with_credential_pool, agent)
    return agent


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("scope,limit", [("model", 0), ("model", 250000), ("mixed", 0), ("unknown", 0)])
def test_quota_scope_survives_native_error_and_pool_recovery(tmp_path, monkeypatch, stream, scope, limit):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    entries = [PooledCredential(
        provider="gemini", id=f"key-{i}", label=f"offline {i}", auth_type="api_key",
        priority=i, source="manual", access_token=f"offline-key-{i}",
    ) for i in range(7)]
    pool = CredentialPool("gemini", entries)
    pool._persist()
    agent = recovery_agent(pool)
    sent_keys = []

    def upstream(request):
        sent_keys.append(request.headers["x-goog-api-key"])
        if f"/models/{MODEL}:" in request.url.path:
            return httpx.Response(429, json=quota_body(limit=limit, scope=scope))
        return httpx.Response(200, json={
            "candidates": [{"content": {"role": "model", "parts": [{"text": "Flash still works"}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 154803, "candidatesTokenCount": 3, "totalTokenCount": 154806},
        })

    for entry in entries:
        agent.api_key, agent._credential_pool_entry_id = entry.runtime_api_key, entry.id
        with GeminiNativeClient(api_key=entry.runtime_api_key, http_client=httpx.Client(transport=httpx.MockTransport(upstream))) as client:
            with pytest.raises(GeminiAPIError) as raised:
                result = client.chat.completions.create(model=MODEL, messages=[{"role": "user", "content": "hello"}], stream=stream)
                if stream:
                    list(result)
            error = raised.value
            classified = classify_api_error(error, provider=agent.provider, model=MODEL)
            if scope != "model":
                assert classified.reason != FailoverReason.upstream_rate_limit
                assert classified.should_rotate_credential
                return
            assert classified.reason == FailoverReason.upstream_rate_limit
            assert not classified.should_rotate_credential
            assert classified.retryable is (limit != 0)
            recovered, _ = agent._recover_with_credential_pool(
                status_code=429, has_retried_429=True, classified_reason=classified.reason,
                error_context=extract_api_error_context(error),
            )
            assert not recovered
            result = client.chat.completions.create(model="gemini-test-flash", messages=[{"role": "user", "content": "hello"}])
            assert result.choices[0].message.content == "Flash still works"
            assert result.usage.prompt_tokens == 154803
            assert sent_keys[-2:] == [entry.runtime_api_key, entry.runtime_api_key]
    # In-memory and persisted pool state stay usable for other models, including after reload.
    assert all(entry.last_status != STATUS_EXHAUSTED for entry in pool.entries())
    reloaded = load_pool("gemini")
    assert reloaded.has_available()
    assert {entry.id for entry in reloaded.entries()} >= {entry.id for entry in entries}
    assert all(entry.last_status != STATUS_EXHAUSTED for entry in reloaded.entries())


@pytest.mark.parametrize("retry_info,message_delay,header,expected", [
    (None, "3.6787", None, 3.6787),
    ("3s", "3.6787", None, 3.6787),
    ("28.91s", "28.91", "2", 28.91),
    ("3s", "3", "30", 30.0),
    ({"seconds": "3", "nanos": 678700000}, "3", None, 3.6787),
    ("NaNs", "25.57", None, 25.57),
    ("-5s", "27.86", "NaN", 27.86),
])
def test_body_retry_floor_reaches_backoff_reset_and_fallback(retry_info, message_delay, header, expected):
    body = quota_body(limit=250000, delay=retry_info)
    body["error"]["message"] = f"A free_tier quota limited this request. Please retry in {message_delay}s."
    if retry_info is None:
        body["error"]["details"].pop()
    response = httpx.Response(429, json=body, headers={} if header is None else {"Retry-After": header})
    error = gemini_http_error(response)
    assert error.retry_after == pytest.approx(expected)
    assert "cannot sustain an agent session" not in str(error)
    assert "free tier is exhausted" not in str(error)
    agent = recovery_agent()
    wait = compute_error_backoff(
        agent, error, retry_count=1, max_retries=3, is_rate_limited=True,
        is_zai_coding_overload=False, base_url=BASE_URL, model=MODEL,
    )
    assert wait >= expected
    before = time.time()
    context = extract_api_error_context(error)
    after = time.time()
    assert before + expected <= context["reset_at"] <= after + expected
    # Both legacy text consumers must also understand Google's fractional 'retry in' wording.
    for parse in (extract_api_error_context, _normalize_error_context):
        raw = RuntimeError(f"Please retry in {message_delay}s") if parse is extract_api_error_context else {"message": f"Please retry in {message_delay}s"}
        before = time.time()
        context = parse(raw)
        after = time.time()
        assert before + float(message_delay) <= context["reset_at"] <= after + float(message_delay)
    classified = classify_api_error(error, provider="gemini", model=MODEL)
    recover_after_classification(
        agent, error, classified, TurnRetryState(), status_code=429,
        error_context=extract_api_error_context(error), messages=[], api_messages=[],
    )
    # Falling back after retries must not convert a provider delay into level-3 / 480s cooldown.
    cooldown = _arm_rate_limit_cooldown(agent, classified.reason)
    assert cooldown is not None and 0 < cooldown <= expected
    # The recorded deadline belongs to the failed model, not another same-provider fallback.
    agent.model = "gemini-test-flash"
    agent._rate_limit_backoff_count = 0
    assert _arm_rate_limit_cooldown(agent, classified.reason) != cooldown
'''

QUOTA_SOURCE = r'''"""Google quota scope and retry hints, shared by native errors and classification."""
from __future__ import annotations

import math
import re
from typing import Any

from agent.retry_utils import parse_retry_after_seconds

_RETRY_IN = re.compile(r"\bretry\s+(?:in|after)\s+(\d+(?:\.\d+)?)\s*s(?:ec(?:ond)?s?)?\b", re.IGNORECASE)
_DURATION = re.compile(r"(\d+(?:\.\d+)?)s")
_QUOTA_LINE = re.compile(
    r"Quota exceeded for metric:\s*[^,\n]+,\s*limit:\s*(\d+(?:\.\d+)?),\s*model:\s*([^\s,;]+)",
    re.IGNORECASE,
)


def _nonnegative_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _duration_seconds(value: Any) -> float | None:
    if isinstance(value, str):
        match = _DURATION.fullmatch(value.strip())
        return _nonnegative_number(match.group(1)) if match else None
    if isinstance(value, dict):
        seconds = _nonnegative_number(value.get("seconds", 0))
        nanos = _nonnegative_number(value.get("nanos", 0))
        if seconds is not None and nanos is not None and seconds.is_integer() and nanos.is_integer() and nanos < 1_000_000_000:
            return seconds + nanos / 1_000_000_000
    return None


def gemini_error_payload(body: dict) -> dict:
    nested = body.get("error")
    return nested if isinstance(nested, dict) else body


def gemini_retry_after_seconds(body: dict, headers: Any = None) -> float | None:
    """Keep the largest valid minimum: Google's prose may be more precise than RetryInfo."""
    payload = gemini_error_payload(body)
    delays = [parse_retry_after_seconds(headers)]
    details = payload.get("details")
    for detail in details if isinstance(details, list) else []:
        if isinstance(detail, dict) and detail.get("@type") == "type.googleapis.com/google.rpc.RetryInfo":
            delays.append(_duration_seconds(detail.get("retryDelay")))
    message = payload.get("message")
    if isinstance(message, str):
        delays.extend(float(match.group(1)) for match in _RETRY_IN.finditer(message))
    valid = [delay for delay in delays if delay is not None and math.isfinite(delay) and delay > 0]
    return max(valid) if valid else None


def gemini_quota_context(body: dict) -> dict:
    """Only exempt the credential when EVERY reported quota violation names a model.

    Missing/malformed/mixed dimensions stay on the existing account-level path.
    A retry hint is not proof that zero allowance will reopen after that delay.
    """
    payload = gemini_error_payload(body)
    message = payload.get("message")
    text_rows = list(_QUOTA_LINE.finditer(message)) if isinstance(message, str) else []
    details = payload.get("details")
    quota_details = [detail for detail in details if isinstance(detail, dict) and detail.get("@type") == "type.googleapis.com/google.rpc.QuotaFailure"] if isinstance(details, list) else []
    models, zero = set(), False
    if quota_details:
        for detail in quota_details:
            violations = detail.get("violations")
            if not isinstance(violations, list) or not violations:
                return {}
            for violation in violations:
                if not isinstance(violation, dict):
                    return {}
                dimensions = violation.get("quotaDimensions")
                model = dimensions.get("model") if isinstance(dimensions, dict) else None
                if not isinstance(model, str) or not model.strip():
                    return {}
                models.add(model.strip())
                zero |= _nonnegative_number(violation.get("quotaValue")) == 0
    elif text_rows and len(text_rows) == len(re.findall(r"Quota exceeded for metric:", message, re.IGNORECASE)):
        models.update(match.group(2) for match in text_rows)
    else:
        return {}
    zero |= any(float(match.group(1)) == 0 for match in text_rows)
    return {"quota_scope": "model", "quota_models": sorted(models), "quota_zero": zero}
'''

CHANGED = {TEST, "agent/gemini_quota.py"}

def replace_once(path, old, new):
    file = Path(path)
    text = file.read_text()
    assert text.count(old) == 1, (path, old[:120], text.count(old))
    file.write_text(text.replace(old, new, 1))
    CHANGED.add(path)


def run_tests(paths, label):
    command = ["bash", "scripts/run_tests.sh", *paths, "-q", "--tb=short"]
    print(f"\n===== {label} =====\n{' '.join(command)}", flush=True)
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    print(result.stdout, flush=True)
    return result

Path(TEST).write_text(TEST_SOURCE)
red = run_tests([TEST], "RED: new behavioral regressions on unmodified main")
if red.returncode == 0 or "AssertionError" not in red.stdout or "ModuleNotFoundError" in red.stdout:
    raise SystemExit("Expected assertion failures on base; refusing to publish an unverified red/green receipt")

Path("agent/gemini_quota.py").write_text(QUOTA_SOURCE)
replace_once("agent/gemini_native_adapter.py", "from agent.gemini_schema import sanitize_gemini_tool_parameters", "from agent.gemini_schema import sanitize_gemini_tool_parameters\nfrom agent.gemini_quota import gemini_quota_context, gemini_retry_after_seconds")
replace_once("agent/gemini_native_adapter.py", '''    "\\n\\nYour Google API key is on the free tier (a few hundred requests/day for Gemini Flash models). "
    "Hermes typically makes 3-10 API calls per user turn, so the free tier is exhausted in a handful of "
    "messages and cannot sustain an agent session. Enable billing on your Google Cloud project and "
    "regenerate the key in a billing-enabled project: https://aistudio.google.com/apikey"''', '''    "\\n\\nGoogle reported a free tier quota limit for this request. Limits differ by model and "
    "quota window; this does not by itself establish that the daily allowance or API key is exhausted. "
    "Check the project's model quotas and billing: https://aistudio.google.com/apikey"''')
replace_once("agent/gemini_native_adapter.py", '"""True when a Gemini 429 message indicates free-tier exhaustion."""', '"""True when a Gemini 429 message identifies a free-tier quota (not its reset window)."""')
replace_once("agent/gemini_native_adapter.py", "retry_after: Optional[float] = None, details: Optional[Dict[str, Any]] = None):", "retry_after: Optional[float] = None, details: Optional[Dict[str, Any]] = None, body: Optional[Dict[str, Any]] = None):")
replace_once("agent/gemini_native_adapter.py", "        self.retry_after, self.details = retry_after, details or {}", "        self.retry_after, self.details = retry_after, details or {}\n        self.body = body or {}")
replace_once("agent/gemini_native_adapter.py", '''    try:
        retry_after: Optional[float] = float(response.headers.get("Retry-After") or response.headers.get("retry-after"))
    except (TypeError, ValueError):
        retry_after = None''', '''    retry_after = gemini_retry_after_seconds(err_obj, response.headers)
    quota_context = gemini_quota_context(err_obj) if status == 429 else {}''')
replace_once("agent/gemini_native_adapter.py", '''    # Users who bypassed the setup wizard (raw GOOGLE_API_KEY in .env) still need to learn the free
    # tier cannot sustain an agent session; a legacy "Standard" key gets the real fix (Google's raw 401 asks for OAuth).''', '''    # Quota scope/window is not a statement about the whole key or daily allowance.
    if quota_context.get("quota_zero"):
        message += "\\n\\nThis model has zero quota allowance for the project; a retry delay does not guarantee access. Choose an available model or check the project's quota tier."''')
replace_once("agent/gemini_native_adapter.py", '''        retry_after=retry_after, details={"status": err_status, "reason": reason, "metadata": metadata, "message": err_message},''', '''        retry_after=retry_after, details={"status": err_status, "reason": reason, "metadata": metadata, "message": err_message, **quota_context},
        body={**err_obj, "retry_after": retry_after},''')

replace_once("agent/error_classifier.py", '# Aggregator\'s upstream model 429 — fallback model, key is healthy', '# Model-scoped upstream 429 — fallback model, key is healthy')
replace_once("agent/error_classifier.py", '''def _status_429(c: _Ctx) -> Verdict:
    # Z.AI/Zhipu''', '''def _status_429(c: _Ctx) -> Verdict:
    if c.provider_slug in {"gemini", "google"}:
        from agent.gemini_quota import gemini_quota_context, gemini_retry_after_seconds

        quota = gemini_quota_context(c.body)
        if quota:
            retry_after = gemini_retry_after_seconds(c.body, c.headers)
            if retry_after is not None:
                quota["retry_after"] = retry_after
            return _v(
                _R.upstream_rate_limit, retryable=not quota["quota_zero"],
                should_fallback=True, error_context=quota,
            )
    # Z.AI/Zhipu''')

for path in ("agent/agent_runtime_helpers.py", "agent/credential_pool.py"):
    replace_once(path, r'retry\s+(?:after\s+)?', r'retry\s+(?:(?:after|in)\s+)?')
replace_once("agent/agent_runtime_helpers.py", '''        # Upstream (e.g. DeepSeek behind OpenRouter) is throttling the aggregator; the credential is
        # healthy. Do not rotate/exhaust; let fallback switch models.''', '''        # The failure is scoped to a model (Gemini QuotaFailure or an aggregator's
        # upstream), not this credential. Do not persist global key exhaustion.''')
replace_once("agent/agent_runtime_helpers.py", '"Upstream aggregator 429 (provider unknown) — skipping "', '"Model-scoped upstream 429 — skipping "')

replace_once("agent/turn_recovery.py", "import logging\n", "import logging\nimport math\n")
replace_once("agent/turn_recovery.py", '''    recovered_with_pool, _retry.has_retried_429 = agent._recover_with_credential_pool(''', '''    from agent.fallback_cooldown import _record_model_quota_retry_deadline

    _record_model_quota_retry_deadline(agent, classified)
    recovered_with_pool, _retry.has_retried_429 = agent._recover_with_credential_pool(''')
replace_once("agent/turn_recovery.py", '''    wait_time = _retry_after if _retry_after is not None else jittered_backoff(retry_count, base_delay=2.0, max_delay=60.0)''', '''    # Native adapters normalize structured provider hints onto the exception. Do not
    # shorten that minimum (or discard its fractional part) with the generic header cap.
    _adapter_retry_after = parse_retry_after_seconds(getattr(api_error, "retry_after", None))
    if _adapter_retry_after is not None and math.isfinite(_adapter_retry_after) and _adapter_retry_after > 0:
        _retry_after = max(_retry_after or 0.0, _adapter_retry_after)
    wait_time = _retry_after if _retry_after is not None else jittered_backoff(retry_count, base_delay=2.0, max_delay=60.0)''')
replace_once("agent/turn_recovery.py", '''    if _should_fallback and agent._fallback_index < len(agent._fallback_chain):''', '''    # A short model-local quota window gets the bounded normal retry budget first.
    # Zero allowance is deliberately excluded: RetryInfo does not make that route usable.
    _quota = classified.error_context
    if (
        _quota.get("quota_scope") == "model" and not _quota.get("quota_zero")
        and 0 < (_quota.get("retry_after") or 0) <= 60 and retry_count < max_retries
    ):
        _should_fallback = False
    if _should_fallback and agent._fallback_index < len(agent._fallback_chain):''')
replace_once("agent/turn_recovery.py", '''    rate limits and any other retryable error (capped at 600s: Anthropic Tier 1 buckets''', '''    rate limits and any other retryable error (generic headers capped at 600s; a
    normalized adapter minimum is never shortened). Anthropic Tier 1 buckets''')

replace_once("agent/fallback_cooldown.py", '''def _arm_rate_limit_cooldown(agent, reason: "FailoverReason | None") -> int | None:''', '''def _record_model_quota_retry_deadline(agent, classified) -> None:
    """Carry only this failed route's minimum into fallback; never a global pool status."""
    agent._model_quota_retry_deadline = None
    quota = classified.error_context
    delay = quota.get("retry_after")
    if quota.get("quota_scope") == "model" and not quota.get("quota_zero") and delay is not None and delay > 0:
        agent._model_quota_retry_deadline = (
            agent.provider, agent.model, time.monotonic() + delay,
        )


def _arm_rate_limit_cooldown(agent, reason: "FailoverReason | None") -> float | None:''')
replace_once("agent/fallback_cooldown.py", '''    backoff_count = getattr(agent, "_rate_limit_backoff_count", 0)''', '''    deadline = getattr(agent, "_model_quota_retry_deadline", None)
    if (
        deadline is not None and reason == FailoverReason.upstream_rate_limit
        and deadline[:2] == (agent.provider, agent.model)
        and agent.model == (agent._primary_runtime or {}).get("model")
    ):
        agent._rate_limited_until = deadline[2]
        agent._rate_limit_backoff_count = 0
        remaining = max(0.0, deadline[2] - time.monotonic())
        logger.info("Model quota retry deadline: cooldown %.3f s for %s", remaining, agent.model)
        return remaining
    backoff_count = getattr(agent, "_rate_limit_backoff_count", 0)''')

# Syntax first, then the regression and neighboring provider/pool/retry suites.
import ast
for path in CHANGED:
    ast.parse(Path(path).read_text(), filename=path)
paths = [TEST, "tests/agent/test_gemini_native_adapter.py", "tests/agent/test_gemini_free_tier_gate.py", "tests/agent/test_gemini_standard_key_guidance.py", "tests/agent/test_error_classifier.py", "tests/agent/test_credential_pool.py", "tests/agent/test_credential_pool_operations.py", "tests/agent/test_credential_pool_sole_cooldown.py", "tests/agent/test_gemini_fast_fallback.py", "tests/agent/test_retry_utils.py", "tests/run_agent/test_provider_fallback.py", "tests/run_agent/test_reset_aware_primary_restore.py", "tests/run_agent/test_fallback_credential_isolation.py"]
paths = [path for path in paths if Path(path).exists()]
green = run_tests(paths, "GREEN: patched regression and neighboring suites")
if green.returncode:
    raise SystemExit(green.returncode)
subprocess.run(["git", "diff", "--check"], check=True)
subprocess.run(["git", "diff", "--stat"], check=True)
subprocess.run(["git", "fetch", "--depth=1", "origin", BASE], check=True)
with tempfile.TemporaryDirectory() as directory:
    env = {**os.environ, "GIT_INDEX_FILE": str(Path(directory) / "index"),
           "GIT_AUTHOR_NAME": "Xipong", "GIT_AUTHOR_EMAIL": "217837358+Xipong@users.noreply.github.com",
           "GIT_COMMITTER_NAME": "Xipong", "GIT_COMMITTER_EMAIL": "217837358+Xipong@users.noreply.github.com"}
    subprocess.run(["git", "read-tree", BASE], env=env, check=True)
    subprocess.run(["git", "add", "--", *sorted(CHANGED)], env=env, check=True)
    tree = subprocess.check_output(["git", "write-tree"], env=env, text=True).strip()
    commit = subprocess.check_output(["git", "commit-tree", tree, "-p", BASE, "-m", "fix(gemini): preserve model quota scope and provider retry deadlines\n\nFixes NousResearch/hermes-agent#108656"], env=env, text=True).strip()
    subprocess.run(["git", "push", "origin", f"{commit}:refs/heads/{BRANCH}"], check=True)
    print(f"VERIFIED_FIX_COMMIT={commit}\nVERIFIED_FIX_BRANCH={BRANCH}", flush=True)
