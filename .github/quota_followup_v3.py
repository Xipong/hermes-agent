"""Final review: narrow the model cooldown guard; preserve non-model billing policy."""
from pathlib import Path
import ast
import subprocess

source = Path('.github/quota_followup_v2.py').read_text()
cut = source.index("\ntry:\n    ns['main']()")
env = {'__file__': str(Path('.github/quota_followup_v2.py').resolve()), '__name__': 'quota_followup_v2'}
exec(compile(source[:cut], env['__file__'], 'exec'), env)
ns, ROOT, TREE, REPORT = env['ns'], env['ROOT'], env['TREE'], env['REPORT']
original_patch, original_run, replace = ns['patch'], ns['run'], ns['replace']

ns['TESTS'] = ns['TESTS'].replace(
    "def test_fallback_model_failure_does_not_extend_primary_quota_deadline(provider, model):",
    "@pytest.mark.parametrize('reason', [FailoverReason.upstream_rate_limit, FailoverReason.rate_limit, FailoverReason.billing])\ndef test_fallback_model_failure_does_not_extend_primary_quota_deadline(provider, model, reason):")
ns['TESTS'] = ns['TESTS'].replace(
    '''    assert _arm_rate_limit_cooldown(agent, FailoverReason.upstream_rate_limit) is None
    assert agent._rate_limited_until == deadline
    assert agent._rate_limit_backoff_count == 2''',
    '''    armed = _arm_rate_limit_cooldown(agent, reason)
    if provider == 'gemini' and reason != FailoverReason.upstream_rate_limit:
        # Ordinary account/credential-wide failures retain the existing policy.
        assert armed is not None
        assert agent._rate_limit_backoff_count == 3
    else:
        assert armed is None
        assert agent._rate_limited_until == deadline
        assert agent._rate_limit_backoff_count == 2''')


def patch():
    original_patch()
    replace('agent/fallback_cooldown.py', '''    primary_model = (agent._primary_runtime or {}).get("model")
    if getattr(agent, "_fallback_activated", False) and not (
        primary_provider and current_provider == primary_provider and agent.model == primary_model
    ):
        return None''', '''    if getattr(agent, "_fallback_activated", False) and not (primary_provider and current_provider == primary_provider):
        return None
    if (
        getattr(agent, "_fallback_activated", False) and reason == FailoverReason.upstream_rate_limit
        and getattr(agent, "model", None) != (agent._primary_runtime or {}).get("model")
    ):
        # Model-scoped failure of a same-provider fallback says nothing about the
        # primary's bucket. Account-wide rate/billing failures retain their policy.
        return None''')
    replace('agent/error_classifier.py', '''    if status in {None, 429} and "worker local total request limit reached" in msg:
        return _V_OVERLOADED''', '''    if status in {None, 429} and "worker local total request limit reached" in msg:
        return _v(_R.overloaded, should_fallback=True)''')
    p = TREE / 'tests/agent/test_error_classifier.py'
    text = p.read_text()
    node = next(n for n in ast.walk(ast.parse(text)) if isinstance(n, ast.FunctionDef)
                and n.name == 'test_resource_exhausted_separator_variants_without_status')
    old = ast.get_source_segment(text, node)
    new = old.replace('test_resource_exhausted_separator_variants_without_status', 'test_worker_capacity_variants_do_not_rotate_credentials').replace(
        'result.reason == FailoverReason.rate_limit', 'result.reason == FailoverReason.overloaded').replace(
        'result.should_rotate_credential is True', 'result.should_rotate_credential is False')
    p.write_text(text.replace(old, new))


def run(args, **kwargs):
    args = list(args)
    if args[:2] == ['git', 'add'] or (len(args) > 2 and args[1:3] == ['-m', 'compileall']):
        args.append('tests/agent/test_error_classifier.py')
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
        line.startswith(('+ ', '=== Summary:', 'WORKBENCH_ERROR:', 'PUBLISHED_CLEAN_COMMIT=', 'FAILED '))
        or ('tests/agent/' in line and ('✗' in line or '✓' in line))
    ))
    (ROOT / '.github/quota-summary.txt').write_text(summary + '\n')
    for args in [
        ['git', 'config', 'user.name', 'Xipong'],
        ['git', 'config', 'user.email', '217837358+Xipong@users.noreply.github.com'],
        ['git', 'add', '.github/quota-result.txt', '.github/quota-summary.txt'],
        ['git', 'commit', '-m', 'test: record reviewed quota recovery regression results'],
        ['git', 'push', 'origin', 'HEAD:work/quota-log-followup-108661'],
    ]:
        subprocess.run(args, cwd=ROOT, check=True)
