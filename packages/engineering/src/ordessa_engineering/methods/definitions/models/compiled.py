"""Neutral compiled payloads and the compilation result; no host or stage implementation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Literal, Union
from types import MappingProxyType

from .. import errors
from .identity import MethodIdentity, ResourceRef
from .sources import SourceBundle, ParsedSourceBundle
from .capabilities import CapabilityBinding

from ..defaults import DOCUMENT_VALIDATION_TARGET_DEFAULT_V1, CRITERION_DEFAULTS_V1

@dataclass(frozen=True)
class FrozenObject:
    entries: tuple[tuple[str, Any], ...] = ()

    def __post_init__(self):
        if type(self.entries) is not tuple or any(type(pair) is not tuple or len(pair) != 2 or type(pair[0]) is not str for pair in self.entries):
            raise TypeError("frozen object requires immutable string entries")
        if len({key for key, _ in self.entries}) != len(self.entries):
            raise ValueError("duplicate frozen key")
        def check(value):
            if isinstance(value, FrozenObject): return
            if type(value) is tuple:
                for item in value: check(item)
            elif value is not None and type(value) not in (str, int, bool):
                raise TypeError("frozen object cannot contain mutable values")
        for _, value in self.entries: check(value)



def freeze_value(value: Any) -> Any:
    if isinstance(value, dict):
        return FrozenObject(tuple((key, freeze_value(child)) for key, child in sorted(value.items())))
    if isinstance(value, list):
        return tuple(freeze_value(child) for child in value)
    if value is None or type(value) in (str, int, bool):
        return value
    raise ValueError("unsupported method value")



def thaw_value(value: Any) -> Any:
    if isinstance(value, FrozenObject):
        return {key: thaw_value(child) for key, child in value.entries}
    if isinstance(value, tuple):
        return [thaw_value(child) for child in value]
    return value



@dataclass(frozen=True)
class SlotBinding:
    name: str
    slot: str



@dataclass(frozen=True)
class Transition:
    outcome: str
    kind: Literal["next", "wait", "stop"]
    target: str



@dataclass(frozen=True)
class CompiledNode:
    node_id: str
    kind: Literal["operation", "wait", "stop"]
    operation: str | None = None
    event: str | None = None
    next_node: str | None = None
    stop_outcome: str | None = None
    inputs: tuple[SlotBinding, ...] = ()
    bindings: tuple[SlotBinding, ...] = ()
    matches: tuple[SlotBinding, ...] = ()
    transitions: tuple[Transition, ...] = ()
    config: FrozenObject = FrozenObject()



@dataclass(frozen=True)
class TargetSelector:
    """Select neutral document types, never host objects or database records."""
    document_types: tuple[str, ...] = ()



@dataclass(frozen=True)
class DispositionPolicy:
    satisfied: str
    violated: str
    insufficient: str
    unknown: str



@dataclass(frozen=True)
class ReductionPolicy:
    required_criteria: str
    empty_applicable_set: str
    priority: tuple[str, ...]



@dataclass(frozen=True)
class DecisionPolicy:
    """Decimal text remains exact; no platform floats or model execution."""
    kind: str
    calibration_profile_id: str
    activation: str
    thresholds: tuple[tuple[str, str], ...]
    selected_option: str | None
    option_statuses: tuple[tuple[str, str], ...]
    below_threshold: str | None
    above_threshold: str | None
    missing_evaluation: str
    truncation: str



@dataclass(frozen=True)
class CheckSpec:
    capability_id: str
    interface_version: str
    bindings: FrozenObject



@dataclass(frozen=True)
class CriteriaSpec:
    standard_ref: ResourceRef
    standard_revision: str
    criterion_id: str
    statement: str
    selector: TargetSelector
    required_inputs: tuple[str, ...]
    required: bool
    blocking: bool
    reviewer_capability: str | None
    checks: tuple[CheckSpec, ...]
    policy: DispositionPolicy
    reduction: ReductionPolicy
    answer_vocabulary: FrozenObject | None
    decision_policy: DecisionPolicy | None



@dataclass(frozen=True)
class CriterionRef:
    standard_ref: ResourceRef
    criterion_id: str



@dataclass(frozen=True)
class QuestionSpec:
    question_id: str
    question_revision: str
    kind: str
    criterion_refs: tuple[CriterionRef, ...]
    instructions: str
    answer_from: CriterionRef
    answer_vocabulary: FrozenObject



@dataclass(frozen=True)
class DecisionSpec:
    resource_ref: ResourceRef
    question_set_id: str
    question_set_version: str
    input_contract: str
    input_mapping_version: str
    required_input_slots: tuple[str, ...]
    iteration: str
    questions: tuple[QuestionSpec, ...]
    result_contract: str
    truncation_policy: str
    missing_required_evidence: str
    evidence_order: str | None



@dataclass(frozen=True)
class DocumentSpec:
    document_type: str
    schema_ref: ResourceRef
    value_schema: FrozenObject
    template_ref: ResourceRef | None
    validation_target: Literal["method_content"] = DOCUMENT_VALIDATION_TARGET_DEFAULT_V1



@dataclass(frozen=True)
class SkillSpec:
    role: str
    resource_ref: ResourceRef



@dataclass(frozen=True)
class StoredProgram:
    """Lossless immutable versioned encoding, with no fabricated source bindings."""
    schema_version: int
    compiler_version: str
    workflow: FrozenObject
    documents: tuple[FrozenObject, ...]
    standards: tuple[FrozenObject, ...]
    decision_templates: tuple[FrozenObject, ...]
    skill_resources: tuple[FrozenObject, ...]
    capability_bindings: tuple[CapabilityBinding, ...]

    def __post_init__(self):
        if type(self.schema_version) is not int or type(self.compiler_version) is not str:
            raise TypeError("typed program version required")
        if not isinstance(self.workflow, FrozenObject): raise TypeError("immutable workflow required")
        for name in ("documents", "standards", "decision_templates", "skill_resources"):
            value = getattr(self, name)
            if type(value) is not tuple or any(not isinstance(item, FrozenObject) for item in value):
                raise TypeError("immutable program sections required")
        if type(self.capability_bindings) is not tuple or any(type(item) is not CapabilityBinding for item in self.capability_bindings):
            raise TypeError("immutable capability bindings required")

    @property
    def engine_contract_version(self): return "ordessa.methods/v1"


@dataclass(frozen=True)
class HistoricalStoredProgram(StoredProgram):
    def __post_init__(self):
        super().__post_init__()
        if self.schema_version != 1: raise ValueError("historical program version mismatch")

@dataclass(frozen=True)
class CurrentStoredProgram(StoredProgram):
    schema_resources: tuple[FrozenObject, ...]
    def __post_init__(self):
        super().__post_init__()
        if self.schema_version != 2 or type(self.schema_resources) is not tuple or any(not isinstance(item, FrozenObject) for item in self.schema_resources):
            raise ValueError("current program version/closure mismatch")

@dataclass(frozen=True)
class ProgramBindings:
    standards: tuple[tuple[str, ResourceRef], ...]
    decisions: tuple[tuple[str, ResourceRef], ...]
    def __post_init__(self):
        for values in (self.standards, self.decisions):
            if type(values) is not tuple or any(type(pair) is not tuple or len(pair) != 2 or type(pair[0]) is not str or type(pair[1]) is not ResourceRef for pair in values):
                raise TypeError("immutable program source bindings required")



# Typed modern semantic authority. Open payloads are limited to contract-defined
# config, check bindings and JSON Schema values; no unknown semantic field bag.
def _typecheck(value, hint):
    from typing import get_origin, get_args
    from types import UnionType
    origin, args = get_origin(hint), get_args(hint)
    if origin in (UnionType, Union):
        if not any(_matches(value, child) for child in args): raise TypeError("semantic field type mismatch")
    elif origin is Literal:
        if not any(type(value) is type(x) and value == x for x in args): raise ValueError("semantic literal invalid")
    elif origin is tuple:
        if type(value) is not tuple: raise TypeError("immutable semantic tuple required")
        if len(args) == 2 and args[1] is Ellipsis:
            for child in value: _typecheck(child, args[0])
        else:
            if len(value) != len(args): raise TypeError("semantic tuple arity mismatch")
            for child, spec in zip(value, args): _typecheck(child, spec)
    elif hint is str:
        if type(value) is not str or not value: raise TypeError("nonempty semantic string required")
    elif hint in (int, bool, type(None)):
        if type(value) is not hint: raise TypeError("semantic primitive type mismatch")
    elif type(value) is not hint:
        raise TypeError("typed semantic value required")
    elif hint is ResourceRef:
        for name in ("resource_id", "sha256", "kind"): _typecheck(getattr(value, name), str)
        if len(value.sha256) != 64 or any(c not in "0123456789abcdef" for c in value.sha256):
            raise ValueError("exact semantic resource digest required")


def _matches(value, hint):
    try: _typecheck(value, hint); return True
    except (TypeError, ValueError): return False






class SemanticValue:
    """Pure constructor validation of explicit semantic fields."""
    def __post_init__(self):
        from dataclasses import fields
        from typing import get_type_hints
        hints = get_type_hints(type(self))
        for f in fields(self): _typecheck(getattr(self, f.name), hints[f.name])




from dataclasses import field


@dataclass(frozen=True, kw_only=True)
class TransitionTarget(SemanticValue):
    next: str | None = None
    wait: str | None = None
    stop: str | None = None
    def __post_init__(self):
        super().__post_init__()
        if sum(x is not None for x in (self.next, self.wait, self.stop)) != 1: raise ValueError("one transition target required")


@dataclass(frozen=True, kw_only=True)
class SlotMap(SemanticValue):
    entries: tuple[SlotBinding, ...]
    def __post_init__(self):
        super().__post_init__()
        for x in self.entries:
            _typecheck(x.name, str);_typecheck(x.slot, str)
        if len({x.name for x in self.entries}) != len(self.entries): raise ValueError("duplicate slot binding")


@dataclass(frozen=True, kw_only=True)
class OutcomeBinding(SemanticValue):
    outcome: str
    target: TransitionTarget


@dataclass(frozen=True, kw_only=True)
class OutcomeMap(SemanticValue):
    entries: tuple[OutcomeBinding, ...]
    def __post_init__(self):
        super().__post_init__()
        if not self.entries or len({x.outcome for x in self.entries}) != len(self.entries): raise ValueError("nonempty unique outcomes required")


@dataclass(frozen=True, kw_only=True)
class ResultRouting(SemanticValue):
    path: str
    outcomes: OutcomeMap


@dataclass(frozen=True, kw_only=True)
class LoopSpec(SemanticValue):
    loop_id: str
    from_step: str
    to_step: str
    max_rounds: int
    on_exhausted: str
    def __post_init__(self):
        super().__post_init__()
        if not 1 <= self.max_rounds <= 4096:
            raise ValueError('bounded serial rounds required')


@dataclass(frozen=True, kw_only=True)
class OperationNode(SemanticValue):
    id: str
    kind: Literal["operation"]
    operation: str
    outcomes: OutcomeMap
    inputs: SlotMap | None = None
    config: FrozenObject | None = None
    result_routing: ResultRouting | None = None


@dataclass(frozen=True, kw_only=True)
class WaitNode(SemanticValue):
    id: str
    kind: Literal["wait"]
    event: str
    next: str
    bind: SlotMap | None = None
    match: SlotMap | None = None


@dataclass(frozen=True, kw_only=True)
class StopNode(SemanticValue):
    id: str
    kind: Literal["stop"]
    outcome: str


@dataclass(frozen=True, kw_only=True)
class WorkflowSpec(SemanticValue):
    schema_version: Literal[1]
    entry: str
    steps: tuple[OperationNode | WaitNode | StopNode, ...]
    stop_outcomes: tuple[str, ...]
    wait_kinds: tuple[str, ...]
    workflow_id: str | None = None
    semantics: str | None = None
    context_slots: tuple[str, ...] | None = None
    resume_contract: str | None = None
    cancellation: str | None = None
    revision_restart: str | None = None
    automatic_side_effect_retry: Literal["forbidden_when_outcome_unknown"] | None = None
    outputs: SlotMap | None = None
    loops: tuple[LoopSpec, ...] | None = None
    def __post_init__(self):
        super().__post_init__()
        if not self.steps: raise ValueError("workflow steps required")
        for names in (self.stop_outcomes,self.wait_kinds,self.context_slots):
            if names is not None and len(names)!=len(set(names)): raise ValueError("unique workflow labels required")


@dataclass(frozen=True, kw_only=True)
class AnswerOption(SemanticValue):
    option_id: str
    description: str


@dataclass(frozen=True, kw_only=True)
class AnswerLevel(SemanticValue):
    level_id: str
    index: int
    description: str
    def __post_init__(self):
        super().__post_init__()
        if self.index < 0: raise ValueError("nonnegative answer index required")


@dataclass(frozen=True, kw_only=True)
class ChoiceVocabulary(SemanticValue):
    kind: Literal["choice"]
    options: tuple[AnswerOption, ...]
    def __post_init__(self):
        super().__post_init__()
        if not self.options: raise ValueError("answer options required")


@dataclass(frozen=True, kw_only=True)
class ScoreVocabulary(SemanticValue):
    kind: Literal["score"]
    levels: tuple[AnswerLevel, ...]
    def __post_init__(self):
        super().__post_init__()
        if not self.levels: raise ValueError("answer levels required")


@dataclass(frozen=True, kw_only=True)
class NoulVocabulary(SemanticValue):
    kind: Literal["noul"]
    true_description: str
    false_description: str


@dataclass(frozen=True, kw_only=True)
class DispositionSpec(SemanticValue):
    satisfied: Literal["pass", "block", "manual", "insufficient"]
    violated: Literal["pass", "block", "manual", "insufficient"]
    insufficient: Literal["pass", "block", "manual", "insufficient"]
    unknown: Literal["pass", "block", "manual", "insufficient"]


@dataclass(frozen=True, kw_only=True)
class ReductionSpec(SemanticValue):
    required_criteria: Literal["all_applicable"]
    empty_applicable_set: Literal["error"]
    priority: tuple[Literal["block", "manual", "pass"], ...]
    def __post_init__(self):
        super().__post_init__()
        if len(self.priority)!=3 or len(set(self.priority))!=3: raise ValueError("three unique reduction priorities required")


@dataclass(frozen=True, kw_only=True)
class OptionStatus(SemanticValue):
    option_id: str
    status: Literal["threshold_dependent", "satisfied", "violated", "insufficient", "unknown"]


@dataclass(frozen=True, kw_only=True)
class OptionStatusMap(SemanticValue):
    entries: tuple[OptionStatus, ...]
    def __post_init__(self):
        super().__post_init__()
        if len({x.option_id for x in self.entries}) != len(self.entries): raise ValueError("duplicate option status")


@dataclass(frozen=True, kw_only=True)
class DecisionPolicySpec(SemanticValue):
    calibration_profile_id: str
    activation: Literal["matching_validated_evaluation_required"]
    missing_evaluation: Literal["pass", "block", "manual", "insufficient"]
    truncation: Literal["unknown"]
    selected_option: str | None = None
    option_statuses: OptionStatusMap | None = None
    minimum_selected_probability: str | None = None
    minimum_top_level_probability: str | None = None
    maximum_p_true: str | None = None
    minimum_expected_index: str | None = None
    below_threshold: Literal["pass", "block", "manual", "insufficient"] | None = None
    above_threshold: Literal["pass", "block", "manual", "insufficient"] | None = None
    def __post_init__(self):
        super().__post_init__()
        import re
        for value in (self.minimum_selected_probability,self.minimum_top_level_probability,self.maximum_p_true,self.minimum_expected_index):
            if value is not None and re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?",value) is None: raise ValueError("decimal text required")


@dataclass(frozen=True, kw_only=True)
class CheckDefinition(SemanticValue):
    capability_id: str
    interface_version: str
    bindings: FrozenObject


@dataclass(frozen=True, kw_only=True)
class CriterionDefinition(SemanticValue):
    criterion_id: str
    statement: str
    checks: tuple[CheckDefinition, ...]
    policy: DispositionSpec
    applies_to: tuple[str, ...] | None = None
    required_inputs: tuple[str, ...] | None = None
    required: bool | None = None
    blocking: bool | None = None
    reviewer_capability: str | None = None
    answer_vocabulary: ChoiceVocabulary | ScoreVocabulary | NoulVocabulary | None = None
    decision_policy: DecisionPolicySpec | None = None
    def __post_init__(self):
        super().__post_init__()
        if not self.checks: raise ValueError("criterion checks required")
        for names in (self.applies_to,self.required_inputs):
            if names is not None and len(set(names))!=len(names): raise ValueError("unique criterion input labels required")


@dataclass(frozen=True, kw_only=True)
class StandardDefinition(SemanticValue):
    schema_version: Literal[1]
    standard_id: str
    revision: str
    criteria: tuple[CriterionDefinition, ...]
    reduction: ReductionSpec
    resource_ref: ResourceRef = field(metadata={"wire": False})
    purpose: str | None = None
    def __post_init__(self):
        super().__post_init__()
        if not self.criteria: raise ValueError("standard criteria required")


@dataclass(frozen=True, kw_only=True)
class BoundCriterion(SemanticValue):
    resource_ref: ResourceRef
    criterion_id: str


@dataclass(frozen=True, kw_only=True)
class AnswerDefinition(SemanticValue):
    from_criterion: BoundCriterion
    field: Literal["answer_vocabulary"]


@dataclass(frozen=True, kw_only=True)
class QuestionDefinition(SemanticValue):
    question_id: str
    question_revision: str
    kind: Literal["choice", "score", "noul"]
    criterion_refs: tuple[BoundCriterion, ...]
    instructions: str
    answer_definition: AnswerDefinition
    def __post_init__(self):
        super().__post_init__()
        if not self.criterion_refs: raise ValueError("question criterion references required")


@dataclass(frozen=True, kw_only=True)
class DecisionDefinition(SemanticValue):
    schema_version: Literal[1]
    question_set_id: str
    question_set_version: str
    input_mapping_version: str
    input_contract: str
    required_input_slots: tuple[str, ...]
    iteration: Literal["once", "each_evidence_required_claim"]
    questions: tuple[QuestionDefinition, ...]
    result_contract: Literal["DecisionResult.v1"]
    truncation_policy: Literal["reject"]
    missing_required_evidence: Literal["do_not_invoke"]
    resource_ref: ResourceRef = field(metadata={"wire": False})
    evidence_order: str | None = None
    def __post_init__(self):
        super().__post_init__()
        if not self.questions: raise ValueError("decision questions required")
        if len(set(self.required_input_slots))!=len(self.required_input_slots): raise ValueError("unique question inputs required")


@dataclass(frozen=True, kw_only=True)
class DocumentDefinition(SemanticValue):
    document_type: str
    schema_resource: ResourceRef
    value_schema: FrozenObject
    template_resource: ResourceRef | None = field(metadata={"keep_none": True})
    validation_target: Literal["method_content"]


@dataclass(frozen=True, kw_only=True)
class SchemaDefinition(SemanticValue):
    schema_resource: ResourceRef
    value_schema: FrozenObject


@dataclass(frozen=True, kw_only=True)
class SkillDefinition(SemanticValue):
    role: str
    resource_ref: ResourceRef


@dataclass(frozen=True, kw_only=True)
class CompiledProgram:
    """Modern typed semantic authority; encoding is only a derived wire view."""
    compiler_version: str
    workflow: WorkflowSpec
    document_definitions: tuple[DocumentDefinition, ...]
    schema_definitions: tuple[SchemaDefinition, ...]
    standard_definitions: tuple[StandardDefinition, ...]
    decision_definitions: tuple[DecisionDefinition, ...]
    skill_definitions: tuple[SkillDefinition, ...]
    capability_bindings: tuple[CapabilityBinding, ...]
    def __post_init__(self):
        SemanticValue.__post_init__(self)
        for definitions, key in ((self.standard_definitions, "standard_id"), (self.decision_definitions, "question_set_id")):
            ids = [getattr(x, key) for x in definitions]
            if len(ids) != len(set(ids)): raise ValueError("unique semantic resource identities required")
    @property
    def schema_version(self): return 2
    @property
    def engine_contract_version(self): return "ordessa.methods/v1"
    @property
    def bindings(self):
        return ProgramBindings(tuple((x.standard_id,x.resource_ref) for x in self.standard_definitions),
                               tuple((x.question_set_id,x.resource_ref) for x in self.decision_definitions))


@dataclass(frozen=True)
class HistoricalBoundProgram:
    """Explicit historical content: no modern semantic authority is fabricated."""
    encoding: HistoricalStoredProgram
    bindings: ProgramBindings
    def __post_init__(self):
        if type(self.encoding) is not HistoricalStoredProgram or type(self.bindings) is not ProgramBindings: raise TypeError("historical encoding and explicit bindings required")
        for key, pairs, id_key in (("standards",self.bindings.standards,"standard_id"), ("decision_templates",self.bindings.decisions,"question_set_id")):
            ids = [dict(x.entries)[id_key] for x in getattr(self.encoding, key)]
            if set(ids) != {name for name,_ in pairs} or len(ids) != len(pairs): raise ValueError("historical source bindings mismatch")
    @property
    def schema_version(self):return 1
    @property
    def engine_contract_version(self):return self.encoding.engine_contract_version
    @property
    def compiler_version(self):return self.encoding.compiler_version
    @property
    def capability_bindings(self):return self.encoding.capability_bindings


@dataclass(frozen=True)
class CompiledMethod:
    source_bundle: SourceBundle
    parsed_source: ParsedSourceBundle
    program: CompiledProgram
    diagnostics: tuple[errors.Diagnostic, ...] = ()
    def __post_init__(self):
        if type(self.source_bundle) is not SourceBundle or type(self.program) is not CompiledProgram:
            raise TypeError("one captured source and one typed program required")
        if type(self.parsed_source) is not ParsedSourceBundle or self.parsed_source.source_bundle is not self.source_bundle:
            raise ValueError("compiled parsed view must bind the same source bundle")
        if type(self.diagnostics) is not tuple or any(type(d) is not errors.Diagnostic for d in self.diagnostics):
            raise TypeError("immutable diagnostics required")
    @property
    def identity(self): return self.parsed_source.identity
    @property
    def source_manifest_digest(self): return self.source_bundle.manifest_digest
    @property
    def compiler_version(self): return self.program.compiler_version
