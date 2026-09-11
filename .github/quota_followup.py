"""Isolated workbench: test the PR head, patch it, publish only verified source/tests."""
from pathlib import Path
import os
import subprocess
import sys
import textwrap

BASE = '706054b207d0331639d9371ed8f36f642aa38125'
TARGET = 'fix/gemini-model-quota-108656'
WORK_BRANCH = 'work/quota-log-followup-108661'
ROOT = Path.cwd()
TREE = Path('/tmp/hermes-quota-followup')
REPORT = []
TEST_PATH = 'tests/agent/test_auxiliary_quota_recovery.py'

TESTS = r'''
"""Log-shaped quota failures through real auxiliary routing and persisted pools."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time

import httpx
import pytest
import yaml

from agent import auxiliary_client as aux
from agent.credential_pool import CredentialPool, PooledCredential, STATUS_EXHAUSTED, load_pool
from agent.error_classifier import FailoverReason, classify_api_error
from agent.gemini_native_adapter import GeminiNativeClient, GeminiAPIError, gemini_http_error

GEMINI = 'https://generativelanguage.googleapis.com/v1beta'
NVIDIA = 'https://integrate.api.nvidia.com/v1'
LIMITED = 'gemini-test-limited'
HEALTHY = 'gemini-test-healthy'
NIM_LIMITED = 'nvidia/test-limited'
NIM_HEALTHY = 'nvidia/test-healthy'


def quota_body(kind='tokens', *, delay=48.100581664, scoped=True):
    metric = ('generate_content_free_tier_requests' if kind == 'requests'
              else 'generate_content_free_tier_input_token_count')
    limit = 0 if kind == 'zero' else 20 if kind == 'requests' else 250000
    message = ('You exceeded your current quota, please check your plan and billing details.\n'
               f'* Quota exceeded for metric: generativelanguage.googleapis.com/{metric}, '
               f'limit: {limit}, model: {LIMITED}\nPlease retry in {delay}s.')
    violations = [{'quotaMetric': metric, 'quotaDimensions': {'model': LIMITED}, 'quotaValue': str(limit)}]
    if kind == 'mixed':
        violations.append({'quotaMetric': 'project_requests', 'quotaDimensions': {'project': 'offline'}})
    details = [{'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': f'{delay}s'}]
    if kind != 'text':
        details.insert(0, {'@type': 'type.googleapis.com/google.rpc.QuotaFailure', 'violations': violations})
    if not scoped:
        # RetryInfo-only responses have no model-scope evidence and no prose delay.
        message = 'You exceeded your current quota, please check your plan and billing details.'
        details = details[-1:]
    return {'error': {'code': 429, 'status': 'RESOURCE_EXHAUSTED', 'message': message, 'details': details}}


def persist_keys(provider):
    entries = [PooledCredential(provider=provider, id=f'{provider}-{i}', label=f'offline-{i}',
               auth_type='api_key', priority=i, source='manual', access_token=f'offline-{provider}-{i}')
               for i in range(4)]
    pool = CredentialPool(provider, entries)
    pool._persist()
    return entries


@pytest.fixture
def routed_wire(tmp_path, monkeypatch):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    (tmp_path / 'config.yaml').write_text(yaml.safe_dump({
        'model': {'provider': 'gemini', 'default': HEALTHY},
        'auxiliary': {'transient_retries': 0, 'moa_reference': {
            'provider': 'gemini', 'model': LIMITED,
            'fallback_chain': [{'provider': 'gemini', 'model': HEALTHY}],
        }},
    }))
    persist_keys('gemini')
    persist_keys('nvidia')
    state = {'kind': 'tokens', 'requests': []}
    lock = threading.Lock()
    clients = []
    aux._reset_aux_unhealthy_cache()

    def upstream(request):
        body = json.loads(request.content)
        is_google = request.url.host == 'generativelanguage.googleapis.com'
        model = request.url.path.split('/models/', 1)[1].split(':', 1)[0] if is_google else body['model']
        key = request.headers.get('x-goog-api-key') or request.headers.get('authorization')
        with lock:
            state['requests'].append((model, key))
        if model == LIMITED:
            return httpx.Response(429, json=quota_body(state['kind']))
        if model == NIM_LIMITED:
            return httpx.Response(429, json={'message': 'ResourceExhausted: Worker local total request limit reached (32/32)'})
        if is_google:
            data = {'candidates': [{'content': {'role': 'model', 'parts': [{'text': 'healthy route response'}]},
                                    'finishReason': 'STOP'}],
                    'usageMetadata': {'promptTokenCount': 84665, 'candidatesTokenCount': 3, 'totalTokenCount': 84668}}
            if ':streamGenerateContent' in request.url.path:
                return httpx.Response(200, text='data: ' + json.dumps(data) + '\n\n', headers={'content-type': 'text/event-stream'})
            return httpx.Response(200, json=data)
        data = {'id': 'offline', 'object': 'chat.completion', 'model': model,
                'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'healthy route response'}, 'finish_reason': 'stop'}]}
        if body.get('stream'):
            chunk = {'id': 'offline', 'object': 'chat.completion.chunk', 'model': model,
                     'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': 'healthy route response'}, 'finish_reason': 'stop'}]}
            return httpx.Response(200, text='data: ' + json.dumps(chunk) + '\n\ndata: [DONE]\n\n', headers={'content-type': 'text/event-stream'})
        return httpx.Response(200, json=data)

    transport = httpx.MockTransport(upstream)
    original_init = GeminiNativeClient.__init__

    def native_init(self, *args, **kwargs):
        client = httpx.Client(transport=transport)
        clients.append(client)
        kwargs['http_client'] = client
        original_init(self, *args, **kwargs)

    def http_client_kwargs(base_url, *, async_mode=False):
        client = httpx.AsyncClient(transport=transport) if async_mode else httpx.Client(transport=transport)
        clients.append(client)
        return {'http_client': client}

    monkeypatch.setattr(GeminiNativeClient, '__init__', native_init)
    monkeypatch.setattr(aux, '_openai_http_client_kwargs', http_client_kwargs)
    yield state, tmp_path
    aux._reset_aux_unhealthy_cache()
    aux._evict_cached_clients('gemini')
    aux._evict_cached_clients('nvidia')
    for client in clients:
        if isinstance(client, httpx.AsyncClient):
            asyncio.run(client.aclose())
        else:
            client.close()


@pytest.mark.parametrize('mode', ['sync', 'async', 'parallel'])
@pytest.mark.parametrize('kind', ['tokens', 'requests', 'zero', 'text', 'worker', 'cross-provider'])
def test_auxiliary_quota_keeps_other_routes_and_credentials_usable(routed_wire, mode, kind):
    state, home = routed_wire
    state['kind'] = kind if kind in {'tokens', 'requests', 'zero', 'text'} else 'tokens'
    provider, model = ('nvidia', NIM_LIMITED) if kind in {'worker', 'cross-provider'} else ('gemini', LIMITED)
    if kind in {'worker', 'cross-provider'}:
        config = yaml.safe_load((home / 'config.yaml').read_text())
        config['auxiliary']['moa_reference']['fallback_chain'] = (
            [{'provider': 'gemini', 'model': LIMITED}, {'provider': 'nvidia', 'model': NIM_HEALTHY}]
            if kind == 'cross-provider' else [{'provider': 'nvidia', 'model': NIM_HEALTHY}])
        (home / 'config.yaml').write_text(yaml.safe_dump(config))

    def invoke(p=provider, m=model):
        kwargs = dict(task='moa_reference', provider=p, model=m,
                      messages=[{'role': 'user', 'content': 'offline recovery check'}], max_tokens=64)
        return asyncio.run(aux.async_call_llm(**kwargs)) if mode == 'async' else aux.call_llm(**kwargs)

    if kind == 'cross-provider':
        # The existing auxiliary candidate policy raises non-auth fallback failures.
        # Both failed routes must remain available on the next call, not get payment bans.
        with pytest.raises(GeminiAPIError):
            invoke()
        assert not aux._is_provider_unhealthy('gemini')
        assert not aux._is_provider_unhealthy('nvidia')
        result = invoke('gemini', LIMITED)
        results, calls = [result], 2
    elif mode == 'parallel':
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _: invoke(), range(4)))
        calls = 4
    else:
        results, calls = [invoke()], 1
    assert all(result.choices[0].message.content == 'healthy route response' for result in results)
    assert not aux._is_provider_unhealthy('gemini')
    assert not aux._is_provider_unhealthy('nvidia')
    # A model quota must not produce even an immediate duplicate call before fallback.
    failed_calls = sum(m == model for m, _ in state['requests'])
    assert failed_calls == (1 if kind == 'cross-provider' else calls)
    for p in ('gemini', 'nvidia'):
        reloaded = load_pool(p)
        assert reloaded.has_available()
        assert all(entry.last_status != STATUS_EXHAUSTED for entry in reloaded.entries())


@pytest.mark.parametrize('kind', ['google-retryinfo', 'google-mixed', 'nvidia-retryafter', 'billing', 'daily', 'auth'])
def test_auxiliary_pool_persists_retry_deadlines_without_losing_real_quota_walls(tmp_path, monkeypatch, kind):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    now = [time.time()]
    monkeypatch.setattr(time, 'time', lambda: now[0])
    provider = 'nvidia' if kind == 'nvidia-retryafter' else 'gemini'
    entries = persist_keys(provider)
    delay = 48.100581664
    if kind.startswith('google'):
        error = gemini_http_error(httpx.Response(429, json=quota_body('mixed' if kind == 'google-mixed' else 'tokens',
                                                                scoped=kind == 'google-mixed')))
    elif kind == 'nvidia-retryafter':
        from openai import RateLimitError
        response = httpx.Response(429, json={'status': 429, 'title': 'Too Many Requests'},
                                  headers={'retry-after': str(delay)}, request=httpx.Request('POST', NVIDIA))
        error = RateLimitError('Too Many Requests', response=response, body={'status': 429, 'title': 'Too Many Requests'})
    else:
        error = Exception({'billing': 'Payment required: insufficient credits', 'daily': 'Daily quota exceeded', 'auth': 'Invalid API key'}[kind])
        error.status_code = {'billing': 402, 'daily': 429, 'auth': 401}[kind]
    temporary = kind in {'google-retryinfo', 'google-mixed', 'nvidia-retryafter'}
    if temporary:
        assert not aux._is_payment_error(error)
        assert aux._is_rate_limit_error(error)
        assert classify_api_error(error, provider=provider).reason == FailoverReason.rate_limit
    else:
        assert aux._is_payment_error(error) is (kind != 'auth')
    first_reset = None
    for entry in entries:
        aux._recover_provider_pool(provider, error, failed_api_key=entry.runtime_api_key)
        persisted = next(row for row in load_pool(provider).entries() if row.id == entry.id)
        assert persisted.last_status == STATUS_EXHAUSTED
        if temporary:
            assert persisted.last_error_reset_at == pytest.approx(now[0] + delay)
            first_reset = first_reset or persisted.last_error_reset_at
        now[0] += 1
    assert not load_pool(provider).has_available()
    if temporary:
        now[0] = first_reset + 0.01
        recovered = load_pool(provider)
        assert recovered.has_available()
        assert recovered.select().id == entries[0].id
        assert sum(row.last_status == STATUS_EXHAUSTED for row in recovered.entries()) == 3
    elif kind in {'billing', 'daily'}:
        now[0] += 61
        assert not load_pool(provider).has_available()
'''


def run(args, *, cwd=TREE, check=True):
    print('+ ' + ' '.join(map(str, args)), flush=True)
    result = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(result.stdout, flush=True)
    REPORT.append('+ ' + ' '.join(map(str, args)) + '\n' + result.stdout)
    if check and result.returncode:
        raise RuntimeError(f'command failed ({result.returncode}): {args}')
    return result


def replace(path, old, new):
    p = TREE / path
    text = p.read_text()
    assert text.count(old) == 1, (path, old[:120], text.count(old))
    p.write_text(text.replace(old, new))


def patch():
    path = 'agent/auxiliary_client.py'
    replace(path, 'from agent.credential_pool import load_pool\n',
            'from agent.credential_pool import load_pool\nfrom agent.error_classifier import FailoverReason, classify_api_error\n')
    replace(path, '''    status = getattr(exc, "status_code", None)
    return status == 402 or (
        status in {403, 404, 429, None} and _contains_any(str(exc).lower(), _PAYMENT_KEYWORDS)
    )''', '''    classified = classify_api_error(exc)
    # Google includes "billing details" even in temporary quota responses; rendered
    # guidance and RESOURCE_EXHAUSTED are not proof of a payment failure.
    if classified.reason in {FailoverReason.rate_limit, FailoverReason.upstream_rate_limit,
                              FailoverReason.overloaded}:
        return False
    status = classified.status_code
    return classified.reason == FailoverReason.billing or status == 402 or (
        status in {403, 404, 429, None} and _contains_any(str(exc).lower(), _PAYMENT_KEYWORDS)
    )''')
    replace(path, '''    # (PR #8023 pattern)
    if type(exc).__name__ == "RateLimitError":
        return True
    if getattr(exc, "status_code", None) != 429:
        return False
    err_lower = str(exc).lower()
    return _contains_any(err_lower, _RATE_LIMIT_KEYWORDS) or not _contains_any(err_lower, _RATE_LIMIT_BILLING_KEYWORDS)''', '''    classified = classify_api_error(exc)
    return classified.reason in {FailoverReason.rate_limit, FailoverReason.upstream_rate_limit} or (
        classified.reason == FailoverReason.overloaded and classified.status_code in {None, 429}
    )''')
    replace(path, '''    normalized = _normalize_aux_provider(provider)
    try:
        pool = load_pool(normalized)
    except Exception as load_exc:''', '''    normalized = _normalize_aux_provider(provider)
    classified = classify_api_error(exc, provider=normalized)
    if classified.reason in {FailoverReason.upstream_rate_limit, FailoverReason.overloaded}:
        # Match the main agent: a model/worker failure cannot exhaust the API key.
        return False
    try:
        pool = load_pool(normalized)
    except Exception as load_exc:''')
    replace(path, '''        error_context: Dict[str, Any] = {"message": str(exc)}
        if status_code is not None:
            error_context["status_code"] = status_code''', '''        from agent.agent_runtime_helpers import extract_api_error_context
        error_context = extract_api_error_context(exc)
        if status_code is not None:
            error_context["status_code"] = status_code''')
    replace(path, '''    if pool_provider and _credential_rung_accepts(first_err):
        recovery_err = first_err
        # Skip the extra retry for clear payment/quota errors — the endpoint won't accept
        # another request with the same exhausted key.
        if _is_rate_limit_error(first_err) and not _is_payment_error(first_err):''', '''    if pool_provider and _credential_rung_accepts(first_err):
        classified = classify_api_error(first_err, provider=pool_provider, model=route.final_model or "")
        if classified.reason in {FailoverReason.upstream_rate_limit, FailoverReason.overloaded}:
            return None, first_err
        from agent.agent_runtime_helpers import extract_api_error_context
        reset_at = extract_api_error_context(first_err).get("reset_at")
        recovery_err = first_err
        # A provider minimum forbids this immediate same-key retry. Rotate eligible
        # credentials or fall back instead; auxiliary tasks must not block on long waits.
        if _is_rate_limit_error(first_err) and not _is_payment_error(first_err) and reset_at is None:''')
    path = 'agent/error_classifier.py'
    replace(path, '''    msg, status = c.msg, c.status_code
    welcome = _nous_welcome_tier(c)''', '''    msg, status = c.msg, c.status_code
    # NIM's worker-local admission counter is shared capacity, not key credit.
    # A generic 429 carries no such scope evidence and keeps the normal policy.
    if status in {None, 429} and "worker local total request limit reached" in msg:
        return _V_OVERLOADED
    welcome = _nous_welcome_tier(c)''')
    path = 'tests/agent/test_auxiliary_client.py'
    replace(path, '''    def test_resource_exhausted_separator_variants_are_payment(self, spelling, status):
        """NIM / gRPC wrappers serialize the quota signal without the space; the fallback gate
        must read every spelling like the literal ``resource exhausted`` (#85649)."""''', '''    def test_worker_capacity_separator_variants_are_not_payment(self, spelling, status):
        """Worker saturation must reach fallback without a provider-wide payment ban."""''')
    replace(path, '''        exc = Exception(f"{spelling}: Worker local total request limit reached (32/32)")
        if status is not None:
            exc.status_code = status
        assert _is_payment_error(exc) is True''', '''        exc = Exception(f"{spelling}: Worker local total request limit reached (32/32)")
        if status is not None:
            exc.status_code = status
        assert _is_payment_error(exc) is False
        assert _is_rate_limit_error(exc) is True''')


def main():
    run(['git', 'fetch', 'origin', TARGET], cwd=ROOT)
    actual = run(['git', 'rev-parse', 'FETCH_HEAD'], cwd=ROOT).stdout.strip()
    assert actual == BASE, f'PR moved to {actual}; refusing to overwrite concurrent changes'
    run(['git', 'worktree', 'add', '--detach', str(TREE), BASE], cwd=ROOT)
    (TREE / '.venv').symlink_to(ROOT / '.venv', target_is_directory=True)
    (TREE / TEST_PATH).write_text(textwrap.dedent(TESTS).lstrip())
    red = run(['bash', 'scripts/run_tests.sh', TEST_PATH, '-q', '--tb=short'], check=False)
    if red.returncode == 0:
        raise RuntimeError('New regression matrix did not reproduce on the existing PR')
    patch()
    files = [TEST_PATH, 'tests/agent/test_gemini_quota_recovery.py',
             'tests/agent/test_auxiliary_client.py', 'tests/agent/test_error_classifier.py',
             'tests/agent/test_credential_pool.py', 'tests/agent/test_gemini_native_adapter.py',
             'tests/agent/test_fallback_cooldown.py', 'tests/agent/test_turn_recovery.py']
    files = [p for p in files if (TREE / p).exists()]
    run(['bash', 'scripts/run_tests.sh', *files, '-q', '--tb=short'])
    run(['git', 'diff', '--check'])
    changed = ['agent/auxiliary_client.py', 'agent/error_classifier.py', 'tests/agent/test_auxiliary_client.py', TEST_PATH]
    run([str(ROOT / '.venv/bin/python'), '-m', 'compileall', '-q', *changed])
    run(['git', 'add', *changed])
    run(['git', 'config', 'user.name', 'Xipong'])
    run(['git', 'config', 'user.email', '217837358+Xipong@users.noreply.github.com'])
    run(['git', 'commit', '-m', 'fix(auxiliary): preserve quota scope and retry deadlines without payment bans'])
    run(['git', 'push', 'origin', f'HEAD:{TARGET}'])
    REPORT.append('PUBLISHED_CLEAN_COMMIT=' + run(['git', 'rev-parse', 'HEAD']).stdout.strip())


try:
    main()
except Exception as exc:
    REPORT.append(f'WORKBENCH_ERROR: {type(exc).__name__}: {exc}')
    raise
finally:
    (ROOT / '.github/quota-result.txt').write_text('\n'.join(REPORT))
    subprocess.run(['git', 'config', 'user.name', 'Xipong'], cwd=ROOT, check=True)
    subprocess.run(['git', 'config', 'user.email', '217837358+Xipong@users.noreply.github.com'], cwd=ROOT, check=True)
    subprocess.run(['git', 'add', '.github/quota-result.txt'], cwd=ROOT, check=True)
    subprocess.run(['git', 'commit', '-m', 'test: record auxiliary quota workbench results'], cwd=ROOT, check=True)
    subprocess.run(['git', 'push', 'origin', f'HEAD:{WORK_BRANCH}'], cwd=ROOT, check=True)
