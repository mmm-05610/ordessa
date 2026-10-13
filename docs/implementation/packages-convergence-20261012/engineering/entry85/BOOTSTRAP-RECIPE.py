"""Receiving helpers for the first Work; never a fixture or bypass.

Every argument is an object/ref returned by an original owner. Missing original
Unit/query/review/capability producers raise or prevent publication. The current
SQLiteReviewBindings has unbound/bind_selection support, but Server's ordinary
product configuration still requires bound Proposal/phases and has no
post-Proposal retained-handle path. These helpers are not wired to the CLI.
They do not mint a MethodRef, ProposalRef, phase, role, capability, Grant,
native invocation, or input ArtifactRevisionRef.
"""
from __future__ import annotations

from dataclasses import asdict

from ordessa_engineering.application.api import ApplicationError
from ordessa_engineering.domain.artifacts.method_binding import MethodRef as BoundMethodRef
from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.common.models.values import Digest


def compose_unbound_review_and_work(factory, access, wire_scope, *, unit_owner,
                                    author_unit_resolver, invocation_resolver,
                                    unit_query_factory, execution_query_factory=None,
                                    execution_request_factory=None,
                                    base_ports_factory=None,
                                    phase_bindings=(), material_submissions=(),
                                    report_phase_key=None):
    """Create original ports before a Proposal; bind no future subject here.

    ``unit_owner`` and all resolvers must be the selected original runtime
    owners. The first-case checkpoint had no selected Unit owner, so this
    function correctly refuses there. The product root must retain the exact
    returned ``review_bindings`` object; the current product factory exposes
    it only as ``ports.review_admission.bindings``.
    """
    from ordessa_server.composition.engineering_method_unit_assembly import (
        method_unit_application_ports_factory,
    )
    if unit_owner is None:
        raise ApplicationError("UNIT_REVIEW_SOURCE_UNAVAILABLE")
    compose = method_unit_application_ports_factory(
        unit_owner=unit_owner,
        proposal_ref=None,
        phases=None,
        author_unit_resolver=author_unit_resolver,
        invocation_resolver=invocation_resolver,
        unit_query_factory=unit_query_factory,
        execution_query_factory=execution_query_factory,
        execution_request_factory=execution_request_factory,
        base_ports_factory=base_ports_factory,
        phase_bindings=phase_bindings,
        material_submissions=material_submissions,
        report_phase_key=report_phase_key,
    )
    ports = compose(factory, access, wire_scope)
    review_bindings = getattr(ports.review_admission, "bindings", None)
    work_bindings = ports.current_wait_bindings
    if (review_bindings is None or getattr(review_bindings, "proposal_ref", "unbound") is not None
            or getattr(review_bindings, "phases", "unbound") is not None
            or work_bindings is None
            or getattr(getattr(work_bindings, "source", None), "review_bindings", None)
                is not review_bindings):
        raise ApplicationError("WORK_SOURCE_AUTHORITY_UNAVAILABLE")
    return ports, review_bindings


def published_ref_for_adoption(snapshot_ref):
    """Convert only the actual frozen snapshot ref to the domain ref identity."""
    return BoundMethodRef(
        snapshot_ref.method_id,
        snapshot_ref.release_version,
        snapshot_ref.schema_version,
        Digest("sha256", snapshot_ref.snapshot_digest),
    )


def publish_against_actual_catalog(publication, method_source, compiler_version):
    """Call the selected RegisteredMethodPublication; never pad its catalog."""
    result = publication.publish(method_source, compiler_version=compiler_version)
    if not result.ok:
        raise ApplicationError("METHOD_PUBLICATION_REFUSED")
    return result.value.ref


def select_published_method(publication, snapshot_ref, context, *, actual_method_control_version):
    """Adopt the exact published ref using the original MethodUseCases CAS."""
    if type(actual_method_control_version) is not int or actual_method_control_version < 0:
        raise ApplicationError("METHOD_SELECTION_CHANGED")
    method_ref = published_ref_for_adoption(snapshot_ref)
    result = publication.select(
        method_ref, context, expected_version=actual_method_control_version,
    )
    if result.state != "completed":
        raise ApplicationError("METHOD_SELECTION_CHANGED")
    return method_ref


def bind_owner_returned_subject(review_bindings, context, proposal_ref, phases):
    """Bind the immutable, same-library Proposal result and its exact phases."""
    if type(proposal_ref) is not ProposalRef or type(phases) is not tuple or not phases:
        raise ApplicationError("METHOD_SUBJECT_BINDING_MISMATCH")
    bind = getattr(review_bindings, "bind_selection", None)
    if not callable(bind):
        raise ApplicationError("METHOD_SUBJECT_BINDING_MISMATCH")
    bind(context, proposal_ref=proposal_ref, phases=phases)


async def start_original_work(service, context, *, run_id, proposal_ref,
                              work_inputs_ref):
    """Start on the same Service using exact original selection refs."""
    if type(proposal_ref) is not ProposalRef or type(work_inputs_ref) is not ArtifactRevisionRef:
        raise ApplicationError("WORK_INPUT_INVALID")
    return await service.execute(
        "engineering.work.start",
        {"run_id": run_id, "selection": {
            "proposal_ref": asdict(proposal_ref),
            "initial_slot_refs": {"work_inputs": asdict(work_inputs_ref)},
        }},
        context,
    )

