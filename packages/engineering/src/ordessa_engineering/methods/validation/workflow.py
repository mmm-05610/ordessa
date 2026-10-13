"""Finite workflow validation; this module never interprets or runs a node."""
from __future__ import annotations

from collections import deque
import re
from typing import Any, Mapping

from ..definitions.errors import Diagnostic
from ..definitions.models import CapabilityDescriptor, LoadLimits, LoadedMethod


def validate_workflow(loaded: LoadedMethod, capabilities: Mapping[str, CapabilityDescriptor],
                      limits: LoadLimits) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    entry_ref = loaded.manifest["entry"]["resource"]
    workflow = loaded.resources.get(entry_ref)
    candidates = [item for item in loaded.resources.values() if item.declaration.get("kind") == "workflow"]
    if workflow is None or workflow.declaration.get("kind") != "workflow" or len(candidates) != 1:
        return [Diagnostic("WORKFLOW_RESOURCE_INVALID", "error", "entry must reference the sole workflow resource")]
    value = workflow.value
    path = workflow.captured.logical_path
    steps = value["steps"]
    if len(steps) > limits.workflow_steps:
        return [Diagnostic("WORKFLOW_STEP_COUNT_INVALID", "error", "workflow exceeds its configured step limit", workflow.declaration["id"], path, "/steps")]
    by_id: dict[str, dict[str, Any]] = {}
    for index, step in enumerate(steps):
        if step["id"] in by_id:
            diagnostics.append(Diagnostic("DUPLICATE_WORKFLOW_STEP", "error", f"duplicate step id {step['id']}", workflow.declaration["id"], path, f"/steps/{index}/id"))
        by_id[step["id"]] = step
    entry = value.get("entry")
    if entry not in by_id:
        diagnostics.append(Diagnostic("WORKFLOW_ENTRY_MISSING", "error", "workflow entry does not resolve", workflow.declaration["id"], path, "/entry"))
    stop_outcomes = value.get("stop_outcomes")
    wait_kinds = value.get("wait_kinds")
    edges: dict[str, set[str]] = {key: set() for key in by_id}
    requirements = loaded.manifest.get("requires", [])
    required_capabilities = {
        item.get("capability_id") for item in requirements if isinstance(item, dict)
    } if isinstance(requirements, list) else set()
    slots = set(value.get("context_slots", []))
    outputs = value.get("outputs")
    if outputs is not None:
        for name, slot in outputs.items():
            if slot not in slots:
                diagnostics.append(Diagnostic("WORKFLOW_OUTPUT_SLOT_UNKNOWN", "error", "declared output must reference a declared context slot", workflow.declaration["id"], path, f"/outputs/{name}"))

    # Keep edge provenance long enough to remove only explicitly counted edges
    # from the graph used for the acyclicity check.
    counted_edges: set[tuple[str, str]] = set()

    def add_transition(source: str, outcome: str, transition: Any, pointer: str) -> None:
        if not isinstance(transition, dict):
            diagnostics.append(Diagnostic("WORKFLOW_TRANSITION_INVALID", "error", "transition must be an object", workflow.declaration["id"], path, pointer))
            return
        if set(transition) == {"next"}:
            target = transition["next"]
            edges[source].add(target)
        elif set(transition) == {"wait"}:
            if not isinstance(transition["wait"], str) or transition["wait"] not in wait_kinds:
                diagnostics.append(Diagnostic("UNKNOWN_WAIT_KIND", "error", "transition uses an unregistered wait kind", workflow.declaration["id"], path, pointer))
        elif set(transition) == {"stop"}:
            if not isinstance(transition["stop"], str) or transition["stop"] not in stop_outcomes:
                diagnostics.append(Diagnostic("UNKNOWN_STOP_OUTCOME", "error", "transition uses an unregistered stop outcome", workflow.declaration["id"], path, pointer))
        else:
            diagnostics.append(Diagnostic("WORKFLOW_TRANSITION_INVALID", "error", "transition must be exactly one of next, wait, or stop", workflow.declaration["id"], path, pointer))

    for step_id, step in by_id.items():
        for key, source in {**step.get("inputs", {}), **step.get("match", {})}.items():
            if source not in slots:
                diagnostics.append(Diagnostic("WORKFLOW_CONTEXT_UNKNOWN", "error", "input references an undeclared context slot", workflow.declaration["id"], path, f"/steps/{step_id}/inputs/{key}"))
        for target, source in step.get("bind", {}).items():
            if target not in slots or not source.startswith("event.") or not source[6:]:
                diagnostics.append(Diagnostic("WORKFLOW_BINDING_INVALID", "error", "event bindings require declared target slots and event fields", workflow.declaration["id"], path, f"/steps/{step_id}/bind/{target}"))
        kind = step.get("kind")
        if kind == "operation":
            capability_id = step.get("operation")
            descriptor = capabilities.get(capability_id) if isinstance(capability_id, str) else None
            outcomes = step.get("outcomes")
            if descriptor is None:
                diagnostics.append(Diagnostic("UNKNOWN_CAPABILITY", "error", f"operation capability unavailable: {capability_id}", workflow.declaration["id"], path, f"/steps/{step_id}/operation"))
            elif descriptor.kind != "operation":
                diagnostics.append(Diagnostic("CAPABILITY_KIND_MISMATCH", "error", "workflow operation points to a non-operation capability", workflow.declaration["id"], path, f"/steps/{step_id}/operation"))
            else:
                if capability_id not in required_capabilities:
                    diagnostics.append(Diagnostic("CAPABILITY_NOT_DECLARED", "error", "workflow operation capability must be declared in method.yaml requires", workflow.declaration["id"], path, f"/steps/{step_id}/operation"))
                config_schema = descriptor.contract.get("method_config_schema")
                if config_schema is not None:
                    from jsonschema import Draft202012Validator, SchemaError
                    try:
                        Draft202012Validator.check_schema(config_schema)
                        from .references import validate_schema_refs
                        references = validate_schema_refs(config_schema, resource_id=workflow.declaration["id"], path=path)
                        if references:
                            diagnostics.append(Diagnostic("CAPABILITY_CONTRACT_INVALID", "error", "config schema references must resolve locally", workflow.declaration["id"], path))
                        elif not Draft202012Validator(config_schema).is_valid(step.get("config", {})):
                            diagnostics.append(Diagnostic("OPERATION_CONFIG_INVALID", "error", "operation config violates its registered contract", workflow.declaration["id"], path, f"/steps/{step_id}/config"))
                    except SchemaError:
                        diagnostics.append(Diagnostic("CAPABILITY_CONTRACT_INVALID", "error", "registered operation config schema is invalid", workflow.declaration["id"], path))
                declared_outcomes = descriptor.contract.get("workflow_outcomes")
                if (not isinstance(outcomes, dict) or not isinstance(declared_outcomes, list)
                        or any(not isinstance(item, str) for item in declared_outcomes)
                        or set(outcomes) != set(declared_outcomes)):
                    diagnostics.append(Diagnostic("UNHANDLED_OUTCOME", "error", "operation outcomes must exactly cover its registered contract", workflow.declaration["id"], path, f"/steps/{step_id}/outcomes"))
            if not isinstance(outcomes, dict):
                outcomes = {}
            for outcome, transition in outcomes.items():
                add_transition(step_id, outcome, transition, f"/steps/{step_id}/outcomes/{outcome}")
            routing = step.get("result_routing")
            if routing is not None:
                pointer = f"/steps/{step_id}/result_routing"
                route_path = routing.get("path") if isinstance(routing, dict) else None
                # RFC 6901: empty root pointer or slash-separated tokens with
                # only ~0 and ~1 escapes.
                valid_pointer = (isinstance(route_path, str) and route_path.startswith("/")
                    and re.search(r"~(?![01])", route_path) is None)
                if not valid_pointer:
                    diagnostics.append(Diagnostic("RESULT_ROUTING_POINTER_INVALID", "error", "result routing path must be a valid JSON Pointer", workflow.declaration["id"], path, f"{pointer}/path"))
                routed = routing.get("outcomes") if isinstance(routing, dict) else None
                if not isinstance(routed, dict) or not routed:
                    diagnostics.append(Diagnostic("RESULT_ROUTING_OUTCOMES_INVALID", "error", "result routing requires a non-empty outcome map", workflow.declaration["id"], path, f"{pointer}/outcomes"))
                else:
                    for result, transition in routed.items():
                        add_transition(step_id, result, transition, f"{pointer}/outcomes/{result}")
        elif kind == "wait":
            target = step.get("next")
            edges[step_id].add(target)
        elif kind == "stop":
            if step.get("outcome") not in stop_outcomes:
                diagnostics.append(Diagnostic("STOP_NODE_INVALID", "error", "stop node outcome is not registered", workflow.declaration["id"], path, f"/steps/{step_id}/outcome"))

    for step_id, targets in edges.items():
        for target in targets:
            if target not in by_id:
                diagnostics.append(Diagnostic("WORKFLOW_TARGET_MISSING", "error", f"transition target does not exist: {target}", workflow.declaration["id"], path, f"/steps/{step_id}"))

    loops = value.get("loops") or []
    seen_loop_ids: set[str] = set()
    seen_loop_sources: set[str] = set()
    for index, loop in enumerate(loops):
        pointer = f"/loops/{index}"
        if not isinstance(loop, dict):
            continue  # shape validation reports this first
        loop_id, source, target = loop.get("loop_id"), loop.get("from_step"), loop.get("to_step")
        if loop_id in seen_loop_ids:
            diagnostics.append(Diagnostic("DUPLICATE_WORKFLOW_LOOP", "error", "loop_id values must be unique", workflow.declaration["id"], path, f"{pointer}/loop_id"))
        seen_loop_ids.add(loop_id)
        if source in seen_loop_sources:
            diagnostics.append(Diagnostic("WORKFLOW_LOOP_AMBIGUOUS", "error", "each operation step may declare at most one counted edge", workflow.declaration["id"], path, f"{pointer}/from_step"))
        seen_loop_sources.add(source)
        edge = (source, target)
        if edge in counted_edges:
            diagnostics.append(Diagnostic("DUPLICATE_WORKFLOW_LOOP_EDGE", "error", "each counted edge may be declared only once", workflow.declaration["id"], path, pointer))
        counted_edges.add(edge)
        source_step = by_id.get(source)
        if not source_step or source_step.get("kind") != "operation":
            diagnostics.append(Diagnostic("WORKFLOW_LOOP_SOURCE_INVALID", "error", "counted loop source must be an operation step", workflow.declaration["id"], path, f"{pointer}/from_step"))
        if not isinstance(loop.get("max_rounds"), int) or isinstance(loop.get("max_rounds"), bool) or not 1 <= loop["max_rounds"] <= 4096:
            diagnostics.append(Diagnostic("WORKFLOW_LOOP_LIMIT_INVALID", "error", "max_rounds must be between 1 and 4096 inclusive", workflow.declaration["id"], path, f"{pointer}/max_rounds"))
        if loop.get("on_exhausted") not in stop_outcomes:
            diagnostics.append(Diagnostic("WORKFLOW_LOOP_EXHAUSTION_INVALID", "error", "on_exhausted must name a declared stop outcome", workflow.declaration["id"], path, f"{pointer}/on_exhausted"))
        if source_step and target not in edges.get(source, set()):
            diagnostics.append(Diagnostic("WORKFLOW_LOOP_EDGE_MISSING", "error", "counted loop must name an actual edge from its operation step", workflow.declaration["id"], path, pointer))
    if entry in by_id:
        reached: set[str] = set()
        pending = deque([entry])
        while pending:
            node = pending.popleft()
            if node in reached:
                continue
            reached.add(node)
            pending.extend(edges.get(node, ()))
        for node in sorted(set(by_id) - reached):
            diagnostics.append(Diagnostic("UNREACHABLE_STEP", "error", f"workflow step is unreachable: {node}", workflow.declaration["id"], path, f"/steps/{node}"))

        # A gray/black DFS detects residual back-edges after declared bounded
        # edges are removed. Every remaining cycle is unsupported.
        # The traversal is iterative so a legal long chain is answered with
        # diagnostics instead of a runtime recursion failure; enter/exit order
        # and the diagnostic for each back-edge match the recursive form.
        gray: set[str] = set()
        black: set[str] = set()
        stack: list[tuple[str, int]] = [(entry, 0)]
        while stack:
            node, cursor = stack.pop()
            if cursor:
                gray.discard(node)
                black.add(node)
                continue
            if node in gray:
                diagnostics.append(Diagnostic("UNSUPPORTED_FLOW_CYCLE", "error", f"workflow contains a cycle at {node}", workflow.declaration["id"], path, f"/steps/{node}"))
                continue
            if node in black:
                continue
            gray.add(node)
            # Re-push this node with a resume marker before its children so the
            # children are visited in edge order and the exit runs after them.
            stack.append((node, 1))
            children = [item for item in edges.get(node, ()) if item in by_id and (node, item) not in counted_edges]
            for child in reversed(children):
                stack.append((child, 0))
    return diagnostics
