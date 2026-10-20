"""SOURCE_BOUND_POLICY admission against an original SQLite Submission.

The SQLite proposal/submission/dispatch closure is real.  Native Unit records
are explicit test peers, so this verifies the Engineering source and role
boundary without claiming a production UnitRecords provider or model run.
"""
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
import asyncio
import json
import sys

import pytest

import ordessa_interfaces
_repo = Path(__file__).resolve().parents[4]
ordessa_interfaces.__path__.append(str(_repo / "packages/interfaces/system-access/src/ordessa_interfaces"))
sys.path.insert(0, str(_repo / "packages/interfaces/system-access/bindings/src"))
import ordessa_interfaces.system_access as _system_access
_system_access.__path__.append(str(_repo / "packages/interfaces/contracts/src/ordessa_interfaces/system_access"))

from ordessa_interfaces.system_access.contracts.refs import Scope as WireScope
from ordessa_interfaces.system_access.access_control.authentication import AccessGrant, InstanceAccessAuthority
from ordessa_system_access_bindings import EngineeringCommandAccess
from ordessa_engineering.adapters.review_sources import SQLiteReviewAuthorshipSource
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.unit_reviewer_authority import SQLiteUnitReviewerAuthority
from ordessa_engineering.application.assembly import build_reviewer_assignment_usecases
from ordessa_engineering.application.api import EngineeringService
from ordessa_engineering.application.contracts.commands import ReadSet
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.review_authorship import SOURCE_BOUND_POLICY
from ordessa_infrastructure.encoding import canonical_bytes
from submission_wait_business_fixture import build_submission_wait_fixture


TOKEN = "native-authorship-admission-test"
ASSIGN = "engineering.reviews.assign_reviewer"
def _unit(unit_id):
    return {"environmentNamespace": "explicit-test-native-peer", "unitId": unit_id,
            "ownerProviderRef": {"provider": "test-peer"}, "sourceRevision": "peer-revision-1"}


class _TestUnitRecords:
    """Explicit identity peers only; this is not a production records source."""
    def resolve_unit_reference(self, ref, invocation, *, input_digest):
        assert invocation == {"unit_id": ref["unitId"], "purpose": invocation["purpose"]}
        assert input_digest == "fixture:" + ref["unitId"]
        return SimpleNamespace(public_ref=ref)


def test_source_bound_native_authorship_uses_submission_and_requires_distinct_reviewer(tmp_path):
    e = build_submission_wait_fixture(tmp_path, authorship_policy=SOURCE_BOUND_POLICY)
    factory = e["factory"]
    try:
        snapshot = e["snapshot"]
        from ordessa_engineering.methods.definitions.models.compiled import thaw_value
        acceptance = next(node for node in snapshot.program.workflow.steps if node.id == "acceptance_review")
        assert thaw_value(acceptance.config)["unit_submission_review_strategy"]["roles"]["identity_constraint"] == SOURCE_BOUND_POLICY

        authorship = SQLiteReviewAuthorshipSource(factory, e["controls"], review_bindings=e["bindings"])
        source_fact = authorship.resolve_authorship(e["context"], e["plan"], tuple(e["submission"].output_refs))
        assert source_fact.source_kind == "native_unit"
        execution = e["submission"].execution_ref
        expected_author = {"environmentNamespace": execution.environment_namespace,
            "unitId": execution.unit_id, "ownerProviderRef": json.loads(execution.owner_provider_ref_bytes),
            "sourceRevision": execution.source_revision}
        assert source_fact.author_unit_ref == expected_author
        assert e["native"]["synthetic_native_facts"] is True

        reviewer_caps = (ASSIGN,)
        wire_scope = WireScope(e["scope"].realm_id, e["scope"].project_id)
        authority = InstanceAccessAuthority(lambda: TOKEN, principal_id="reviewer-issuer",
            legacy_principal=None, grants=(AccessGrant(wire_scope, reviewer_caps),))
        access = EngineeringCommandAccess(authority)
        caller = authority.authenticate("Bearer " + TOKEN)
        records = _TestUnitRecords()

        def query(_context, unit_ref, _plan, _request, *, purpose):
            return {"unit_id": unit_ref["unitId"], "purpose": purpose}, "fixture:" + unit_ref["unitId"]

        assignments = build_reviewer_assignment_usecases(factory, method_control=e["controls"], records=records,
            expected_access=access, expected_scope=wire_scope, unit_query_factory=query,
            authorship_source=authorship)
        service = EngineeringService(factory, access, reviewer_assignments=assignments)
        with factory.begin(e["scope"], "read") as uow:
            request = uow.reviews.get_request(e["plan"].review_id)
        author = source_fact.author_unit_ref

        def assign(reviewer, request_id):
            with access.admit(caller, wire_scope, ASSIGN, request_id=request_id, trace_id="test") as ctx:
                parameters = {"review_id": e["plan"].review_id,
                    "expected_plan_digest": asdict(e["plan"].plan_digest),
                    "request_version": request.version, "fence": request.fence,
                    "reviewer_unit_ref": reviewer}
                expected = service.command_request_digest(ASSIGN, parameters, ctx, ReadSet(ctx.scope, ()))
                result = asyncio.run(service.execute(ASSIGN, parameters, ctx))
                with factory.begin(e["scope"], "read") as uow:
                    journal = uow.commands.get(ctx.key)
                assert journal is not None and journal.request_digest == expected
                return result

        with pytest.raises(ApplicationError, match="UNTRUSTED_REVIEWER"):
            assign(author, "same-native-reviewer")

        result = assign(_unit("independent-reviewer"), "distinct-native-reviewer")
        assert result.status == "completed"
        with factory.begin(e["scope"], "read") as uow:
            assignment = uow.reviewer_assignments.active_for_review(e["plan"].review_id)[0]
            persisted = uow.reviewer_assignments.get(assignment.ref)
        assert persisted.author_unit_ref_bytes == canonical_bytes(author)
        assert persisted.reviewer_unit_ref_bytes != persisted.author_unit_ref_bytes
    finally:
        e["library"].close()
