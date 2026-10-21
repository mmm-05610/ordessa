"""Protocol-neutral prompt observation for non-ACP harness providers.

The owner owns the guarded write, the bounded frame read and the turn transition.
The provider owns its dialect: it encodes the prompt frame, decides which decoded
frame ends the turn, and maps that frame to a terminal outcome. No dialect is
interpreted here.
"""
import asyncio
import hashlib
import json
import math

MAX_PROMPT_BYTES = 1048576
MAX_PROMPT_FRAMES = 4096


def prompt_text(params_bytes):
    """Extract the user text from the frozen prompt parameters.

    The public prompt value keeps the ACP-shaped ``{"prompt": [{"type": "text",
    "text": …}]}`` content list; it is data, not an ACP frame, so native brands
    can reuse it without speaking ACP.
    """
    if type(params_bytes) is not bytes:
        raise ValueError('prompt parameters must be bytes')
    try:
        value = json.loads(params_bytes.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        raise ValueError('prompt parameters must be UTF-8 JSON') from None
    if type(value) is not dict:
        raise ValueError('prompt parameters must be an object')
    parts = value.get('prompt')
    if type(parts) is not list or not parts:
        raise ValueError('prompt content is required')
    texts = []
    for part in parts:
        if type(part) is not dict or part.get('type') != 'text':
            raise ValueError('only text prompt parts are supported')
        text = part.get('text')
        if type(text) is not str or not text or '\x00' in text:
            raise ValueError('prompt text is invalid')
        texts.append(text)
    text = '\n'.join(texts)
    if len(text.encode('utf-8')) > 262144:
        raise ValueError('prompt text is too large')
    return text


async def observe_native_prompt(receive, handler, *, session_id, deadline, invocation, delivery):
    """Read bounded frames until the provider's predicate completes the turn."""
    if not callable(getattr(handler, 'accept', None)) or not callable(getattr(handler, 'outcome', None)):
        raise ValueError('native prompt handler is incomplete')
    loop = asyncio.get_running_loop()
    pending = b''
    cursor = None
    seen = set()
    size = 0
    frames = 0
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return 'unknown', {**delivery, 'reason': 'prompt_observation_timeout'}
        page = await asyncio.wait_for(receive(cursor, deadline, invocation), remaining)
        if type(page).__name__ != 'ProtocolEventPage':
            raise ValueError('native prompt page is invalid')
        if not page.events:
            if not page.has_more:
                return 'unknown', {**delivery, 'reason': 'prompt_stream_closed'}
            cursor = page.cursor
            continue
        for event in page.events:
            raw = event.payload_bytes
            if event.kind != 'bytes' or event.payload_digest != 'sha256:' + hashlib.sha256(raw).hexdigest():
                raise ValueError('native prompt event is invalid')
            size += len(raw)
            frames += 1
            if size > MAX_PROMPT_BYTES or frames > MAX_PROMPT_FRAMES:
                return 'unknown', {**delivery, 'reason': 'prompt_observation_limit'}
            pending += raw
            while b'\n' in pending:
                line, pending = pending.split(b'\n', 1)
                if not line:
                    continue
                try:
                    value = json.loads(line.decode('utf-8'))
                except (ValueError, UnicodeDecodeError):
                    raise ValueError('native prompt frame is not JSON') from None
                if type(value) is not dict:
                    continue
                if handler.accept(value, session_id=session_id):
                    terminal, observation = handler.outcome(value, session_id=session_id)
                    return terminal, {**delivery, **observation}
        if page.has_more:
            if page.cursor in seen:
                raise ValueError('native prompt cursor repeated')
            seen.add(page.cursor)
            cursor = page.cursor
