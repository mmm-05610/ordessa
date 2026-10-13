"""Resolve exact review-author sources from original Engineering records.

This source proves recorded provenance only.  It never labels a submitter as a
human and never treats actor metadata as an authentication grant.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib

from ....application.contracts.commands import CommandContext, CommandKey
from ....application.contracts.errors import ApplicationError
from ....application.contracts.review_authorship import (
    MaterialSubmissionProof,
    ReviewAuthorship,
)
from ....domain.artifacts.ref_codec import decode_artifact_ref
from ....domain.artifacts.refs import ArtifactRevisionRef
from ....domain.changes.submission import Submission
from ....domain.common.mechanisms.codec import canonical_value, decode_json
from ....domain.common.models.values import Digest
from ....domain.common.outcomes.diagnostics import ReferenceError
from ....domain.reviews.models import ReviewPlan


@dataclass(frozen=True)
class ConfiguredMaterialSubmission:
    """One exact artifact revision and its original create/append command key."""

    revision_ref: ArtifactRevisionRef
    command_key: CommandKey

    def __post_init__(self):
        if (type(self.revision_ref) is not ArtifactRevisionRef
                or type(self.command_key) is not CommandKey
                or self.command_key.realm_id != self.revision_ref.realm_id):
            raise ApplicationError("REVIEW_AUTHOR_SOURCE_INVALID")


class SQLiteReviewAuthorshipSource:
    """Read configured material-submission or native-Submission authorship.

    Material receipts are selected by exact revision and journal key.  Native
    attribution follows the original Submission and dispatch binding readers.
    Neither path scans for latest artifacts or infers a human identity.
    """

    _MATERIAL_OPERATIONS = frozenset({
        "engineering.artifacts.create",
        "engineering.artifacts.append_revision",
    })

    def __init__(self, factory, method_control, *, review_bindings,
                 material_submissions: tuple[ConfiguredMaterialSubmission, ...] = ()):
        if (getattr(method_control, "factory", None) is not factory
                or getattr(review_bindings, "factory", None) is not factory
                or getattr(review_bindings, "methods", method_control) is not method_control
                or not callable(getattr(review_bindings, "resolve_review_submission", None))
                or type(material_submissions) is not tuple
                or any(type(item) is not ConfiguredMaterialSubmission
                       for item in material_submissions)
                or len({item.revision_ref for item in material_submissions}) != len(material_submissions)):
            raise ApplicationError("REVIEW_AUTHOR_SOURCE_UNAVAILABLE")
        self.factory = factory
        self.methods = method_control
        self.review_bindings = review_bindings
        self.material_submissions = material_submissions

    def resolve_authorship(self, context, plan: ReviewPlan,
                           delivery_refs: tuple[ArtifactRevisionRef, ...]) -> ReviewAuthorship:
        if (type(context) is not CommandContext
                or type(plan) is not ReviewPlan or type(delivery_refs) is not tuple
                or not delivery_refs or any(type(ref) is not ArtifactRevisionRef for ref in delivery_refs)
                or plan.scope != context.scope
                or plan.requirement.method_ref is None
                or {target.ref for target in plan.requirement.expected_targets.targets} != set(delivery_refs)
                or any((ref.realm_id, ref.project_id) !=
                       (context.scope.realm_id, context.scope.project_id) for ref in delivery_refs)
                or len(set(delivery_refs)) != len(delivery_refs)):
            raise ApplicationError("REVIEW_AUTHOR_SOURCE_INVALID")
        method_ref = plan.requirement.method_ref
        phase_key = plan.requirement.phase_key
        selected = self.review_bindings.resolve_review_submission(context, method_ref, phase_key)
        if selected is not None:
            return self._native_authorship(context, plan, delivery_refs, selected)
        return self._material_authorship(context, plan, delivery_refs)

    def _material_authorship(self, context, plan, delivery_refs):
        configured = {item.revision_ref: item for item in self.material_submissions}
        if set(delivery_refs) - set(configured):
            raise ApplicationError("REVIEW_AUTHOR_SOURCE_UNAVAILABLE")
        proofs = []
        with self.methods.guard_method(context, plan.requirement.method_ref) as snapshot:
            with self.factory.begin(context.scope, "read") as uow:
                for ref in delivery_refs:
                    submission = configured[ref]
                    key = submission.command_key
                    if key.realm_id != context.scope.realm_id:
                        raise ApplicationError("REVIEW_AUTHOR_SOURCE_MISMATCH")
                    entry = uow.commands.get(key)
                    if (entry is None or entry.state != "completed"
                            or entry.operation not in self._MATERIAL_OPERATIONS
                            or entry.project_id != context.scope.project_id
                            or entry.key != key or entry.result_bytes is None):
                        raise ApplicationError("REVIEW_AUTHOR_SOURCE_UNAVAILABLE")
                    try:
                        result = canonical_value(entry.result_bytes)
                        raw_ref = result.get("revision_ref") if type(result) is dict else None
                        returned_ref = decode_artifact_ref(raw_ref)
                    except (ApplicationError, ReferenceError, TypeError, ValueError, KeyError):
                        raise ApplicationError("REVIEW_AUTHOR_SOURCE_MISMATCH") from None
                    if returned_ref != ref:
                        raise ApplicationError("REVIEW_AUTHOR_SOURCE_MISMATCH")
                    if entry.operation == "engineering.artifacts.create":
                        # A create receipt also records the artifact identity;
                        # bind it to the revision rather than trusting it alone.
                        artifact_result = result.get("artifact")
                        if (type(artifact_result) is not dict
                                or artifact_result.get("artifact_id") != ref.artifact_id):
                            raise ApplicationError("REVIEW_AUTHOR_SOURCE_MISMATCH")
                    revision = uow.engineering.resolve_revision(ref)
                    if (revision.scope != context.scope or plan.requirement.method_ref not in revision.method_refs
                            or revision.created_by.actor_id != key.principal_id):
                        raise ApplicationError("REVIEW_AUTHOR_SOURCE_MISMATCH")
                    proofs.append(MaterialSubmissionProof(
                        revision_ref=ref,
                        command_key=key,
                        operation=entry.operation,
                        operation_id=entry.operation_id,
                        request_digest=entry.request_digest,
                        result_digest=Digest("sha256", hashlib.sha256(entry.result_bytes).hexdigest()),
                        submitter_principal_id=key.principal_id,
                    ))
                uow.commit()
        return ReviewAuthorship(context.scope, plan.requirement.method_ref,
            delivery_refs, "authenticated_material_submitter", material_proofs=tuple(proofs))

    def _native_authorship(self, context, plan, delivery_refs, submission_ref):
        with self.methods.guard_method(context, plan.requirement.method_ref):
            with self.factory.begin(context.scope, "read") as uow:
                submission = uow.submissions.resolve(submission_ref)
                if type(submission) is not Submission or submission.scope != context.scope:
                    raise ApplicationError("REVIEW_AUTHOR_SOURCE_MISMATCH")
                output_refs = tuple(ref for ref in submission.output_refs
                                    if type(ref) is ArtifactRevisionRef)
                if (not output_refs or set(delivery_refs) != set(output_refs)
                        or len(delivery_refs) != len(output_refs)):
                    raise ApplicationError("REVIEW_AUTHOR_SOURCE_MISMATCH")
                for ref in output_refs:
                    revision = uow.engineering.resolve_revision(ref)
                    if (revision.scope != context.scope
                            or plan.requirement.method_ref not in revision.method_refs):
                        raise ApplicationError("REVIEW_AUTHOR_SOURCE_MISMATCH")
                from ....application.orchestration.steps.implementation_dispatch import (
                    resolve_dispatch_submission_binding,
                )
                binding = resolve_dispatch_submission_binding(uow, submission)
                row = uow.dispatch.by_operation(submission.execution_ref.operation_ref, context.scope)
                if row.get("dispatch_phase") != "completed":
                    raise ApplicationError("REVIEW_AUTHOR_SOURCE_UNAVAILABLE")
                if binding.scope != context.scope:
                    raise ApplicationError("REVIEW_AUTHOR_SOURCE_MISMATCH")
                uow.commit()
        execution = submission.execution_ref
        unit_ref = {
            "environmentNamespace": execution.environment_namespace,
            "unitId": execution.unit_id,
            "ownerProviderRef": decode_json(execution.owner_provider_ref_bytes),
            "sourceRevision": execution.source_revision,
        }
        return ReviewAuthorship(context.scope, plan.requirement.method_ref,
            delivery_refs, "native_unit", author_unit_ref=unit_ref)


__all__ = ["ConfiguredMaterialSubmission", "SQLiteReviewAuthorshipSource"]
