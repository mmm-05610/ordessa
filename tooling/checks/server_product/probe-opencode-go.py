"""Bounded explicit Go API compatibility probe; no secrets or response text in output.

This tests upstream protocols, not Harness/Profile/Desktop integration. Models
and endpoint families are taken from https://opencode.ai/docs/go/ (2026-10-01).
"""
import argparse
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


def read_key(path, line):
    if type(line) is not int or line < 1:
        raise ValueError('Positive key line required')
    lines = path.read_text().splitlines()
    value = lines[line - 1].strip() if line <= len(lines) else ''
    if not value or len(value) > 8000 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('Selected key line is absent or invalid')
    return value


def payloads():
    prompt = 'Reply only OK. Do not use tools.'
    return (
        ('openai-chat', 'chat/completions', dict(model='glm-5.3-flash',
            messages=[dict(role='user', content=prompt)], max_tokens=256, stream=False)),
        ('anthropic-messages', 'messages', dict(model='minimax-m2.7',
            messages=[dict(role='user', content=prompt)], max_tokens=256, stream=False)),
        ('openai-responses', 'responses', dict(model='gpt-5.6-luna', input=prompt,
            max_output_tokens=256, stream=False)),
    )


def run(args):
    if not args.allow_model_calls:
        raise ValueError('Explicit bounded model-call opt-in required')
    key = read_key(args.key_file, args.key_line)
    session = 'ordessa-compat-' + uuid4().hex
    failed = False
    for protocol, endpoint, payload in payloads():
        headers = {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
                   'User-Agent': 'Ordessa/0.1 compatibility-probe', 'x-opencode-session': session}
        if protocol == 'anthropic-messages':
            headers.update({'x-api-key': key, 'anthropic-version': '2023-06-01'})
        request = Request('https://opencode.ai/zen/go/v1/' + endpoint,
                          data=json.dumps(payload).encode(), headers=headers, method='POST')
        try:
            response = urlopen(request, timeout=90)
        except HTTPError as error:
            response = error
        except Exception:
            print(json.dumps(dict(protocol=protocol, state='transport-error')), flush=True)
            failed = True
            continue
        with response:
            raw = response.read(1024 * 1024 + 1)
            report = dict(protocol=protocol, model=payload['model'], httpStatus=response.status,
                          scope='direct-upstream-not-harness-or-profile')
            try:
                body = json.loads(raw) if len(raw) <= 1024 * 1024 else {}
                if protocol == 'openai-chat':
                    message = body.get('choices', [{}])[0].get('message', {})
                    text = message.get('content')
                    report['finishReason'] = body.get('choices', [{}])[0].get('finish_reason')
                elif protocol == 'anthropic-messages':
                    text = ''.join(item.get('text', '') for item in body.get('content', [])
                                   if item.get('type') == 'text')
                    report['finishReason'] = body.get('stop_reason')
                else:
                    text = ''.join(part.get('text', '') for item in body.get('output', [])
                                   for part in item.get('content', []) if part.get('type') == 'output_text')
                    report['finishReason'] = body.get('status')
                report['nonemptyText'] = isinstance(text, str) and bool(text.strip())
                if report.get('finishReason') not in ('stop', 'length', 'tool_calls', 'end_turn',
                                                      'max_tokens', 'stop_sequence', 'completed', 'incomplete'):
                    report['finishReason'] = 'unrecognized'
                report['state'] = 'response' if response.status == 200 else 'http-rejected'
            except Exception:
                report['state'] = 'unrecognized-response'
            # Never emit upstream error text, response headers, usage details or credentials.
            print(json.dumps(report), flush=True)
            failed |= report.get('state') != 'response' or not report.get('nonemptyText')
    return int(failed)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-model-calls', action='store_true')
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--key-line', type=int, default=2)
    raise SystemExit(run(parser.parse_args()))
