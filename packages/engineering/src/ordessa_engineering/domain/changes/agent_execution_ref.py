"""Versioned original Agent receipt identity; facts never confer send authority."""
from dataclasses import dataclass
import re
from ordessa_infrastructure.encoding import canonical_bytes,decode_json
from ..common.models.execution_refs import read_agent_instance_ref
from ..common.models.refs import BlobRef
from ..common.models.values import Digest,validate_id
from ..common.outcomes.diagnostics import ReferenceError
from ..common.mechanisms.codec import projection


@dataclass(frozen=True)
class AgentExecutionRecordRef:
    agent_ref_bytes:bytes
    turn_ref_bytes:bytes
    source_revision:str
    operation_ref:str
    engineering_attempt_ref:str
    prompt_input_digest:Digest
    query_digest:str
    captured_observation_ref:BlobRef

    def __post_init__(self):
        agent=dict(read_agent_instance_ref(self.agent_ref_bytes))
        for value in (self.source_revision,self.operation_ref,self.engineering_attempt_ref):validate_id(value)
        if (type(self.prompt_input_digest) is not Digest or type(self.captured_observation_ref) is not BlobRef
                or type(self.query_digest) is not str or not re.fullmatch(r'sha256:[0-9a-f]{64}',self.query_digest)
                or type(self.turn_ref_bytes) is not bytes or len(self.turn_ref_bytes)>8192):
            raise ReferenceError('INVALID_AGENT_EXECUTION_RECORD_REF')
        if self.captured_observation_ref.media_type!='application/json' or self.captured_observation_ref.byte_length>262144:
            raise ReferenceError('INVALID_AGENT_EXECUTION_RECORD_REF')
        try:
            turn=decode_json(self.turn_ref_bytes)
            if (type(turn) is not dict or set(turn)!={'schemaVersion','instanceRef','turnId'}
                    or turn['schemaVersion']!='agent-turn-ref/1' or turn['instanceRef']!=agent
                    or canonical_bytes(turn)!=self.turn_ref_bytes):raise ValueError()
            validate_id(turn['turnId'])
            query={'schemaVersion':'agent-turn-query/1','turnRef':turn,
                   'expectedInputDigest':'sha256:'+self.prompt_input_digest.hex}
            import hashlib
            if 'sha256:'+hashlib.sha256(canonical_bytes(query)).hexdigest()!=self.query_digest:raise ValueError()
        except (ValueError,TypeError,KeyError,RecursionError,UnicodeError):
            raise ReferenceError('INVALID_AGENT_EXECUTION_RECORD_REF') from None

    def projection(self,*,identity=False):
        return {'schemaVersion':'engineering-agent-execution-ref/2',
            'agent_ref_bytes':decode_json(self.agent_ref_bytes),'turn_ref_bytes':decode_json(self.turn_ref_bytes),
            'source_revision':self.source_revision,'operation_ref':self.operation_ref,
            'engineering_attempt_ref':self.engineering_attempt_ref,
            'prompt_input_digest':projection(self.prompt_input_digest,identity=identity),
            'query_digest':self.query_digest,'captured_observation_ref':projection(self.captured_observation_ref,identity=identity)}

    @property
    def agent_ref(self):
        return decode_json(self.agent_ref_bytes)
