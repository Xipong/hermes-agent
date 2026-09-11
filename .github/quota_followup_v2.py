"""Expanded verification of the log follow-up; workbench files never enter the PR."""
from pathlib import Path
import ast
import re
import subprocess

source = Path('.github/quota_followup.py').read_text()
ns = {'__file__': str(Path('.github/quota_followup.py').resolve()), '__name__': 'quota_workbench'}
exec(compile(source[:source.index('\ntry:\n    main()')], ns['__file__'], 'exec'), ns)
ROOT, TREE, REPORT = ns['ROOT'], ns['TREE'], ns['REPORT']
replace, original_patch, original_run = ns['replace'], ns['patch'], ns['run']

ns['TESTS'] = ns['TESTS'].replace('def persist_keys(provider):', 'def persist_keys(provider, count=4):').replace(
    'for i in range(4)]', 'for i in range(count)]').replace(
    "@pytest.mark.parametrize('kind', ['google-retryinfo'", "@pytest.mark.parametrize('count', [1, 4])\n@pytest.mark.parametrize('kind', ['google-retryinfo'").replace(
    'def test_auxiliary_pool_persists_retry_deadlines_without_losing_real_quota_walls(tmp_path, monkeypatch, kind):',
    'def test_auxiliary_pool_persists_retry_deadlines_without_losing_real_quota_walls(tmp_path, monkeypatch, kind, count):').replace(
    'entries = persist_keys(provider)', 'entries = persist_keys(provider, count)').replace(
    'pytest.approx(now[0] + delay)', 'pytest.approx(now[0] + delay, rel=0, abs=0.001)').replace(
    'for row in recovered.entries()) == 3', 'for row in recovered.entries()) == count - 1')
ns['TESTS'] += '''

@pytest.mark.parametrize('provider,model', [('gemini', HEALTHY), ('nvidia', NIM_HEALTHY)])
def test_fallback_model_failure_does_not_extend_primary_quota_deadline(provider, model):
    from types import SimpleNamespace
    from agent.fallback_cooldown import _arm_rate_limit_cooldown
    deadline = time.monotonic() + 48.100581664
    agent = SimpleNamespace(
        provider=provider, model=model, _fallback_activated=True,
        _primary_runtime={'provider': 'gemini', 'model': LIMITED},
        _model_quota_retry_deadline=(provider, model, time.monotonic() + 300),
        _rate_limited_until=deadline, _rate_limit_backoff_count=2,
    )
    assert _arm_rate_limit_cooldown(agent, FailoverReason.upstream_rate_limit) is None
    assert agent._rate_limited_until == deadline
    assert agent._rate_limit_backoff_count == 2
'''


def patch():
    original_patch()
    path = 'agent/auxiliary_client.py'
    replace(path, '''    """Payment/credit/quota exhaustion: HTTP 402, or a billing/quota body on 403/404/429/no-status."""''',
            '''    """Shared billing/throttle verdicts, with legacy plan-access wording as a fallback."""''')
    replace(path, '''    """429 rate limit (not billing/quota, which _is_payment_error owns).

    OpenAI's RateLimitError may omit .status_code — matched by class name. A generic 429 without
    billing keywords counts as a rate limit.
    """''', '''    """Shared quota/capacity verdict, never inferred from payment-looking guidance."""''')
    replace(path, '''# Billing-body markers (credit exhaustion wrapped in 402/403/404/429 bodies), plus daily/weekly quota
# exhaustion (functionally credit exhaustion; "resource exhausted" is the Vertex/gRPC quota phrasing —
# also serialized by SDK wrappers and NIM as RESOURCE_EXHAUSTED / ResourceExhausted / resource-exhausted).''',
            '''# Legacy access/plan messages. The shared classifier's rate/capacity verdict
# takes precedence: generic quota wording must never arm a payment health ban.''')
    p = TREE / path
    text = p.read_text()
    lines = text.splitlines(keepends=True)
    for node in sorted(ast.parse(text).body, key=lambda n: n.lineno, reverse=True):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in {
                '_RATE_LIMIT_KEYWORDS', '_RATE_LIMIT_BILLING_KEYWORDS'} for t in node.targets):
            del lines[node.lineno-1:node.end_lineno]
    p.write_text(''.join(lines))
    replace(path, '''            error_context=error_context, api_key_hint=failed_api_key or None,
        )''', '''            error_context=error_context, api_key_hint=failed_api_key or None,
            failure_reason=("billing_unverified" if classified.billing_unverified else classified.reason.value),
        )''')
    # This existing fixture was named a rate-limit retry but supplied the ambiguous
    # usage-wall wording the main classifier deliberately treats as billing.
    replace('tests/agent/test_auxiliary_client.py', '''    def test_call_llm_rotates_explicit_codex_pool_on_429(self):
        rate_err = Exception("usage limit reached")''', '''    def test_call_llm_rotates_explicit_codex_pool_on_429(self):
        rate_err = Exception("Rate limit exceeded")''')
    replace('agent/fallback_cooldown.py', '''    if getattr(agent, "_fallback_activated", False) and not (primary_provider and current_provider == primary_provider):
        return None''', '''    primary_model = (agent._primary_runtime or {}).get("model")
    if getattr(agent, "_fallback_activated", False) and not (
        primary_provider and current_provider == primary_provider and agent.model == primary_model
    ):
        return None''')


def run(args, **kwargs):
    args = list(args)
    if args[:3] == ['bash', 'scripts/run_tests.sh', ns['TEST_PATH']] and len([a for a in args if a.endswith('.py')]) > 1:
        patterns = ['test_auxiliary_client*.py', 'test_auxiliary_*fallback*.py',
                    'test_*credential_pool*.py', 'test_error_classif*.py', 'test_gemini*.py',
                    'test_*fallback_cooldown*.py', 'test_rate_limit*.py']
        extra = sorted({str(p.relative_to(TREE)) for pattern in patterns
                        for p in (TREE / 'tests/agent').glob(pattern)} - set(args))
        args[2:2] = extra
    if args[:2] == ['git', 'add'] or (len(args) > 2 and args[1:3] == ['-m', 'compileall']):
        args.append('agent/fallback_cooldown.py')
    if args[:2] == ['git', 'commit']:
        original_run([str(ROOT / '.venv/bin/python'), '-m', 'ruff', 'check',
                      '--select', 'E9,F821,F822,F823', 'agent/auxiliary_client.py',
                      'agent/error_classifier.py', 'agent/fallback_cooldown.py', ns['TEST_PATH']])
    return original_run(args, **kwargs)


ns['patch'], ns['run'] = patch, run
try:
    ns['main']()
except Exception as exc:
    REPORT.append(f'WORKBENCH_ERROR: {type(exc).__name__}: {exc}')
    raise
finally:
    text = '\n'.join(REPORT)
    (ROOT / '.github/quota-result.txt').write_text(text)
    summary = '\n'.join(line for line in text.splitlines() if (
        line.startswith(('+ ', '=== Summary:', 'WORKBENCH_ERROR:', 'PUBLISHED_CLEAN_COMMIT=', 'FAILED ', 'E   '))
        or ('tests/agent/' in line and ('✗' in line or '✓' in line))
    ))
    (ROOT / '.github/quota-summary.txt').write_text(summary + '\n')
    for args in [
        ['git', 'config', 'user.name', 'Xipong'],
        ['git', 'config', 'user.email', '217837358+Xipong@users.noreply.github.com'],
        ['git', 'add', '.github/quota-result.txt', '.github/quota-summary.txt'],
        ['git', 'commit', '-m', 'test: record expanded auxiliary quota workbench results'],
        ['git', 'push', 'origin', 'HEAD:work/quota-log-followup-108661'],
    ]:
        subprocess.run(args, cwd=ROOT, check=True)
