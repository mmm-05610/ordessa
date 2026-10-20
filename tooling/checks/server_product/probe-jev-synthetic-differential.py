"""At most five native synthetic requests; no Engineering Work or real DID.

One variable per comparison: nesting, data length, or the fixed long-context
header. A definite constraint, refusal, or unresolved transport result stops it.
Raw error bodies and credentials are never persisted or printed.
"""
import argparse
import asyncio
import hashlib
import importlib.util
import json
import logging
from pathlib import Path
import re
import time

import httpx2
from typesafe_sdk import AsyncTypeSafeClient, Choice, RetryPolicy
from ordessa_server.composition.temporary_process_capability import ExistingOpenCodeInput

ROOT = Path(__file__).resolve().parents[3]
BASE = 'https://opencode.ai/inference/systemone'
MODEL = 'jev-1.13-free'
LONG_HEADER = 'TypeSafe-Danger-Zone-Long-Context'
FIELDS = frozenset(('error errors message code type status detail details loc msg '
    'limit max max_tokens token_count input_tokens actual_tokens maximum length '
    'max_length context per_request_context per_question_context param name reason error_code error_type').split())
CODES = frozenset(('max_tokens_exceeded context_length_exceeded invalid_request_error '
    'invalid_api_key authentication_error permission_denied model_not_found '
    'request_too_large input_too_long api_error BadRequestError').split())
TERMS = frozenset(('context token tokens limit limits exceeded exceeds maximum minimum '
    'length characters character bytes size state input output request body too large long '
    'invalid missing required field fields schema json format nesting depth string object '
    'array list dict questions question criteria choice choices options option number count '
    'key api unauthorized authentication permission denied model not found unsupported '
    'provider free subscription balance quota encoding compression gzip zstd header headers '
    'value expected allowed only at least most reason error worker exception failed').split())


def project_error(response, key, marker):
    """Inspect locally; emit fixed classifications and safe numeric limits only."""
    raw = response.content
    text = raw[:65536].decode('utf-8', errors='replace')
    key_echo = bool(key and key in text)
    text = text.replace(key, '<redacted>') if key else text
    suspicious = bool(re.search(r'(?i)(?:bearer\s+|sk-)[A-Za-z0-9_-]{8,}', text))
    text = re.sub(r'(?i)(?:bearer\s+|sk-)[A-Za-z0-9_-]{8,}', '<redacted>', text)
    content_type = response.headers.get('content-type', '').split(';', 1)[0].strip().lower()
    if content_type not in {'application/json', 'application/problem+json', 'text/plain', 'text/html'}:
        content_type = 'other'
    try:
        body = json.loads(text)
    except (ValueError, TypeError):
        body = None
    paths = []

    def inspect(value, prefix='', level=0):
        if type(value) is dict and level < 3:
            for field, child in list(value.items())[:32]:
                if field in FIELDS:
                    path = prefix + field
                    paths.append(path)
                    inspect(child, path + '.', level + 1)
        elif type(value) is list and level < 3:
            for child in value[:4]:
                inspect(child, prefix + '[].', level + 1)

    inspect(body)
    lowered = text.casefold()
    codes = sorted(code for code in CODES
                   if re.search(r'(?<![A-Za-z0-9_])' + re.escape(code) + r'(?![A-Za-z0-9_])', text))
    terms = sorted(set(re.findall(r'[a-z]+', lowered)) & TERMS)
    numbers = sorted({int(match.group(1)) for match in re.finditer(
        r'(?i)(?:limit|maximum|max|length|tokens?|characters?|bytes|size)[^0-9\n]{0,30}(\d{1,9})(?!\d)', text)})[:8]
    if ({'invalid_api_key', 'authentication_error', 'permission_denied'} & set(codes)
            or response.status_code in (401, 403)
            or re.search(r'invalid\s+api\s+key|unauthorized|permission\s+denied', lowered)):
        category = 'credential_or_permission_refused'
    elif response.status_code in (429, 529) or re.search(r'insufficient\s+(?:balance|quota)|quota\s+exceeded', lowered):
        category = 'quota_or_service_refused'
    elif 'model_not_found' in codes or re.search(r'model\s+(?:not\s+found|is\s+not\s+supported)|no\s+provider\s+found', lowered):
        category = 'model_route_refused'
    elif ('max_tokens_exceeded' in codes or 'context_length_exceeded' in codes
            or re.search(r'(?:context\s+(?:length|limit)|token\s+limit).{0,60}(?:exceed|maximum|too\s+long)', lowered)):
        category = 'model_context_limit'
    elif 'state' in terms and {'size', 'length', 'characters'} & set(terms) and {'limit', 'maximum', 'exceeded', 'exceeds', 'too'} & set(terms):
        category = 'state_size_limit'
    elif 'body' in terms and {'large', 'limit', 'maximum'} & set(terms):
        category = 'request_body_limit'
    elif {'choice', 'criteria', 'options'} & set(terms) and {'maximum', 'minimum', 'expected', 'only'} & set(terms):
        category = 'choice_constraint'
    else:
        category = 'unclassified_rejection'
    return {'content_type': content_type, 'body_bytes': len(raw),
        'body_kind': type(body).__name__ if body is not None else 'text',
        'structured_fields': sorted(set(paths))[:32], 'recognized_codes': codes,
        'public_terms': terms, 'public_limits': numbers, 'category': category,
        'key_echo_redacted': key_echo, 'token_pattern_redacted': suspicious,
        'synthetic_echo_detected': marker in text, 'raw_saved': False}


def state(size, nested=False):
    sentence = 'Synthetic public input sizing sentence. '
    data = (sentence * (size // len(sentence) + 1))[:size]
    if nested:
        data = {'level1': {'level2': {'level3': {'level4': data}}}}
    return {'marker': 'ready', 'data': data}


async def run(root):
    spec = importlib.util.spec_from_file_location('fixed_jev_operator',
        ROOT / 'tooling/checks/server_product/probe-work-package-generation.py')
    driver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
    raw_key = ExistingOpenCodeInput('/home/maoqh/projects/ordessa/.env',
                                  variable_name='OPEN_CODE_GO_API_KEY').read()
    try:
        key = raw_key.decode('ascii')
    finally:
        raw_key[:] = b'\0' * len(raw_key); raw_key.clear()
    result = {'case': 'synthetic-jev-differential/1', 'model': MODEL, 'endpoint': BASE + '/v1/systemone',
        'attempt_limit': 5, 'real_DID_sent': False, 'work_created': False,
        'review_ref_created': False, 'generation_invocations': 0, 'cases': []}
    holder = {'jev_network_trace': []}
    result['network_trace'] = holder['jev_network_trace']
    client = driver.jev_http_client(holder, 20)
    active = None

    def save():
        (root / 'receipt.json').write_text(json.dumps(result, indent=2) + '\n')
        (root / 'receipt.json').chmod(0o600)

    async def request_hook(request):
        if active is not None and request.method == 'POST':
            payload = json.loads(request.content)
            active['wire'] = {'body_bytes': len(request.content),
                'body_sha256': hashlib.sha256(request.content).hexdigest(),
                'root_fields': sorted(payload), 'state_type': type(payload['state']).__name__,
                'questions_type': type(payload['questions']).__name__,
                'question_fields': sorted(payload['questions']['diagnostic']),
                'question_count': len(payload['questions']),
                'long_header_present': request.headers.get(LONG_HEADER) == 'true'}

    async def response_hook(response):
        if active is not None and response.request.method == 'POST':
            await response.aread()
            active['http_status'] = response.status_code
            if not response.is_success:
                active['rejection'] = project_error(response, key, 'Synthetic public input sizing sentence.')

    client.event_hooks['request'].append(request_hook)
    client.event_hooks['response'].append(response_hook)
    async with AsyncTypeSafeClient(api_key=key, base_url=BASE, model=MODEL,
            timeout=20, retry=RetryPolicy(max_retries=0), http_client=client) as sdk:
        result['anonymous_warmup'] = []
        for _ in range(2):
            try:
                response = await client.get(BASE + '/v1/systemone')
                result['anonymous_warmup'].append({'http_status': response.status_code})
                break
            except httpx2.RequestError as error:
                result['anonymous_warmup'].append({'error_type': type(error).__name__})
        else:
            result['stop'] = 'anonymous_connection_not_ready'; save(); return result

        async def case(label, size, *, nested=False, long=False, options=3):
            nonlocal active
            if len(result['cases']) >= 5:
                raise RuntimeError('Diagnostic request budget spent')
            active = {'id': label, 'data_bytes': size, 'nested': nested,
                      'long_context': long, 'options': options, 'status': 'started'}
            result['cases'].append(active); save()
            criteria = {'ready': 'The marker is ready', 'other': 'The marker is other'}
            if options == 3:
                criteria['unknown'] = 'The marker is not supplied'
            started = time.monotonic()
            try:
                response = await sdk.system_one(state(size, nested),
                    {'diagnostic': Choice(instructions='Which value is in the marker field?', criteria=criteria)},
                    extra_headers={LONG_HEADER: 'true'} if long else None)
                answer = response.choices['diagnostic']
                if answer.choice not in criteria or response.model not in {'jev-1.13.0', MODEL}:
                    raise ValueError('Unexpected diagnostic response identity')
                active.update(status='completed', choice=answer.choice,
                    resolved_model=response.model,
                    input_tokens=response.usage.input_tokens, output_tokens=response.usage.output_tokens)
            except Exception as error:
                active['status'] = 'failed'; active['error_type'] = type(error).__name__
            active['elapsed_ms'] = round((time.monotonic() - started) * 1000)
            selected = active; active = None; save(); return selected

        first = await case('A-flat-small', 1024)
        if first['status'] != 'completed':
            category = first.get('rejection', {}).get('category')
            if first.get('http_status') == 400 and category in {'choice_constraint', 'unclassified_rejection'}:
                await case('A-two-options-only', 1024, options=2)
            result['stop'] = 'baseline_rejected'; return result
        nested = await case('B-nesting-only', 1024, nested=True)
        if nested['status'] != 'completed':
            result['stop'] = 'nesting_rejected'; return result
        medium = await case('C-size-only', 131072)
        if medium['status'] != 'completed':
            if medium.get('rejection', {}).get('category') == 'model_context_limit':
                await case('C-long-header-only', 131072, long=True)
            result['stop'] = 'medium_rejected'; return result
        large = await case('D-size-only', 330000)
        if large['status'] != 'completed' and large.get('rejection', {}).get('category') == 'model_context_limit':
            await case('D-long-header-only', 330000, long=True)
        result['stop'] = 'matrix_complete'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-real', action='store_true')
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    if not args.run_real:
        raise SystemExit('Explicit authorized real diagnostic required')
    root = args.root.absolute()
    if root.exists() or root.is_symlink() or root.parent.resolve() != (ROOT / '.nightly-cache').resolve():
        raise SystemExit('Fresh direct private cache root required')
    root.mkdir(mode=0o700)
    for name in ('typesafe_sdk', 'httpx2', 'httpcore2'):
        logging.getLogger(name).setLevel(logging.WARNING)
    try:
        result = asyncio.run(run(root))
        result['client_closed'] = True
    except Exception as error:
        receipt = root / 'receipt.json'
        result = json.loads(receipt.read_text()) if receipt.is_file() else {'cases': []}
        result.update(stop='local_diagnostic_failure', error_type=type(error).__name__)
    (root / 'receipt.json').write_text(json.dumps(result, indent=2) + '\n')
    (root / 'receipt.json').chmod(0o600)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
