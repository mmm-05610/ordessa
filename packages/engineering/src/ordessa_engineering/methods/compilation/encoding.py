"""Sole method-program external encoding, semantic decoding and derived views."""
from __future__ import annotations
from dataclasses import asdict, fields, MISSING
from typing import Any, Union, get_type_hints
from ..definitions.models.compiled import (
    FrozenObject,
    SlotBinding,
    Transition,
    CompiledNode,
    TargetSelector,
    DispositionPolicy,
    ReductionPolicy,
    DecisionPolicy,
    CheckSpec,
    CriteriaSpec,
    CriterionRef,
    QuestionSpec,
    DecisionSpec,
    DocumentSpec,
    SkillSpec,
    StoredProgram,
    HistoricalStoredProgram,
    CurrentStoredProgram,
    ProgramBindings,
    SemanticValue,
    TransitionTarget,
    SlotMap,
    OutcomeBinding,
    OutcomeMap,
    OperationNode,
    WaitNode,
    StopNode,
    WorkflowSpec,
    AnswerOption,
    AnswerLevel,
    ChoiceVocabulary,
    ScoreVocabulary,
    NoulVocabulary,
    DispositionSpec,
    ReductionSpec,
    OptionStatus,
    OptionStatusMap,
    DecisionPolicySpec,
    CheckDefinition,
    CriterionDefinition,
    StandardDefinition,
    BoundCriterion,
    AnswerDefinition,
    QuestionDefinition,
    DecisionDefinition,
    DocumentDefinition,
    SchemaDefinition,
    SkillDefinition,
    CompiledProgram,
    HistoricalBoundProgram,
    CompiledMethod,
    freeze_value, thaw_value, _typecheck, ResourceRef, CapabilityBinding,
    CRITERION_DEFAULTS_V1, SlotBinding, Transition,
)
from ..definitions.models.identity import method_digest

def _stored_to_canonical(program):
    from dataclasses import asdict
    value = {"schema_version": program.schema_version, "compiler_version": program.compiler_version,
             "workflow": thaw_value(program.workflow),
             **{key: [thaw_value(item) for item in getattr(program, key)] for key in
                ("documents", "standards", "decision_templates", "skill_resources")},
             "capability_bindings": [asdict(item) for item in program.capability_bindings]}
    if isinstance(program, CurrentStoredProgram):
        value["schema_resources"] = [thaw_value(item) for item in program.schema_resources]
    return value

def stored_program_from_canonical( value):
    version = value["schema_version"]
    if type(version) is not int or version not in (1, 2):
        raise ValueError("unsupported program version")
    keys = {"schema_version", "compiler_version", "workflow", "documents", "standards",
            "decision_templates", "skill_resources", "capability_bindings"}
    if version == 2: keys.add("schema_resources")
    if set(value) != keys: raise ValueError("program fields differ from its version contract")
    common = (version, value["compiler_version"], freeze_value(value["workflow"]),
              *(tuple(freeze_value(item) for item in value[key]) for key in
                ("documents", "standards", "decision_templates", "skill_resources")),
              tuple(CapabilityBinding(**item) for item in value["capability_bindings"]))
    if version == 1: return HistoricalStoredProgram(*common)
    if version == 2: return CurrentStoredProgram(*common, tuple(freeze_value(item) for item in value["schema_resources"]))
    raise ValueError("unsupported program version")

def _parse_semantic(value, hint):
    from typing import get_origin, get_args
    from types import UnionType
    origin, args = get_origin(hint), get_args(hint)
    if origin in (UnionType, Union):
        for child in args:
            try: return _parse_semantic(value, child)
            except (TypeError, ValueError, KeyError): pass
        raise ValueError("semantic union shape invalid")
    if origin is tuple:
        if type(value) is not list: raise TypeError("semantic array required")
        if len(args) == 2 and args[1] is Ellipsis: return tuple(_parse_semantic(v, args[0]) for v in value)
        if len(value) != len(args): raise ValueError("semantic tuple shape invalid")
        return tuple(_parse_semantic(v, h) for v, h in zip(value, args))
    if hint is FrozenObject:
        if type(value) is not dict: raise TypeError("contract object required")
        return freeze_value(value)
    if hint is ResourceRef:
        if type(value) is not dict or set(value) != {"resource_id", "sha256", "kind"}: raise ValueError("exact resource reference required")
        result = ResourceRef(**value);_typecheck(result, ResourceRef);return result
    if isinstance(hint, type) and issubclass(hint, SemanticValue): return semantic_from_wire(hint, value)
    _typecheck(value, hint);return value

def _semantic_wire(value):
    from dataclasses import asdict
    if isinstance(value, SemanticValue): return semantic_to_wire(value)
    if isinstance(value, ResourceRef): return asdict(value)
    if isinstance(value, FrozenObject): return thaw_value(value)
    if type(value) is tuple: return [_semantic_wire(v) for v in value]
    return value

def semantic_from_wire(cls, value, **source_fields):
    if cls is SlotMap:
        if type(value) is not dict: raise TypeError("slot object required")
        return cls(entries=tuple(SlotBinding(k, v) for k, v in sorted(value.items())))
    if cls is OutcomeMap:
        if type(value) is not dict: raise TypeError("outcome object required")
        return cls(entries=tuple(OutcomeBinding(outcome=k, target=semantic_from_wire(TransitionTarget, v)) for k,v in sorted(value.items())))
    if cls is OptionStatusMap:
        if type(value) is not dict: raise TypeError("option statuses object required")
        return cls(entries=tuple(OptionStatus(option_id=k,status=v) for k,v in sorted(value.items())))
    from dataclasses import fields, MISSING
    from typing import get_type_hints
    if type(value) is not dict: raise TypeError("semantic object required")
    fs = fields(cls); hints = get_type_hints(cls)
    names = {f.metadata.get("wire_name", f.name) for f in fs if f.metadata.get("wire", True)}
    if set(value) - names: raise ValueError("unknown semantic fields")
    kwargs = dict(source_fields)
    for f in fs:
        if not f.metadata.get("wire", True): continue
        name = f.metadata.get("wire_name", f.name)
        if name in value:
            if value[name] is None and not f.metadata.get("keep_none", False):
                raise ValueError("explicit null is not a semantic omission")
            kwargs[f.name] = _parse_semantic(value[name], hints[f.name])
        elif f.default is MISSING and f.default_factory is MISSING: raise ValueError("missing semantic field: " + name)
    return cls(**kwargs)

def semantic_to_wire(value):
    if isinstance(value, SlotMap): return {x.name:x.slot for x in value.entries}
    if isinstance(value, OutcomeMap): return {x.outcome:semantic_to_wire(x.target) for x in value.entries}
    if isinstance(value, OptionStatusMap): return {x.option_id:x.status for x in value.entries}
    from dataclasses import fields
    return {f.metadata.get("wire_name", f.name): _semantic_wire(getattr(value, f.name))
            for f in fields(value) if f.metadata.get("wire", True)
            and (getattr(value, f.name) is not None or f.metadata.get("keep_none", False))}

def _compiled_to_canonical(program):
    from dataclasses import asdict
    return {"schema_version":2,"compiler_version":program.compiler_version,"workflow":semantic_to_wire(program.workflow),
            "documents":[semantic_to_wire(x) for x in program.document_definitions],
            "schema_resources":[semantic_to_wire(x) for x in program.schema_definitions],
            "standards":[semantic_to_wire(x) for x in program.standard_definitions],
            "decision_templates":[semantic_to_wire(x) for x in program.decision_definitions],
            "skill_resources":[semantic_to_wire(x) for x in program.skill_definitions],
            "capability_bindings":[asdict(x) for x in program.capability_bindings]}

def program_to_canonical(program):
    if type(program) is CompiledProgram: return _compiled_to_canonical(program)
    if type(program) is HistoricalBoundProgram: return _stored_to_canonical(program.encoding)
    if type(program) in (StoredProgram, HistoricalStoredProgram, CurrentStoredProgram): return _stored_to_canonical(program)
    raise TypeError("typed program required")

def program_plan_digest(program):
    return method_digest("compiled-method-program", program_to_canonical(program))

def program_encoding(program):
    if type(program) is HistoricalBoundProgram: return program.encoding
    if type(program) in (StoredProgram, HistoricalStoredProgram, CurrentStoredProgram): return program
    return stored_program_from_canonical(program_to_canonical(program))

def compiled_program_from_canonical( value, bindings):
    encoding = stored_program_from_canonical(value)
    if encoding.schema_version != 2: raise ValueError("modern typed program requires schema2")
    if type(bindings) is not ProgramBindings: raise TypeError("exact source bindings required")
    def bind(values,pairs,id_key,typ):
        refs=dict(pairs)
        if len(refs)!=len(pairs) or len(values)!=len(pairs) or {x[id_key] for x in values} != set(refs): raise ValueError("semantic source bindings mismatch")
        return tuple(semantic_from_wire(typ,x,resource_ref=refs[x[id_key]]) for x in values)
    result=CompiledProgram(compiler_version=value["compiler_version"],workflow=semantic_from_wire(WorkflowSpec,value["workflow"]),
        document_definitions=tuple(semantic_from_wire(DocumentDefinition,x) for x in value["documents"]),
        schema_definitions=tuple(semantic_from_wire(SchemaDefinition,x) for x in value["schema_resources"]),
        standard_definitions=bind(value["standards"],bindings.standards,"standard_id",StandardDefinition),
        decision_definitions=bind(value["decision_templates"],bindings.decisions,"question_set_id",DecisionDefinition),
        skill_definitions=tuple(semantic_from_wire(SkillDefinition,x) for x in value["skill_resources"]),
        capability_bindings=encoding.capability_bindings)
    if program_to_canonical(result) != value: raise ValueError("typed program serialization is lossy")
    return result

def _historical_program_entry(program): return program_to_canonical(program)["workflow"]["entry"]

def _historical_program_nodes(program):
    def slots(value): return tuple(SlotBinding(key, child) for key, child in sorted(value.items()))
    return tuple(CompiledNode(n["id"], n["kind"], n.get("operation"), n.get("event"), n.get("next"),
        n.get("outcome"), slots(n.get("inputs", {})), slots(n.get("bind", {})), slots(n.get("match", {})),
        tuple(Transition(k, next(iter(v)), next(iter(v.values()))) for k, v in sorted(n.get("outcomes", {}).items())),
        freeze_value(n.get("config", {}))) for n in program_to_canonical(program)["workflow"]["steps"])

def _historical_program_criteria(program):
    result = []
    refs = dict(program.bindings.standards)
    for standard in program_to_canonical(program)["standards"]:
        for c in standard["criteria"]:
            vocab = c.get("answer_vocabulary")
            dp = c.get("decision_policy")
            decision = None if dp is None else DecisionPolicy(vocab["kind"], dp["calibration_profile_id"], dp["activation"],
                tuple((k, dp[k]) for k in ("minimum_selected_probability", "minimum_top_level_probability", "maximum_p_true", "minimum_expected_index") if k in dp),
                dp.get("selected_option"), tuple(sorted(dp.get("option_statuses", {}).items())), dp.get("below_threshold"), dp.get("above_threshold"), dp["missing_evaluation"], dp["truncation"])
            result.append(CriteriaSpec(refs[standard["standard_id"]], standard["revision"], c["criterion_id"], c["statement"],
                TargetSelector(tuple(c.get("applies_to", CRITERION_DEFAULTS_V1["applies_to"]))), tuple(c.get("required_inputs", CRITERION_DEFAULTS_V1["required_inputs"])), c.get("required", CRITERION_DEFAULTS_V1["required"]), c.get("blocking", CRITERION_DEFAULTS_V1["blocking"]), c.get("reviewer_capability"),
                tuple(CheckSpec(x["capability_id"], x["interface_version"], freeze_value(x["bindings"])) for x in c["checks"]),
                DispositionPolicy(**c["policy"]), ReductionPolicy(standard["reduction"]["required_criteria"], standard["reduction"]["empty_applicable_set"], tuple(standard["reduction"]["priority"])),
                freeze_value(vocab) if vocab else None, decision))
    return tuple(result)

def _historical_program_decisions(program):
    def ref(value): return CriterionRef(ResourceRef(**value["resource_ref"]), value["criterion_id"])
    criteria = {(item.standard_ref, item.criterion_id): item for item in _historical_program_criteria(program)}
    result = []
    refs = dict(program.bindings.decisions)
    for d in program_to_canonical(program)["decision_templates"]:
        questions = []
        for q in d["questions"]:
            origin = ref(q["answer_definition"]["from_criterion"])
            questions.append(QuestionSpec(q["question_id"], q["question_revision"], q["kind"], tuple(ref(x) for x in q["criterion_refs"]), q["instructions"], origin, criteria[(origin.standard_ref, origin.criterion_id)].answer_vocabulary))
        result.append(DecisionSpec(refs[d["question_set_id"]], d["question_set_id"], d["question_set_version"], d["input_contract"], d["input_mapping_version"], tuple(d["required_input_slots"]), d["iteration"], tuple(questions), d["result_contract"], d["truncation_policy"], d["missing_required_evidence"], d.get("evidence_order")))
    return tuple(result)

def _historical_program_documents(program):
    if program.schema_version != 2: raise ValueError("historical document bindings unavailable")
    return tuple(DocumentSpec(d["document_type"], ResourceRef(**d["schema_resource"]), freeze_value(d["value_schema"]), ResourceRef(**d["template_resource"]) if d["template_resource"] else None, d["validation_target"]) for d in program_to_canonical(program)["documents"])

def _historical_program_skills(program):
    if program.schema_version != 2: raise ValueError("historical skill roles unavailable")
    return tuple(SkillSpec(d["role"], ResourceRef(**d["resource_ref"])) for d in program_to_canonical(program)["skill_resources"])



def program_entry(program):
    if type(program) is CompiledProgram:
        return program.workflow.entry
    return _historical_program_entry(program)

def program_nodes(program):
    if type(program) is not CompiledProgram:
        return _historical_program_nodes(program)
    result = []
    for node in program.workflow.steps:
        if type(node) is OperationNode:
            transitions = []
            for binding in sorted(node.outcomes.entries, key=lambda item: item.outcome):
                target = binding.target
                kind, value = next((kind, getattr(target, kind)) for kind in ("next", "wait", "stop") if getattr(target, kind) is not None)
                transitions.append(Transition(binding.outcome, kind, value))
            result.append(CompiledNode(node.id, node.kind, operation=node.operation,
                inputs=tuple(sorted(node.inputs.entries, key=lambda item: item.name)) if node.inputs is not None else (),
                transitions=tuple(transitions), config=node.config if node.config is not None else FrozenObject()))
        elif type(node) is WaitNode:
            result.append(CompiledNode(node.id, node.kind, event=node.event, next_node=node.next,
                bindings=tuple(sorted(node.bind.entries, key=lambda item: item.name)) if node.bind is not None else (),
                matches=tuple(sorted(node.match.entries, key=lambda item: item.name)) if node.match is not None else ()))
        elif type(node) is StopNode:
            result.append(CompiledNode(node.id, node.kind, stop_outcome=node.outcome))
        else:
            raise TypeError("typed workflow node required")
    return tuple(result)

def program_criteria(program):
    if type(program) is not CompiledProgram:
        return _historical_program_criteria(program)
    result = []
    for standard in program.standard_definitions:
        reduction = standard.reduction
        for criterion in standard.criteria:
            policy = criterion.policy
            decision = criterion.decision_policy
            vocabulary = criterion.answer_vocabulary
            decision_view = None
            if decision is not None:
                thresholds = tuple((key, getattr(decision, key)) for key in
                    ("minimum_selected_probability", "minimum_top_level_probability", "maximum_p_true", "minimum_expected_index")
                    if getattr(decision, key) is not None)
                decision_view = DecisionPolicy(vocabulary.kind, decision.calibration_profile_id, decision.activation,
                    thresholds, decision.selected_option,
                    tuple((item.option_id, item.status) for item in sorted(decision.option_statuses.entries, key=lambda item: item.option_id)) if decision.option_statuses is not None else (),
                    decision.below_threshold, decision.above_threshold, decision.missing_evaluation, decision.truncation)
            result.append(CriteriaSpec(standard.resource_ref, standard.revision, criterion.criterion_id, criterion.statement,
                TargetSelector(criterion.applies_to if criterion.applies_to is not None else CRITERION_DEFAULTS_V1["applies_to"]),
                criterion.required_inputs if criterion.required_inputs is not None else CRITERION_DEFAULTS_V1["required_inputs"],
                criterion.required if criterion.required is not None else CRITERION_DEFAULTS_V1["required"],
                criterion.blocking if criterion.blocking is not None else CRITERION_DEFAULTS_V1["blocking"],
                criterion.reviewer_capability,
                tuple(CheckSpec(check.capability_id, check.interface_version, check.bindings) for check in criterion.checks),
                DispositionPolicy(policy.satisfied, policy.violated, policy.insufficient, policy.unknown),
                ReductionPolicy(reduction.required_criteria, reduction.empty_applicable_set, reduction.priority),
                freeze_value(semantic_to_wire(vocabulary)) if vocabulary is not None else None, decision_view))
    return tuple(result)

def program_decisions(program):
    if type(program) is not CompiledProgram:
        return _historical_program_decisions(program)
    criteria = {(item.standard_ref, item.criterion_id): item for item in program_criteria(program)}
    result = []
    for decision in program.decision_definitions:
        questions = []
        for question in decision.questions:
            source = question.answer_definition.from_criterion
            origin = CriterionRef(source.resource_ref, source.criterion_id)
            questions.append(QuestionSpec(question.question_id, question.question_revision, question.kind,
                tuple(CriterionRef(ref.resource_ref, ref.criterion_id) for ref in question.criterion_refs),
                question.instructions, origin, criteria[(origin.standard_ref, origin.criterion_id)].answer_vocabulary))
        result.append(DecisionSpec(decision.resource_ref, decision.question_set_id, decision.question_set_version,
            decision.input_contract, decision.input_mapping_version, decision.required_input_slots, decision.iteration,
            tuple(questions), decision.result_contract, decision.truncation_policy, decision.missing_required_evidence, decision.evidence_order))
    return tuple(result)

def program_documents(program):
    if type(program) is not CompiledProgram:
        return _historical_program_documents(program)
    return tuple(DocumentSpec(item.document_type, item.schema_resource, item.value_schema, item.template_resource, item.validation_target)
                 for item in program.document_definitions)

def program_skills(program):
    if type(program) is not CompiledProgram:
        return _historical_program_skills(program)
    return tuple(SkillSpec(item.role, item.resource_ref) for item in program.skill_definitions)
