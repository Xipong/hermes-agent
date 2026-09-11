"""Review refinements for the fork-only red/green workbench."""
from pathlib import Path

source = Path('.github/gemini_quota_workbench.py').read_text()

def edit(old, new):
    global source
    assert source.count(old) == 1, (old[:120], source.count(old))
    source = source.replace(old, new, 1)

edit('provider="gemini", model=MODEL, base_url=BASE_URL, _credential_pool=pool,', 'provider="gemini", model=MODEL, api_mode="chat_completions", base_url=BASE_URL, _credential_pool=pool,')
edit('from agent.turn_recovery import compute_error_backoff, recover_after_classification', 'from agent.turn_recovery import compute_error_backoff, recover_after_classification, route_classified_error')
edit('import time\n\nimport httpx', 'import time\nfrom datetime import datetime, timezone\n\nimport httpx')
edit('limit: {limit}. Please retry in 3.6787s.', 'limit: {limit}, model: {MODEL}. Please retry in 3.6787s.')
edit('[("model", 0), ("model", 250000), ("mixed", 0), ("unknown", 0)]', '[("model", 0), ("model", 250000), ("text", 0), ("text", 250000), ("mixed", 0), ("unknown", 0), ("malformed", 0), ("auth", 0), ("billing", 0)]')
edit('''            return httpx.Response(429, json=quota_body(limit=limit, scope=scope))''', '''            body = quota_body(limit=limit, scope=scope)
            status = 429
            if scope == "text":
                body["error"]["details"].pop(0)
            elif scope == "malformed":
                body["error"]["details"][0]["violations"] = ["invalid violation"]
            elif scope in {"auth", "billing"}:
                status = 401 if scope == "auth" else 402
                body["error"]["message"] = "Invalid API key" if status == 401 else "Insufficient credits"
            return httpx.Response(status, json=body)''')
edit('''            if scope != "model":
                assert classified.reason != FailoverReason.upstream_rate_limit
                assert classified.should_rotate_credential
                return''', '''            if scope not in {"model", "text"}:
                assert classified.reason != FailoverReason.upstream_rate_limit
                assert classified.should_rotate_credential
                if scope not in {"auth", "billing"}:
                    agent._swap_credential = lambda credential: True
                    agent._recover_with_credential_pool(
                        status_code=429, has_retried_429=True, classified_reason=classified.reason,
                        error_context=extract_api_error_context(error),
                    )
                    assert any(row.last_status == STATUS_EXHAUSTED for row in pool.entries())
                return''')
edit('''            assert not recovered
            result = client.chat.completions.create''', '''            assert not recovered
            # Exercise the actual eager-fallback decision, not a copied policy predicate.
            agent._fallback_index, agent._fallback_chain = 0, [{"provider": "gemini", "model": "gemini-test-flash"}]
            attempts = []
            agent._try_activate_fallback = lambda **kwargs: attempts.append(kwargs) or False
            for retry_count in (1, 3):
                attempts.clear()
                route_classified_error(
                    agent, error, classified, TurnRetryState(), error_msg=str(error),
                    error_context=extract_api_error_context(error), recovered_with_pool=False,
                    base_url=BASE_URL, model=MODEL, messages=[], api_messages=[], system_message=None,
                    active_system_prompt="", conversation_history=[], retry_count=retry_count,
                    max_retries=3, compression_attempts=0, max_compression_attempts=1,
                    api_call_count=retry_count, effective_task_id=None,
                )
                assert bool(attempts) is (limit == 0 or retry_count == 3)
            result = client.chat.completions.create''')
edit('''    ("-5s", "27.86", "NaN", 27.86),''', '''    ("-5s", "27.86", "NaN", 27.86),
    ("750s", "750", None, 750.0),
    ("3s", "3", "Sat, 12 Sep 2026 00:00:30 GMT", 30.0),''')
edit('''def test_body_retry_floor_reaches_backoff_reset_and_fallback(retry_info, message_delay, header, expected):
    body = quota_body''', '''def test_body_retry_floor_reaches_backoff_reset_and_fallback(monkeypatch, retry_info, message_delay, header, expected):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 12, tzinfo=timezone.utc)
    monkeypatch.setattr("agent.retry_utils.datetime", FixedDateTime)
    body = quota_body''')
edit('''    classified = classify_api_error(error, provider="gemini", model=MODEL)
    recover_after_classification(''', '''    classified = classify_api_error(error, provider="gemini", model=MODEL)
    # Native transport semantics also survive a custom/unresolved provider label.
    assert classify_api_error(error, provider="custom-gemini-relay", model=MODEL).reason == classified.reason
    recover_after_classification(''')
# Preserve absent-body behavior for manually constructed GeminiAPIError instances.
edit('self.body = body or {}', 'self.body = body')
# A native error is still native when the user routes it through a custom provider alias.
edit('if c.provider_slug in {"gemini", "google"}:', 'if c.provider_slug in {"gemini", "google"} or c.error_type == "GeminiAPIError":')
# Fix the explanatory docstring without reformatting untouched god files.
edit('''normalized adapter minimum is never shortened). Anthropic Tier 1 buckets''', '''normalized adapter minimum is never shortened). Anthropic Tier 1 buckets''')
# Additional neighbors that exercise the shared functions we changed.
edit('''paths = [path for path in paths if Path(path).exists()]
green = run_tests''', '''for root in (Path("tests/agent"), Path("tests/run_agent")):
    for path in sorted(root.glob("test_*.py")):
        if any(term in path.read_text() for term in (
            "compute_error_backoff", "recover_after_classification", "route_classified_error",
            "_arm_rate_limit_cooldown", "parse_retry_after_seconds",
        )):
            paths.append(str(path))
paths.extend([
    "tests/agent/test_credential_pool_provider_boundary.py",
    "tests/agent/test_credential_pool_unmatched_rotation_bound.py",
    "tests/run_agent/test_24996_fallback_exhaustion_cooldown.py",
    "tests/run_agent/test_credential_pool_interrupt.py",
])
paths = list(dict.fromkeys(path for path in paths if Path(path).exists()))
green = run_tests''')
# Check style on new modules without rewriting unrelated legacy code.
edit('''subprocess.run(["git", "diff", "--check"], check=True)''', '''subprocess.run([".venv/bin/ruff", "check", "agent/gemini_quota.py", TEST, "--select", "E9,F63,F7,F82"], check=True)
subprocess.run(["git", "diff", "--check"], check=True)''')
exec(compile(source, '.github/gemini_quota_workbench.py', 'exec'), {'__name__': '__main__'})
