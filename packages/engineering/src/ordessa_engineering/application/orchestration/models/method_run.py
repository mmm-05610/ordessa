"""Immutable read model over the original runs/step_log persistence."""
from dataclasses import dataclass
from ...contracts.errors import ApplicationError
from ....domain.artifacts.library_material_codec import canonical_json


def _reference_json(value):
    """Keep only recognizable immutable references; never label bodies as refs."""
    if type(value) is not dict:
        return None
    if {'library_id','stable_id','revision','digest'} <= value.keys():
        return canonical_json(value)
    if {'digest','byte_length','media_type','storage_object_id'} <= value.keys():
        return canonical_json(value)
    if {'method_id','release_version','schema_version','snapshot_digest'} <= value.keys():
        return canonical_json(value)
    if {'repository_id','commit_id','tree_digest'} <= value.keys():
        return canonical_json(value)
    if {'policy_id','revision','digest'} <= value.keys():
        return canonical_json(value)
    if type(value.get('kind')) is not str:
        return None
    identities={
        'artifact_revision': {'artifact_id','revision_id'},
        'implementation_package': {'package_id'},
        'proposal': {'change_id','proposal_id'},
        'review': {'review_id'},
        'submission': {'submission_id'},
        'acceptance-receipt': {'adoption_id'},
        'approval': {'approval_id'},
    }
    identity=identities.get(value['kind'])
    digest_key='grant_digest' if value['kind']=='approval' else 'digest'
    if (identity is None or not identity <= value.keys()
            or not {'realm_id','project_id',digest_key} <= value.keys()):
        return None
    return canonical_json(value)


@dataclass(frozen=True)
class MethodRunStep:
    ordinal: int
    step_id: str
    operation: str
    attempt: int
    status: str
    receipt_ref_json: str
    dispatch_json: str | None = None

    def __post_init__(self):
        if (type(self.ordinal) is not int or self.ordinal < 0 or type(self.attempt) is not int
                or self.attempt < 1 or any(type(value) is not str for value in
                    (self.step_id,self.operation,self.status,self.receipt_ref_json))):
            raise ValueError('invalid immutable MethodRun step')

    def to_dict(self):
        from json import loads
        value={'ordinal': self.ordinal, 'step_id': self.step_id,
                'operation': self.operation, 'attempt': self.attempt,
                'status': self.status, 'receipt_ref': loads(self.receipt_ref_json)}
        if self.dispatch_json is not None:
            value['dispatch']=loads(self.dispatch_json)
        return value


@dataclass(frozen=True)
class MethodRunOutput:
    name: str
    context_slot: str
    reference_json: str | None

    def __post_init__(self):
        if (type(self.name) is not str or type(self.context_slot) is not str
                or (self.reference_json is not None and type(self.reference_json) is not str)):
            raise ValueError('invalid immutable MethodRun output')

    @property
    def available(self):
        return self.reference_json is not None

    def to_dict(self):
        from json import loads
        return {'name': self.name, 'context_slot': self.context_slot,
                'available': self.available,
                'reference': None if self.reference_json is None else loads(self.reference_json)}


@dataclass(frozen=True)
class MethodRun:
    """One fixed method snapshot's run, projected without another state store."""
    run_id: str
    method_binding_json: str
    inputs_json: str
    registry_ref_json: str
    status: str
    cursor: int
    wait_reason: str | None
    created_at: str
    updated_at: str
    steps: tuple[MethodRunStep, ...]
    outputs: tuple[MethodRunOutput, ...]

    def __post_init__(self):
        if (any(type(value) is not str for value in
                (self.run_id,self.method_binding_json,self.inputs_json,self.registry_ref_json,self.status,
                 self.created_at,self.updated_at))
                or type(self.cursor) is not int or (self.wait_reason is not None and type(self.wait_reason) is not str)
                or type(self.steps) is not tuple or any(type(step) is not MethodRunStep for step in self.steps)
                or type(self.outputs) is not tuple or any(type(output) is not MethodRunOutput for output in self.outputs)):
            raise ValueError('invalid immutable MethodRun view')

    @classmethod
    def from_persisted(cls, run_id, row, step_rows, output_map):
        from dataclasses import asdict
        if type(step_rows) is not list:
            raise ApplicationError('WORK_HISTORY_INVALID')
        steps=[]
        for value in step_rows:
            ref=value['receipt_ref']
            steps.append(MethodRunStep(value['ordinal'], value['step_id'], value['operation'],
                value['attempt'], value['status'], canonical_json(None if ref is None else asdict(ref)),
                None if 'dispatch' not in value else canonical_json(value['dispatch'])))
        slots=row['inputs'].get('slots')
        if type(slots) is not dict:
            raise ApplicationError('WORK_BINDING_INVALID')
        outputs=[]
        for binding in (() if output_map is None else output_map.entries):
            reference=_reference_json(slots.get(binding.slot))
            outputs.append(MethodRunOutput(binding.name, binding.slot,
                reference))
        return cls(run_id, canonical_json(row['inputs']['method_ref']),
            canonical_json(row['inputs']), canonical_json(row['registry_ref']), row['status'],
            row['cursor'], row['wait_reason'], row['created_at'], row['updated_at'],
            tuple(steps), tuple(outputs))

    def method_binding_view(self):
        from json import loads
        return loads(self.method_binding_json)

    def steps_view(self):
        return tuple(step.to_dict() for step in self.steps)

    def outputs_view(self):
        return tuple(output.to_dict() for output in self.outputs)

    def execution_view(self):
        dispatches=tuple({'step_id':step.step_id,'attempt':step.attempt,
                         **step.to_dict()['dispatch']}
                        for step in self.steps if step.dispatch_json is not None)
        return ({'availability':'available','dispatches':dispatches} if dispatches
                else {'availability':'unavailable'})

    def to_dict(self):
        from json import loads
        return {'run_id': self.run_id, 'method_binding': loads(self.method_binding_json),
                'inputs': loads(self.inputs_json), 'registry_ref': loads(self.registry_ref_json),
                'steps': self.steps_view(), 'outputs': self.outputs_view(),
                'execution':self.execution_view(),
                'status': self.status, 'cursor': self.cursor, 'wait_reason': self.wait_reason,
                'created_at': self.created_at, 'updated_at': self.updated_at}
