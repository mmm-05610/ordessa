"""Bind source reviews to exact, guarded method-owned policy resources."""
from __future__ import annotations

import json
from dataclasses import asdict
from urllib.parse import urljoin

from jsonschema import Draft202012Validator
from referencing import Resource
from referencing.jsonschema import DRAFT202012

from ordessa_engineering.application.contracts.reviewer_admission import SourceReviewBinding
from ordessa_engineering.domain.artifacts.method_binding import ExactMethodResourceRef
from ordessa_engineering.domain.artifacts.provenance import SourceRef
from ordessa_engineering.domain.common.models.values import Digest, RelativePath
from ordessa_engineering.domain.common.mechanisms.hashing import record_digest
from ordessa_engineering.domain.reviews.models import (
    AggregationPolicy, CheckKey, CheckPolicy, CriterionSetRef, ReviewPlan,
    ReviewRequirement, Target, TargetSet,
)
from ordessa_engineering.methods.definitions.models import (
    CheckDefinition, CriterionDefinition, DispositionSpec, ResourceRef,
    ReductionSpec, StandardDefinition, freeze_value,
)
from ordessa_engineering.methods.loading.parsing import parse_document
from .source_sections import CONTRACT as SECTIONS_CONTRACT


_BINDING_CONTRACT = "engineering-source-review/1"
_BINDING_CONTRACT_V2 = "engineering-source-review/2"
_REQUIRED_V2_CHECKS = (
    "source-version-preservation", "scoped-read-boundary", "evidence-support",
    "unique-record-authority", "public-call-chain", "changed-source-refusal",
    "acceptance-coverage", "declared-limitations",
)
_DECISION_CAPABILITY = "ordessa.decision.evaluate"
_DECISION_VERSION = "1.0.0"
_DISPOSITIONS = {"satisfied": "pass", "violated": "block",
                 "insufficient": "insufficient", "unknown": "insufficient"}
_OPTION_STATUSES = {"passed": "satisfied", "not_passed": "violated", "unknown": "unknown"}


def _strict_json(raw: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=pairs)
    if type(value) is not dict:
        raise ValueError("expected JSON object")
    return value


class DeclaredSourceReviewBindings:
    """Pure selector for one explicitly declared, finite source review.

    `baseline` and `candidate` are trusted local caller selections. Their
    provenance is independently read and validated by the source-material
    owner; this object only binds the exact pins into the review plan.
    """

    def __init__(self, factory, method_guard, *, scope, method_ref, baseline,
                 candidate, action_id, binding_resource_id,
                 criteria_resource_id, prompt_resource_id,
                 result_schema_resource_id, reviewer_roles,
                 caller_input_schema_resource_id=None, caller_materials_ref=None,
                 question_materials_ref=None):
        self.factory = factory
        self.method_guard = method_guard
        self.scope = scope
        self.method_ref = method_ref
        self.baseline = baseline
        self.candidate = candidate
        self.action_id = action_id
        self.binding_resource_id = binding_resource_id
        self.criteria_resource_id = criteria_resource_id
        self.prompt_resource_id = prompt_resource_id
        self.result_schema_resource_id = result_schema_resource_id
        self.caller_input_schema_resource_id = caller_input_schema_resource_id
        if caller_materials_ref is not None and type(caller_materials_ref) is not SourceRef:
            raise ValueError("SOURCE_REVIEW_MATERIAL_REF_INVALID")
        self.caller_materials_ref = caller_materials_ref
        if question_materials_ref is not None and type(question_materials_ref) is not SourceRef:
            raise ValueError("SOURCE_REVIEW_SECTION_REF_INVALID")
        self.question_materials_ref = question_materials_ref
        self.reviewer_roles = tuple(reviewer_roles)

    def plan(self, context, review_id) -> ReviewPlan:
        with self.method_guard.guard(context, self.method_ref) as definition:
            return self._build(context, review_id, definition)[0]

    def resolve_source_plan(self, context, plan, definition) -> SourceReviewBinding:
        expected, standard, _inputs = self._build(context, plan.review_id, definition)
        if plan != expected:
            raise ValueError("METHOD_REVIEW_PLAN_CHANGED")
        return SourceReviewBinding(expected, standard)

    def review_inputs(self, context, plan):
        with self.method_guard.guard(context, self.method_ref) as definition:
            expected, standard, inputs = self._build(context, plan.review_id, definition)
            if plan != expected:
                raise ValueError("METHOD_REVIEW_PLAN_CHANGED")
            return {"standard": standard, "refs": inputs["refs"],
                    "policy": inputs["policy"], "criteria": inputs["criteria"],
                    "prompt": inputs["prompt"],
                    "result_schema": inputs["result_schema"],
                    "caller_input_schema": inputs.get("caller_input_schema"),
                    "schema_documents": inputs.get("schema_documents", {}),
                    "caller_materials_ref": self.caller_materials_ref,
                    "question_materials_ref": self.question_materials_ref}

    def _build(self, context, review_id, definition):
        if context.scope != self.scope:
            raise ValueError("SOURCE_REVIEW_SCOPE_MISMATCH")
        self._check_definition(definition)
        actions = [item for item in definition.actions if item.action_id == self.action_id]
        if len(actions) != 1:
            raise ValueError("SOURCE_REVIEW_ACTION_UNAVAILABLE")
        action = actions[0]
        roles = self.reviewer_roles
        if not roles or len(set(roles)) != len(roles):
            raise ValueError("SOURCE_REVIEW_ROLES_INVALID")
        # The resulting review and caller-prepared Package share one finite
        # declaration pin set, including its declared preparation templates.
        # Resolve only resources named by the admitted immutable declaration.
        refs = {item.resource_id: self._resource(context, definition, item.resource_id)
                for item in definition.resources}
        schema_documents = {}
        pinned_documents = {}
        for declared in definition.resources:
            if declared.kind != "schema":
                continue
            exact = refs[declared.resource_id]
            document = _strict_json(self.method_guard.read_resource(context, exact))
            Draft202012Validator.check_schema(document)
            location = "https://ordessa.invalid/method/" + str(exact.logical_path)
            base = urljoin(location, document.get("$id", location))
            pinned = dict(document)
            pinned["$id"] = base
            pinned_documents[declared.resource_id] = pinned
            resource = Resource.from_contents(pinned, default_specification=DRAFT202012)
            schema_documents[location] = resource
            schema_documents[base] = resource
        # The action's own declaration is an exact method resource too.
        action_matches = []
        for action_source in (item for item in definition.resources if item.kind == "action"):
            candidate_ref = refs[action_source.resource_id]
            action_doc = parse_document(self.method_guard.read_resource(context, candidate_ref),
                                        "application/yaml", str(candidate_ref.logical_path))
            if type(action_doc) is dict and action_doc.get("action_id") == self.action_id:
                action_matches.append(candidate_ref)
        if len(action_matches) != 1:
            raise ValueError("SOURCE_REVIEW_ACTION_RESOURCE_MISMATCH")
        action_exact = action_matches[0]

        policy = _strict_json(self.method_guard.read_resource(context, refs[self.binding_resource_id]))
        contract = policy.get("contract") if type(policy) is dict else None
        v2 = contract == _BINDING_CONTRACT_V2
        expected_fields = {
            "contract", "action_id", "criterion_id", "reviewer_roles",
            "criteria_resource_id", "prompt_resource_id", "result_schema_resource_id",
            "check", "options", "dispositions",
        }
        if v2:
            expected_fields |= {"caller_input_schema_resource_id", "evaluation_scope",
                                 "aggregation", "required_checks"}
        if set(policy) != expected_fields or contract not in {_BINDING_CONTRACT, _BINDING_CONTRACT_V2}:
            raise ValueError("SOURCE_REVIEW_BINDING_INVALID")
        if (policy["action_id"] != self.action_id
                or policy["criteria_resource_id"] != self.criteria_resource_id
                or policy["prompt_resource_id"] != self.prompt_resource_id
                or policy["result_schema_resource_id"] != self.result_schema_resource_id
                or tuple(policy["reviewer_roles"]) != roles):
            raise ValueError("SOURCE_REVIEW_BINDING_MISMATCH")
        if v2 and (policy["caller_input_schema_resource_id"] != self.caller_input_schema_resource_id
                   or self.caller_input_schema_resource_id is None
                   or type(self.caller_materials_ref) is not SourceRef
                   or policy["evaluation_scope"] != "baseline_candidate_pair"):
            raise ValueError("SOURCE_REVIEW_MATERIALS_REQUIRED")
        if not v2 and (self.caller_input_schema_resource_id is not None
                       or self.caller_materials_ref is not None
                       or self.question_materials_ref is not None):
            raise ValueError("SOURCE_REVIEW_V1_MATERIALS_UNSUPPORTED")
        check = policy["check"]
        if (type(check) is not dict or check != {"capability_id": _DECISION_CAPABILITY,
                                                "interface_version": _DECISION_VERSION}):
            raise ValueError("SOURCE_REVIEW_CHECK_UNSUPPORTED")
        options = policy["options"]
        if (type(options) is not dict or set(options) != set(_OPTION_STATUSES)
                or any(type(options[key]) is not dict
                       or set(options[key]) != {"description", "status"}
                       or options[key]["status"] != _OPTION_STATUSES[key]
                       or type(options[key]["description"]) is not str
                       or not options[key]["description"] for key in options)):
            raise ValueError("SOURCE_REVIEW_OPTIONS_INVALID")
        if policy["dispositions"] != _DISPOSITIONS:
            raise ValueError("SOURCE_REVIEW_DISPOSITIONS_INVALID")

        criteria = self.method_guard.read_resource(context, refs[self.criteria_resource_id]).decode("utf-8", "strict")
        prompt = self.method_guard.read_resource(context, refs[self.prompt_resource_id]).decode("utf-8", "strict")
        # Use the pinned copies so a relative $ref between method schema
        # resources resolves against their declared method location; the raw
        # resource bytes carry no base and would be unresolvable.
        result_schema = pinned_documents[self.result_schema_resource_id]
        caller_input_schema = None
        if v2:
            caller_input_schema = pinned_documents[self.caller_input_schema_resource_id]
            self._validate_v2_input_schema(caller_input_schema)
            self._validate_v2_result_schema(result_schema)
        else:
            self._validate_result_schema(result_schema)
        criterion_id = policy["criterion_id"]
        if type(criterion_id) is not str or not criterion_id:
            raise ValueError("SOURCE_REVIEW_CRITERION_INVALID")

        # Exact source_binding is attached to the public decision capability.
        bound_ref = refs[self.binding_resource_id]
        # Kept as a plain mapping: the v2 declaration derives one finite frozen
        # copy per required check, and v1 freezes its single copy below. Freezing
        # here first would make that per-check composition unable to unpack.
        binding = {"kind": "source_binding", "action_id": self.action_id,
                   "resource_ref": {
                       "method_ref": {
                           "method_id": str(bound_ref.method_ref.method_id),
                           "release_version": bound_ref.method_ref.release_version,
                           "schema_version": bound_ref.method_ref.schema_version,
                           "snapshot_digest": bound_ref.method_ref.snapshot_digest.hex,
                       },
                       "logical_path": str(bound_ref.logical_path),
                       "resource_digest": bound_ref.resource_digest.hex,
                       "resource_id": bound_ref.resource_id,
                   }}
        representation = None if self.question_materials_ref is None else {
            "contract": SECTIONS_CONTRACT,
            "question_materials_ref": asdict(self.question_materials_ref),
        }
        if representation is not None:
            binding["input_representation"] = representation
        derived_version = 3 if representation is not None else (2 if v2 else 1)
        standard_id = f"{self.action_id}-source-review"
        if representation is not None:
            # CriterionSet.digest remains the actual method resource digest:
            # the original admission guard verifies that exact resource. The
            # derived standard identity pins host context without inventing a
            # replacement method resource or weakening that guard.
            standard_id += '-' + record_digest('source-review-input', representation).hex
        check_definitions = policy.get("required_checks") if v2 else None
        if v2:
            if (type(check_definitions) is not list or len(check_definitions) != len(_REQUIRED_V2_CHECKS)
                    or tuple(item.get("check_id") for item in check_definitions
                             if type(item) is dict) != _REQUIRED_V2_CHECKS
                    or any(set(item) != {"check_id", "statement", "question_text", "evaluation_scope"}
                           or item["evaluation_scope"] != "baseline_candidate_pair"
                           or not all(type(item[k]) is str and item[k].strip()
                                      for k in ("check_id", "statement", "question_text"))
                           for item in check_definitions)):
                raise ValueError("SOURCE_REVIEW_REQUIRED_CHECKS_INVALID")
            if policy["aggregation"] != {
                "policy": "all_required", "missing_input": "reject_before_invocation",
                "any_not_passed": "not_passed", "otherwise_any_unknown": "unknown",
                "pass_requires": "all_required_checks_passed_with_required_materials"}:
                raise ValueError("SOURCE_REVIEW_AGGREGATION_INVALID")
            criteria_defs = tuple(CriterionDefinition(
                criterion_id=item["check_id"],
                statement=f"{item['statement']}\n\n{item['question_text']}\n\n{prompt}",
                checks=(CheckDefinition(capability_id=_DECISION_CAPABILITY,
                                        interface_version=_DECISION_VERSION,
                                        bindings=freeze_value({**binding, "check_id": item["check_id"]})),),
                policy=DispositionSpec(satisfied="pass", violated="block",
                                       insufficient="insufficient", unknown="insufficient"),
            ) for item in check_definitions)
        else:
            criteria_defs = (CriterionDefinition(
                criterion_id=criterion_id,
                statement=f"{criteria}\n\n{prompt}",
                checks=(CheckDefinition(capability_id=_DECISION_CAPABILITY,
                                        interface_version=_DECISION_VERSION,
                                        bindings=freeze_value(binding)),),
                policy=DispositionSpec(satisfied="pass", violated="block",
                                       insufficient="insufficient", unknown="insufficient"),
            ),)
        standard = StandardDefinition(
            schema_version=1, standard_id=standard_id,
            revision=str(derived_version), criteria=criteria_defs,
            reduction=ReductionSpec(required_criteria="all_applicable",
                                    empty_applicable_set="error",
                                    priority=("block", "manual", "pass")),
            resource_ref=ResourceRef(self.binding_resource_id,
                                     refs[self.binding_resource_id].resource_digest.hex,
                                     "criteria"), purpose="provenance_support",
        )
        targets = TargetSet((Target.external("base", self.scope, self.baseline),
                             Target.external("proposed", self.scope, self.candidate)))
        criterion_ids = _REQUIRED_V2_CHECKS if v2 else (criterion_id,)
        keys = tuple(CheckKey(target, check_id) for check_id in criterion_ids
                     for target in targets.targets)
        requirement = ReviewRequirement(
            scope=self.scope, requirement_id=f"{self.action_id}-source-review",
            requirement_version=derived_version, purpose="provenance_support",
            expected_targets=targets, method_ref=self.method_ref,
            criterion_set_ref=CriterionSetRef(standard.standard_id, derived_version, self._digest(bound_ref)),
            required_check_keys=keys, eligible_reviewer_roles=roles,
            phase_key=self.action_id, schema_version=2,
            method_resource_refs=tuple(refs.values()),
        )
        plan = ReviewPlan(review_id, requirement,
                          tuple(CheckPolicy(key, True, True) for key in keys),
                          AggregationPolicy(), roles)
        return plan, standard, {"refs": requirement.method_resource_refs,
                                "policy": policy, "criteria": criteria,
                                "prompt": prompt, "result_schema": result_schema,
                                "caller_input_schema": caller_input_schema,
                                "schema_documents": schema_documents,
                                "options": options}

    def _resource(self, context, definition, resource_id):
        declared = {item.resource_id: item for item in definition.resources}
        source = declared.get(resource_id)
        if source is None:
            raise ValueError("SOURCE_REVIEW_RESOURCE_UNDECLARED")
        expected_kind = {
            self.binding_resource_id: "criteria",
            self.criteria_resource_id: "criteria",
            self.prompt_resource_id: "prompt",
            self.result_schema_resource_id: "schema",
            self.caller_input_schema_resource_id: "schema",
        }.get(resource_id)
        if expected_kind is not None and source.kind != expected_kind:
            raise ValueError("SOURCE_REVIEW_RESOURCE_KIND_MISMATCH")
        exact = self.method_guard.resource_ref(context, self.method_ref, resource_id)
        if (type(exact) is not ExactMethodResourceRef or exact.method_ref != self.method_ref
                or exact.resource_id != resource_id or exact.resource_digest.hex != source.sha256):
            raise ValueError("SOURCE_REVIEW_RESOURCE_MISMATCH")
        return exact

    def _check_definition(self, definition):
        snapshot_ref = definition.method_ref
        if (snapshot_ref.method_id != str(self.method_ref.method_id)
                or snapshot_ref.release_version != self.method_ref.release_version
                or snapshot_ref.schema_version != self.method_ref.schema_version
                or snapshot_ref.snapshot_digest != self.method_ref.snapshot_digest.hex
                or definition.method_id != str(self.method_ref.method_id)
                or definition.release_version != self.method_ref.release_version):
            raise ValueError("METHOD_DECLARATION_CHANGED")
        if self.baseline.content_identity == self.candidate.content_identity:
            raise ValueError("SOURCE_REVIEW_SOURCES_IDENTICAL")

    @staticmethod
    def _digest(ref):
        return Digest("sha256", ref.resource_digest.hex)

    @staticmethod
    def _validate_result_schema(schema):
        props = schema.get("properties") if type(schema) is dict else None
        if (schema.get("type") != "object" or type(props) is not dict
                or not {"completion", "conclusion"} <= set(schema.get("required", ()))
                or props.get("completion", {}).get("enum") != ["completed", "cancelled", "unknown"]
                or props.get("conclusion", {}).get("enum") != ["passed", "not_passed", "unknown"]):
            raise ValueError("SOURCE_REVIEW_RESULT_SCHEMA_INVALID")

    @staticmethod
    def _validate_v2_input_schema(schema):
        props = schema.get("properties") if type(schema) is dict else None
        checks = props.get("checks", {}) if type(props) is dict else {}
        items = checks.get("items", {}) if type(checks) is dict else {}
        check_props = items.get("properties", {}) if type(items) is dict else {}
        evidence = check_props.get("evidence", {}) if type(check_props) is dict else {}
        evidence_item = evidence.get("items", {}) if type(evidence) is dict else {}
        if (schema.get("type") != "object" or schema.get("additionalProperties") is not False
                or set(schema.get("required", ())) != {"scope", "baseline", "candidate", "checks"}
                or not isinstance(checks, dict) or checks.get("minItems") != 8
                or checks.get("maxItems") != 8 or not isinstance(items, dict)
                or items.get("additionalProperties") is not False
                or set(items.get("required", ())) != {"check_id", "claim", "evidence"}
                or check_props.get("check_id", {}).get("enum") != list(_REQUIRED_V2_CHECKS)
                or check_props.get("claim", {}).get("minLength") != 1
                or evidence.get("minItems") != 1 or evidence_item.get("additionalProperties") is not False
                or set(evidence_item.get("required", ())) != {"source_ref", "excerpt"}
                or evidence_item.get("properties", {}).get("excerpt", {}).get("minLength") != 1):
            raise ValueError("SOURCE_REVIEW_INPUT_SCHEMA_INVALID")

    @staticmethod
    def _validate_v2_result_schema(schema):
        props = schema.get("properties") if type(schema) is dict else None
        checks = props.get("checks", {}) if type(props) is dict else {}
        items = checks.get("items", {}) if type(checks) is dict else {}
        item_props = items.get("properties", {}) if type(items) is dict else {}
        evidence = item_props.get("evidence", {}) if type(item_props) is dict else {}
        evidence_item = evidence.get("items", {}) if type(evidence) is dict else {}
        if (schema.get("type") != "object" or schema.get("additionalProperties") is not False
                or set(schema.get("required", ())) != {"scope", "baseline", "candidate", "checks", "aggregate"}
                or checks.get("minItems") != 8 or checks.get("maxItems") != 8
                or items.get("additionalProperties") is not False
                or set(items.get("required", ())) != {"check_id", "claim", "evidence", "native_run_ref",
                    "question_digest", "answer_digest", "choice"}
                or item_props.get("check_id", {}).get("enum") != list(_REQUIRED_V2_CHECKS)
                or item_props.get("choice", {}).get("enum") != ["passed", "not_passed", "unknown"]
                or item_props.get("question_digest", {}).get("pattern") != "^sha256:[0-9a-f]{64}$"
                or item_props.get("answer_digest", {}).get("pattern") != "^sha256:[0-9a-f]{64}$"
                or evidence.get("minItems") != 1 or evidence_item.get("additionalProperties") is not False
                or set(evidence_item.get("required", ())) != {"source_ref", "excerpt"}
                or props.get("aggregate", {}).get("properties", {}).get("policy", {}).get("const") != "all_required"
                or props.get("aggregate", {}).get("properties", {}).get("conclusion", {}).get("enum") !=
                    ["passed", "not_passed", "unknown"]):
            raise ValueError("SOURCE_REVIEW_RESULT_SCHEMA_INVALID")

