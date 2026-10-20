"""pi-rpc/1 prompt handler: encode, settle observation, abort."""
import json

from ordessa_execution_agents.sdk.native_prompt import observe_native_prompt
from ordessa_harness_pi.provider import PiPromptHandler

SESSION = 'sess-1'


def params(text='hello'):
    return json.dumps({'sessionId': SESSION, 'prompt': [{'type': 'text', 'text': text}]}).encode()


class ProtocolEventPage:
    def __init__(self, frames, cursor=None, has_more=False):
        self.events = []
        for raw in frames:
            import hashlib
            payload = (json.dumps(raw) + '\n').encode()
            self.events.append(type('E', (), {
                'kind': 'bytes', 'payload_bytes': payload,
                'payload_digest': 'sha256:' + hashlib.sha256(payload).hexdigest()})())
        self.cursor, self.has_more, self._cursor = cursor, has_more, cursor


def test_prompt_frame_targets_the_agent_message():
    handler = PiPromptHandler()
    frame = handler.encode_prompt(SESSION, params('compute'), 'agent-operation/1')
    value = json.loads(frame)
    assert value['type'] == 'prompt' and value['message'] == 'compute'
    assert frame.endswith(b'\n')


def test_agent_end_alone_does_not_finish_the_turn():
    handler = PiPromptHandler()
    end = {'type': 'agent_end', 'messages': [{'role': 'assistant', 'content': 'DONE'}]}
    assert handler.accept(end, session_id=SESSION) is False, 'only agent_settled concludes'


def run_observe(handler, pages):
    import asyncio
    queue = list(pages)

    async def main():
        async def receive(cursor, deadline, invocation):
            return queue.pop(0)

        return await observe_native_prompt(receive, handler, session_id=SESSION,
            deadline=asyncio.get_running_loop().time() + 60, invocation=None,
            delivery={'delivery': 'confirmed'})

    return asyncio.run(main())


def test_settled_finishes_the_turn_and_records_the_answer():
    handler = PiPromptHandler()
    pages = [ProtocolEventPage([{'type': 'agent_end',
                    'messages': [{'role': 'assistant', 'content': 'real answer'}]}]),
             ProtocolEventPage([{'type': 'agent_settled'}])]
    terminal, observation = run_observe(handler, pages)
    assert terminal == 'completed'
    assert observation['answer'] == 'real answer'


def test_message_end_text_is_captured_when_agent_end_has_no_text():
    handler = PiPromptHandler()
    pages = [ProtocolEventPage([{'type': 'message_end', 'message': {
        'role': 'assistant', 'content': [{'type': 'thinking', 'thinking': 'x'},
                                         {'type': 'text', 'text': '391'}]}}]),
             ProtocolEventPage([{'type': 'agent_end', 'messages': []}]),
             ProtocolEventPage([{'type': 'agent_settled'}])]
    terminal, observation = run_observe(handler, pages)
    assert terminal == 'completed' and observation['answer'] == '391'


def test_abort_frame_is_encoded():
    handler = PiPromptHandler()
    value = json.loads(handler.encode_cancel(SESSION, 'agent-operation/2'))
    assert value['type'] == 'abort'
