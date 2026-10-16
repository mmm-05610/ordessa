"""Typed decoding and finite validation for method-declared review groups."""
from __future__ import annotations

from dataclasses import asdict

from ..definitions.models.compiled import (
    CompiledProgram, OperationNode, WaitNode, WorkflowSpec, thaw_value,
)
from ..definitions.models.identity import ResourceRef
from ..definitions.models.review_bindings import (
    ReviewBindingSpec, ReviewGroupMember, ReviewGroupSpec, ReviewMaterialSource,
    ReviewTargetSource,
)


_GROUP_KEYS = frozenset({"contract", "group_id", "subject_slot", "target_sources",
    "material_sources", "members", "gate_wait", "required_members", "empty_members"})
_BINDING_KEYS = frozenset({"contract", "anchor_node", "group_id", "member_id"})


def _config(node):
    if type(node) not in (OperationNode,):
        return {}
    value = thaw_value(node.config)
    return value if type(value) is dict else {}


def _resource_ref(value):
    if type(value) is not dict or set(value) != {"resource_id", "sha256", "kind"}:
        raise ValueError("compiled standard resource reference required")
    if (type(value["resource_id"]) is not str or not value["resource_id"]
            or type(value["sha256"]) is not str or len(value["sha256"]) != 64
            or any(ch not in "0123456789abcdef" for ch in value["sha256"])
            or value["kind"] != "standard"):
        raise ValueError("compiled standard resource reference invalid")
    return ResourceRef(**value)


def decode_review_binding(node: OperationNode) -> ReviewBindingSpec | None:
    """Decode an exact request-node binding from an already compiled node."""
    if type(node) is not OperationNode:
        raise TypeError("compiled operation node required")
    config = _config(node)
    if "review_binding" not in config:
        return None
    raw = config["review_binding"]
    if type(raw) is not dict or set(raw) != _BINDING_KEYS:
        raise ValueError("review binding fields invalid")
    return ReviewBindingSpec(**raw)


def _decode_group(anchor_node: str, raw: object) -> ReviewGroupSpec:
    if type(raw) is not dict or set(raw) != _GROUP_KEYS:
        raise ValueError("review group fields invalid")
    targets = []
    for item in raw["target_sources"]:
        if type(item) is not dict:
            raise ValueError("review target source invalid")
        targets.append(ReviewTargetSource(**{**item, "slot": item.get("slot"),
            "document_types": tuple(item["document_types"])}))
    materials = []
    for item in raw["material_sources"]:
        if type(item) is not dict:
            raise ValueError("review material source invalid")
        materials.append(ReviewMaterialSource(**{**item, "slot": item.get("slot")}))
    members = []
    for item in raw["members"]:
        if type(item) is not dict or not {"member_id", "request_node", "plan_slot",
                "standard", "response_wait", "record_node"} <= set(item) or set(item) - {
                    "member_id", "request_node", "plan_slot", "standard", "response_wait",
                    "record_node", "advance_waits"}:
            raise ValueError("review group member fields invalid")
        members.append(ReviewGroupMember(
            member_id=item["member_id"], request_node=item["request_node"],
            plan_slot=item["plan_slot"], standard_ref=_resource_ref(item["standard"]),
            response_wait=item["response_wait"], record_node=item["record_node"],
            advance_waits=tuple(item.get("advance_waits", ()))))
    return ReviewGroupSpec(anchor_node=anchor_node,
        target_sources=tuple(targets), material_sources=tuple(materials), members=tuple(members), **{
            key: raw[key] for key in ("contract", "group_id", "subject_slot", "gate_wait",
                "required_members", "empty_members")})


def _completed_target(node):
    if type(node) is not OperationNode:
        return None
    rows = [row for row in node.outcomes.entries if row.outcome == "completed"]
    if len(rows) != 1:
        return None
    target = rows[0].target
    return target.next if target.next is not None else None


def decode_review_groups(workflow: WorkflowSpec) -> tuple[ReviewGroupSpec, ...]:
    """Decode all exact frozen review-group specs from a compiled workflow.

    The decoder is pure and definitions-layer neutral. It does not resolve
    subjects/materials or confer source authority.
    """
    if type(workflow) is not WorkflowSpec:
        raise TypeError("compiled WorkflowSpec required")
    by_id = {node.id: node for node in workflow.steps}
    if len(by_id) != len(workflow.steps):
        raise ValueError("workflow node ids must be unique")
    groups = []
    referenced_bindings = set()
    claimed_nodes = set()
    for node in workflow.steps:
        if type(node) is not OperationNode:
            continue
        config = _config(node)
        if "review_group" not in config:
            continue
        group = _decode_group(node.id, config["review_group"])
        if not group.members or group.members[0].request_node != node.id:
            raise ValueError("review group anchor must be its first request node")
        gate = by_id.get(group.gate_wait)
        if type(gate) is not WaitNode:
            raise ValueError("review group gate must name a wait node")
        group_nodes = {group.gate_wait}
        for index, member in enumerate(group.members):
            request = by_id.get(member.request_node)
            response = by_id.get(member.response_wait)
            record = by_id.get(member.record_node)
            if (type(request) is not OperationNode or request.operation != "engineering.reviews.request"
                    or type(response) is not WaitNode or type(record) is not OperationNode
                    or record.operation != "engineering.reviews.record"):
                raise ValueError("review group member node kind or operation invalid")
            member_nodes = {member.request_node, member.response_wait, member.record_node, *member.advance_waits}
            if group_nodes.intersection(member_nodes):
                raise ValueError("review group nodes must be unique")
            group_nodes.update(member_nodes)
            binding = decode_review_binding(request)
            expected_binding = ReviewBindingSpec(contract="ordessa.method-review-binding/1",
                anchor_node=node.id, group_id=group.group_id, member_id=member.member_id)
            if binding != expected_binding:
                raise ValueError("review group member binding mismatch")
            inputs = request.inputs.entries if request.inputs is not None else ()
            if (request.id in referenced_bindings or
                    len([item for item in inputs if item.name == "plan" and item.slot == member.plan_slot]) != 1):
                raise ValueError("review group plan slot or member binding invalid")
            referenced_bindings.add(request.id)
            request_config = _config(request)
            standards = request_config.get("standards")
            if (type(standards) is not list or len(standards) != 1
                    or _resource_ref(standards[0]) != member.standard_ref):
                raise ValueError("review request must name exactly its member standard")
            if _completed_target(request) != response.id or response.next != record.id:
                raise ValueError("review request/response/record path is not closed")
            if any(row.target.next is not None or row.target.wait is not None
                    for row in request.outcomes.entries if row.outcome != "completed"):
                raise ValueError("noncompleted review request outcomes must stop")
            final_member = index + 1 == len(group.members)
            if final_member and member.advance_waits:
                raise ValueError("final review member cannot declare advance waits")
            expected_next = member.advance_waits[0] if member.advance_waits else (
                group.members[index + 1].request_node if not final_member else group.gate_wait)
            if _completed_target(record) != expected_next:
                raise ValueError("review record does not advance to the declared next member/gate")
            if any(row.target.next is not None or row.target.wait is not None
                    for row in record.outcomes.entries if row.outcome != "completed"):
                raise ValueError("noncompleted review record outcomes must stop")
            for wait_index, wait_id in enumerate(member.advance_waits):
                wait = by_id.get(wait_id)
                if type(wait) is not WaitNode:
                    raise ValueError("review member advance waits must name wait nodes")
                next_node = (member.advance_waits[wait_index + 1]
                    if wait_index + 1 < len(member.advance_waits) else
                    (group.members[index + 1].request_node if not final_member else group.gate_wait))
                if wait.next != next_node:
                    raise ValueError("review member advance waits must form the declared ordered path")
        if claimed_nodes.intersection(group_nodes):
            raise ValueError("review groups cannot share workflow nodes")
        claimed_nodes.update(group_nodes)
        groups.append(group)
    if len({group.group_id for group in groups}) != len(groups):
        raise ValueError("review group ids must be unique")
    all_bindings = {node.id for node in workflow.steps if type(node) is OperationNode
        and "review_binding" in _config(node)}
    if all_bindings != referenced_bindings:
        raise ValueError("unowned or duplicate review binding declaration")
    return tuple(groups)


def validate_compiled_review_groups(program: CompiledProgram) -> None:
    """Check declaration refs and document applicability against one program."""
    if type(program) is not CompiledProgram:
        raise TypeError("compiled program required")
    groups = decode_review_groups(program.workflow)
    slots = set(program.workflow.context_slots or ())
    document_types = {item.document_type for item in program.document_definitions}
    standards = {item.resource_ref: item for item in program.standard_definitions}
    for group in groups:
        if group.subject_slot not in slots:
            raise ValueError("review group subject slot is undeclared")
        declared_types = set()
        for source in group.target_sources:
            if source.slot is not None and source.slot not in slots:
                raise ValueError("review target slot is undeclared")
            if not set(source.document_types) <= document_types:
                raise ValueError("review target document type is undeclared")
            declared_types.update(source.document_types)
        for source in group.material_sources:
            if source.slot is not None and source.slot not in slots:
                raise ValueError("review material slot is undeclared")
        for member in group.members:
            standard = standards.get(member.standard_ref)
            if standard is None:
                raise ValueError("review standard ref is outside compiled program")
            material_names = {item.name for item in group.material_sources}
            applicable_count = 0
            for criterion in standard.criteria:
                applicable = set(criterion.applies_to or ())
                if not applicable:
                    applicable = declared_types
                if not applicable & declared_types:
                    continue
                applicable_count += 1
                if not set(criterion.required_inputs or ()) <= material_names:
                    raise ValueError("review group omits a standard-required material input")
            if not declared_types or not applicable_count:
                raise ValueError("review group has an empty applicable target set")
