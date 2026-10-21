"""Real schema15 assignments with real capability auth and explicit Agent test peers.

Agent query records below are synthetic native-identity peers: this covers the
Engineering assignment/source boundary, not a production original Agent service.
"""
from contextlib import contextmanager
from dataclasses import asdict, replace
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# The workspace installs the umbrella interfaces distribution; system-access
# is an independent source leaf and is deliberately not installed here.
import ordessa_interfaces
_repo = Path(__file__).resolve().parents[4]
ordessa_interfaces.__path__.append(str(_repo / "packages/interfaces/system-access/src/ordessa_interfaces"))
sys.path.insert(0, str(_repo / "packages/interfaces/system-access/bindings/src"))
import ordessa_interfaces.system_access as _system_access
_system_access.__path__.append(str(_repo / "packages/interfaces/contracts/src/ordessa_interfaces/system_access"))

from ordessa_interfaces.system_access.contracts.refs import Scope as WireScope
from ordessa_interfaces.system_access.access_control.authentication import AccessError, AccessGrant, InstanceAccessAuthority
from ordessa_system_access_bindings import EngineeringCommandAccess
from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.adapters.review_sources import SQLiteAgentReviewerAuthority
from ordessa_engineering.application.assembly import build_reviewer_assignment_usecases
from ordessa_engineering.application.api import EngineeringService
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.snapshots import EngineeringTargetBindings
from ordessa_engineering.application.orchestration.method_bridge import MethodBridge
from ordessa_engineering.application.usecases.publish_snapshot import freeze_method
from ordessa_engineering.application.usecases.support.methods import MethodUseCases
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.targets import Target, TargetSet
from ordessa_engineering.application.contracts.agent_review import AgentReviewBinding
from ordessa_engineering.domain.changes.agent_execution_ref import AgentExecutionRecordRef
from ordessa_engineering.application.contracts.commands import ReadSet
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.methods import load_method, compile_method
from ordessa_engineering.methods.definitions.models import MethodSource, CompilationCapabilities, CapabilityDescriptor
from ordessa_engineering.methods.definitions.models.identity import method_digest
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_infrastructure.encoding.immutable_json import sealed_mapping, safe_json
from test_proposal_usecases import SCOPE as DOMAIN_SCOPE, SyntheticAccess, _artifact_graph, _ctx


WIRE_SCOPE = WireScope(DOMAIN_SCOPE.realm_id, DOMAIN_SCOPE.project_id)
ASSIGN = "engineering.reviews.assign_reviewer"
REVOKE = "engineering.reviews.revoke_reviewer"
IDENTITY_CONSTRAINT = "original_author_agent_identity_must_differ_from_original_reviewer_agent_identity"
TOKEN = "reviewer-assignment-test-token"
CAPS = (ASSIGN, REVOKE)


def _unit(unit_id):
    return {'schemaVersion':'agent-instance/1','namespace':'test-native','instanceId':unit_id,
            'bindingDigest':'sha256:'+'b'*64}


class _TestManagement:
    @contextmanager
    def guard_management(self, *args):
        yield Digest("sha256", "b" * 64)


class _SyntheticUnitRecords:
    """Identity echo for the declared fixture query; never a production auth source."""
    sealed = False

    def read_agent_reference(self, ref, *, read_invocation):
        assert read_invocation == {"test_query": ref["instanceId"], "purpose": read_invocation["purpose"]}
        assert read_invocation["purpose"] in {"reviewer", "author"}
        return canonical_bytes(json.loads(safe_json(sealed_mapping(ref))) if self.sealed else ref)


def _publish_with_identity_constraint(lib, root, *, identity_constraint=IDENTITY_CONSTRAINT):
    root.mkdir()
    workflow = {
        "schema_version": 1, "entry": "review", "context_slots": ["proposal_ref"],
        "steps": [
            {"id": "review", "kind": "operation", "operation": "engineering.reviews.request",
             "config": {"purpose": "quality", "standards": [{"resource": "standard.test"}],
                         "review_source": {"response_document_type": "test-document",
                                           "response_schema": {"resource": "schema.test"},
                                           "response_codec": "exact_check_key_status/1"},
                         "unit_submission_review_strategy": {"roles": {"identity_constraint": identity_constraint}}},
             "outcomes": {"completed": {"next": "done"}, "rejected": {"stop": "finished"}}},
            {"id": "done", "kind": "stop", "outcome": "finished"}],
        "stop_outcomes": ["finished"], "wait_kinds": []}
    check = CapabilityDescriptor("test.assignment.check", "check", "1.0.0",
                                 method_digest("capability-contract", {}), {})
    op = next(d for d in EngineeringService.operation_capabilities().capabilities
              if d.capability_id == "engineering.reviews.request")
    standard = {"schema_version": 1, "standard_id": "assignment-standard", "revision": "1.0.0",
        "purpose": "quality", "criteria": [{"criterion_id": "required", "statement": "Check the declared fixture.",
            "applies_to": ["test-document"], "required_inputs": ["proposal_ref"],
            "checks": [{"capability_id": check.capability_id, "interface_version": check.interface_version,
                        "bindings": {}}],
            "policy": {"satisfied": "manual", "violated": "block", "insufficient": "block", "unknown": "manual"}}],
        "reduction": {"required_criteria": "all_applicable", "empty_applicable_set": "error",
                      "priority": ["block", "manual", "pass"]}}
    values = (("workflow.main", "workflow", "workflow.json", workflow),
              ("schema.test", "document_schema", "schema.json", {"type": "object"}),
              ("standard.test", "standard", "standard.json", standard))
    resources = []
    for resource_id, kind, filename, value in values:
        raw = canonical_bytes(value)
        (root / filename).write_bytes(raw)
        resources.append({"id": resource_id, "kind": kind, "path": filename,
                          "media_type": "application/schema+json" if kind == "document_schema" else "application/yaml",
                          "sha256": hashlib.sha256(raw).hexdigest()})
    manifest = {"schema_version": 1, "method_id": "test.reviewer-assignment", "release_version": "1.0.0",
        "compiler_contract": "ordessa.methods/v1", "entry": {"resource": "workflow.main"},
        "resources": resources, "documents": [{"document_type": "test-document", "schema": {"resource": "schema.test"}}],
        "requires": [{k: getattr(d, k) for k in ("capability_id", "kind", "interface_version", "contract_digest")}
                     for d in (check, op)]}
    (root / "method.yaml").write_text(json.dumps(manifest))
    loaded = load_method(MethodSource(root), FileResourceReader())
    assert loaded.ok, loaded.error
    caps = CompilationCapabilities((check, op), trust_class="host")
    compiled = compile_method(loaded.value, caps, "reviewer-assignment-test/1")
    assert compiled.ok, compiled.error
    store = SQLiteSnapshotStore(lib)
    frozen = freeze_method(compiled.value, store, store,
                           capability_catalog=SimpleNamespace(read_current=lambda: caps))
    assert frozen.ok, frozen.error
    snapshot = store.get(frozen.value.ref)
    ref = snapshot.ref
    method = MethodRef(ref.method_id, ref.release_version, ref.schema_version,
                       Digest("sha256", ref.snapshot_digest))
    return snapshot, method, store


@pytest.fixture
def env(tmp_path):
    lib = EngineeringLibrary.create((tmp_path / "schema15.sqlite").resolve(),
                                    library_id="schema15-reviewer-assignment", schema_version=15)
    try:
        snapshot, method, store = _publish_with_identity_constraint(lib, tmp_path / "method")
        factory = SQLiteUoWFactory(lib)
        control = SQLiteMethodControl(factory, store)
        authority = InstanceAccessAuthority(lambda: TOKEN, principal_id="review-assignment-issuer",
            legacy_principal=None, grants=(AccessGrant(WIRE_SCOPE, CAPS),))
        access = EngineeringCommandAccess(authority)
        caller = authority.authenticate("Bearer " + TOKEN)
        management = MethodUseCases(factory, SyntheticAccess(), store, _TestManagement())
        management.adopt(method, replace(_ctx(), scope=DOMAIN_SCOPE, request_id="adopt-role-test"), expected_version=0)
        _, revision, _ = _artifact_graph(factory)
        target = Target("primary", revision)
        bindings = EngineeringTargetBindings(DOMAIN_SCOPE, TargetSet((target,)), ((target, "test-document"),),
            ("proposal_ref",), ("reviewer",), "review")
        plan = MethodBridge().review_plan(snapshot, bindings,
            MethodBridge().review_requirements(snapshot, bindings)[0], "review-assignment")
        with factory.begin(DOMAIN_SCOPE) as uow:
            request = uow.reviews.create_plan(plan)
            uow.commit()
        author = _unit("author-unit")
        records = _SyntheticUnitRecords()
        def query(_ctx, unit_ref, _plan, _request, *, purpose):
            return {"test_query": unit_ref["instanceId"], "purpose": purpose}
        author_resolver = lambda _ctx, _plan: author
        assignments = build_reviewer_assignment_usecases(factory, method_control=control, records=records,
            expected_access=access, expected_scope=WIRE_SCOPE, agent_query_factory=query,
            author_agent_resolver=author_resolver)
        service = EngineeringService(factory, access, reviewer_assignments=assignments)
        def command(operation, request_id):
            with access.admit(caller, WIRE_SCOPE, operation, request_id=request_id, trace_id="test") as ctx:
                yield ctx
        yield locals()
    finally:
        lib.close()


def _assign(e, reviewer, request_id, author_agent_ref=None):
    with e["access"].admit(e["caller"], WIRE_SCOPE, ASSIGN, request_id=request_id, trace_id="test") as ctx:
        parameters = {"review_id": e["plan"].review_id,
            "expected_plan_digest": asdict(e["plan"].plan_digest),
            "request_version": e["request"].version, "fence": e["request"].fence,
            "reviewer_agent_ref": reviewer}
        if author_agent_ref is not None:
            parameters["author_agent_ref"] = author_agent_ref
        expected_digest = e["service"].command_request_digest(ASSIGN, parameters, ctx, ReadSet(ctx.scope, ()))
        result = asyncio.run(e["service"].execute(ASSIGN, parameters, ctx))
        with e["factory"].begin(DOMAIN_SCOPE, "read") as uow:
            entry = uow.commands.get(ctx.key)
        assert entry is not None and entry.request_digest == expected_digest
        assert entry.operation == ASSIGN and entry.state == "completed"
        assert result.operation_id == entry.operation_id and result.status == entry.state
        return result


def _revoke(e, assignment_ref, request_id, reason):
    with e["access"].admit(e["caller"], WIRE_SCOPE, REVOKE, request_id=request_id, trace_id="test") as ctx:
        parameters = {"assignment_ref": asdict(assignment_ref), "expected_control_version": 0,
                      "reason": reason}
        expected_digest = e["service"].command_request_digest(REVOKE, parameters, ctx, ReadSet(ctx.scope, ()))
        result = asyncio.run(e["service"].execute(REVOKE, parameters, ctx))
        with e["factory"].begin(DOMAIN_SCOPE, "read") as uow:
            entry = uow.commands.get(ctx.key)
        assert entry is not None and entry.request_digest == expected_digest
        assert entry.operation == REVOKE and entry.state == "completed"
        assert result.operation_id == entry.operation_id and result.status == entry.state
        return result


@pytest.mark.parametrize('sealed', [False, True])
def test_schema15_assignment_authenticates_issuer_and_enforces_frozen_author_identity(env, sealed):
    e = env
    e['records'].sealed = sealed
    without_owner = EngineeringService(e["factory"], e["access"])
    assert ASSIGN not in {d.capability_id for d in without_owner.bound_operation_capabilities().capabilities}
    assert REVOKE not in {d.capability_id for d in without_owner.bound_operation_capabilities().capabilities}
    with pytest.raises(ApplicationError, match="UNTRUSTED_REVIEWER"):
        _assign(e, e["author"], "same-unit")
    same_underlying_unit = {**e["author"], "bindingDigest": "sha256:" + "c" * 64}
    with pytest.raises(ApplicationError, match="UNTRUSTED_REVIEWER"):
        _assign(e, same_underlying_unit, "same-unit-identity-different-ref")
    with pytest.raises(ApplicationError, match="UNIT_REVIEW_AUTHOR_BINDING_UNAVAILABLE"):
        _assign(e, _unit("reviewer-unit"), "wrong-author", _unit("unrelated-author"))
    result = _assign(e, _unit("reviewer-unit"), "valid-assignment")
    assert result.status == "completed"
    payload = json.loads(result.result_bytes)
    ref_data = payload["assignment_ref"]
    with e["factory"].begin(DOMAIN_SCOPE, "read") as uow:
        ref = uow.reviewer_assignments.active_for_review(e["plan"].review_id)[0].ref
        record = uow.reviewer_assignments.get(ref)
        control = uow.reviewer_assignments.control(ref)
    assert asdict(ref) == ref_data
    assert record.issuer_principal_id == "review-assignment-issuer"
    assert record.issuer_credential_epoch == e["caller"].credential_epoch
    assert record.author_agent_ref_bytes == canonical_bytes(e["author"])
    assert control.state == "active" and control.version == 0
    with pytest.raises(ApplicationError, match="REVIEWER_ASSIGNMENT_ALREADY_ACTIVE"):
        _assign(e, _unit("second-reviewer"), "duplicate-active")


@pytest.mark.parametrize('field,value', [
    ('schemaVersion', 'agent-instance/other'), ('namespace', 'other-namespace'),
    ('instanceId', 'other-agent'), ('bindingDigest', 'sha256:' + 'e' * 64),
])
def test_schema15_sealed_record_cannot_substitute_any_reference_field(env, monkeypatch, field, value):
    records = env['records']
    original = records.read_agent_reference
    def substitute(ref, *, read_invocation):
        resolved = json.loads(original(ref, read_invocation=read_invocation))
        return canonical_bytes(json.loads(safe_json(sealed_mapping({**resolved, field: value}))))
    monkeypatch.setattr(records, 'read_agent_reference', substitute)
    with pytest.raises(ApplicationError, match='UNTRUSTED_REVIEWER'):
        _assign(env, _unit('reviewer-unit'), 'substituted-' + field)
    with env['factory'].begin(DOMAIN_SCOPE, 'read') as uow:
        with pytest.raises(ApplicationError):
            uow.reviewer_assignments.active_for_review(env['plan'].review_id)


def test_schema15_assignment_capability_revocation_and_reopen_persistence(env, tmp_path):
    e = env
    result = _assign(e, _unit("reviewer-unit"), "persist-assignment")
    with e["factory"].begin(DOMAIN_SCOPE, "read") as uow:
        assignment = uow.reviewer_assignments.active_for_review(e["plan"].review_id)[0]
    e["authority"].replace_grants((AccessGrant(WIRE_SCOPE, (REVOKE,)),))
    stale = e["authority"].authenticate("Bearer " + TOKEN)
    with pytest.raises(AccessError, match="ACCESS_DENIED"):
        with e["access"].admit(stale, WIRE_SCOPE, ASSIGN, request_id="denied", trace_id="test") as ctx:
            e["assignments"].assign_reviewer(ctx, review_id=e["plan"].review_id,
                expected_plan_digest=e["plan"].plan_digest, request_version=e["request"].version,
                fence=e["request"].fence, reviewer_agent_ref=_unit("reviewer-unit"))
    e["caller"] = stale
    revoke_result = _revoke(e, assignment.ref, "revoke", "end assigned role")
    e["authority"].replace_grants((AccessGrant(WIRE_SCOPE, CAPS),))
    e["caller"] = e["authority"].authenticate("Bearer " + TOKEN)
    replay = _assign(e, _unit("reviewer-unit"), "persist-assignment")
    assert replay.operation_id == result.operation_id
    with e["factory"].begin(DOMAIN_SCOPE, "read") as uow:
        with pytest.raises(ApplicationError, match="REVIEWER_ASSIGNMENT_UNAVAILABLE"):
            uow.reviewer_assignments.active_for_review(e["plan"].review_id)
        assert uow.reviewer_assignments.control(assignment.ref).state == "revoked"
    path = e["lib"].path
    e["lib"].close()
    reopened = EngineeringLibrary.open(path, library_id="schema15-reviewer-assignment")
    try:
        with SQLiteUoWFactory(reopened).begin(DOMAIN_SCOPE, "read") as uow:
            recovered = uow.reviewer_assignments.get(assignment.ref)
            control = uow.reviewer_assignments.control(assignment.ref)
        assert recovered == assignment
        assert control.state == "revoked" and control.version == 1
        assert result.operation_id
    finally:
        reopened.close()
    assert revoke_result.status == "completed"

    schema14 = EngineeringLibrary.create((tmp_path / "schema14.sqlite").resolve(),
        library_id="schema14-no-reviewer-assignments", schema_version=14)
    try:
        factory14 = SQLiteUoWFactory(schema14)
        with pytest.raises(ApplicationError, match="REVIEWER_ASSIGNMENT_SCHEMA_REQUIRED"):
            build_reviewer_assignment_usecases(factory14,
                method_control=SimpleNamespace(factory=factory14, guard_method=lambda *a, **k: None),
                records=e["records"], expected_access=e["access"], expected_scope=WIRE_SCOPE,
                agent_query_factory=e["query"])
    finally:
        schema14.close()


def _unit_binding(e, reviewer, author):
    from ordessa_engineering.domain.changes.agent_execution_ref import AgentExecutionRecordRef
    prompt = Digest('sha256', 'e' * 64)
    turn = {'schemaVersion': 'agent-turn-ref/1', 'instanceRef': reviewer, 'turnId': 'review-turn'}
    query = 'sha256:' + hashlib.sha256(canonical_bytes({'schemaVersion': 'agent-turn-query/1',
        'turnRef': turn, 'expectedInputDigest': 'sha256:' + prompt.hex})).hexdigest()
    captured = BlobRef(Digest('sha256', 'a' * 64), 2, 'application/json', 'test-capture')
    execution = AgentExecutionRecordRef(canonical_bytes(reviewer), canonical_bytes(turn), 'test-source',
        'test-operation', 'test-attempt', prompt, query, captured)
    return AgentReviewBinding(e['plan'].plan_digest, e['request'].version, e['request'].fence,
        execution, 'sha256:' + prompt.hex, {'query': 'immutable-fixture'}, (),
        None, 'test-document', b'{}', Digest('sha256', 'a' * 64),
        {'identity_constraint': IDENTITY_CONSTRAINT, 'authorAgentRef': author, 'reviewerAgentRef': reviewer},
        e['plan'].check_keys)


def test_original_reviewer_guard_rejects_author_mismatch_and_rolls_back_same_tx_revoke(env):
    e = env
    reviewer = _unit("reviewer-unit")
    assigned = _assign(e, reviewer, "guard-assignment")
    with e["factory"].begin(DOMAIN_SCOPE, "read") as uow:
        assignment, _control = uow.reviewer_assignments.active_for_review(e["plan"].review_id)
    reviewer_authority = SQLiteAgentReviewerAuthority(e["factory"], expected_access=e["access"],
        expected_scope=WIRE_SCOPE, assignments=e["assignments"],
        method_control=e["control"], agent_records=e["records"], agent_query_factory=e["query"],
        author_agent_resolver=e["author_resolver"])
    with pytest.raises(ApplicationError, match="UNIT_REVIEW_AUTHORITY_UNAVAILABLE"):
        SQLiteAgentReviewerAuthority(e["factory"], expected_access=e["access"],
            expected_scope=WireScope("foreign-realm", "foreign-project"), assignments=e["assignments"],
            method_control=e["control"], agent_records=e["records"], agent_query_factory=e["query"],
            author_agent_resolver=e["author_resolver"])
    foreign_lib = EngineeringLibrary.create((e["tmp_path"] / "foreign.sqlite").resolve(),
        library_id="foreign-reviewer-authority", schema_version=15)
    try:
        with pytest.raises(ApplicationError, match="UNIT_REVIEW_AUTHORITY_UNAVAILABLE"):
            SQLiteAgentReviewerAuthority(SQLiteUoWFactory(foreign_lib), expected_access=e["access"],
                expected_scope=WIRE_SCOPE, assignments=e["assignments"], method_control=e["control"],
                agent_records=e["records"], agent_query_factory=e["query"],
                author_agent_resolver=e["author_resolver"])
    finally:
        foreign_lib.close()
    raw_ref = BlobRef(Digest("sha256", "c" * 64), 4, "application/octet-stream", "test-raw-response")
    obs_digest = Digest("sha256", "d" * 64)
    bad_binding = _unit_binding(e, reviewer, _unit("unrelated-author"))
    with e["access"].admit(e["caller"], WIRE_SCOPE, ASSIGN, request_id="author-mismatch", trace_id="test") as ctx:
        with pytest.raises(ApplicationError, match="UNIT_REVIEW_AUTHOR_BINDING_UNAVAILABLE"):
            with reviewer_authority.guard_agent_reviewer(ctx, e["plan"], e["request"], bad_binding,
                    raw_ref, obs_digest):
                pytest.fail("mismatched author must never yield evidence")

    binding = _unit_binding(e, reviewer, e["author"])
    with e["access"].admit(e["caller"], WIRE_SCOPE, ASSIGN, request_id="same-tx-fence", trace_id="test") as ctx:
        with reviewer_authority.guard_agent_reviewer(ctx, e["plan"], e["request"], binding,
                raw_ref, obs_digest) as evidence:
            assert evidence.roles == tuple(sorted(e["plan"].reviewer_requirements))
            with e["factory"].begin(DOMAIN_SCOPE, "write") as uow:
                uow.commands.reserve(ctx.key, project_id=DOMAIN_SCOPE.project_id,
                    operation=ASSIGN, operation_id="race-command", request_digest=e["plan"].plan_digest)
                uow.reviewer_assignments.revoke(assignment.ref, expected_version=0,
                    revoked_at=ctx.received_at, reason="same transaction fence test", event_id="race-revoke")
                with pytest.raises(ApplicationError):
                    uow.commit()
    with e["factory"].begin(DOMAIN_SCOPE, "read") as uow:
        assert uow.reviewer_assignments.control(assignment.ref).state == "active"
        assert uow.commands.get(ctx.key) is None
    e["authority"].replace_grants((AccessGrant(WIRE_SCOPE, CAPS),))
    new_epoch_caller = e["authority"].authenticate("Bearer " + TOKEN)
    with e["access"].admit(new_epoch_caller, WIRE_SCOPE, ASSIGN,
                           request_id="new-issuer-epoch", trace_id="test") as new_ctx:
        with pytest.raises(ApplicationError, match="UNTRUSTED_REVIEWER"):
            with reviewer_authority.guard_agent_reviewer(new_ctx, e["plan"], e["request"], binding,
                    raw_ref, obs_digest):
                pytest.fail("assignment from an older issuer epoch must be refused")


def test_original_assignment_same_key_replay_and_conflict_do_not_requery_owner(env, monkeypatch):
    first = _assign(env, _unit("reviewer"), "fixed-request")
    def no_lookup(*args, **kwargs):
        raise AssertionError("replay/conflict must use the original command record")
    monkeypatch.setattr(env["records"], "read_agent_reference", no_lookup)
    replay = _assign(env, _unit("reviewer"), "fixed-request")
    assert replay.operation_id == first.operation_id and replay.result_bytes == first.result_bytes
    with pytest.raises(ApplicationError, match="REQUEST_IDENTITY_CONFLICT"):
        _assign(env, _unit("different-reviewer"), "fixed-request")
    with env["factory"].begin(DOMAIN_SCOPE, "read") as uow:
        record, control = uow.reviewer_assignments.active_for_review(env["plan"].review_id)
        assert record.reviewer_agent_ref == _unit("reviewer") and control.version == 0


def test_business_assignment_uses_actual_agent_binding_reads_and_live_read_revocation(env):
    """Original issuer + real Engineering UoW + original Agent read owner.

    Agent preparation is explicitly test-owned; no provider launch/send occurs.
    """
    import importlib.util
    from ordessa_engineering.adapters.native_records.agent_execution import AgentExecutionConsumer
    from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
    from ordessa_agents.public import AgentInstanceRef
    path=Path(__file__).resolve().parents[3]/'execution/agents/tests/sdk/interaction_fixtures.py'
    spec=importlib.util.spec_from_file_location('original_assignment_read_fixture',path)
    fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
    source,native_authority,_sender,reader=fixture.original_service(env['tmp_path']/'original-agent.sqlite')
    try:
        reviewer=AgentInstanceRef(fixture.INSTANCE.namespace,'actual-reviewer',fixture.MATERIAL.digest)
        observed=fixture.provenance(reviewer)
        source.records.publish_instance_binding(observed,'session-1',principal_scope='principal:test',protocol_id='acp')
        source.records.publish_instance_control(observed,SimpleNamespace(operation_ref='fixture-reviewer-start'),
            'principal:test',binding_material=fixture.MATERIAL)
        author=fixture.INSTANCE.projection()
        consumer=AgentExecutionConsumer(source,SQLiteBlobStore(env['lib']))
        def query(context,ref,plan,request,*,purpose):return reader
        def author_resolver(context,plan):return author
        assignments=build_reviewer_assignment_usecases(env['factory'],method_control=env['control'],
            records=consumer,expected_access=env['access'],expected_scope=WIRE_SCOPE,
            agent_query_factory=query,author_agent_resolver=author_resolver)
        case={**env,'assignments':assignments,'service':EngineeringService(env['factory'],env['access'],
            reviewer_assignments=assignments)}
        before=source.records._db.total_changes
        with pytest.raises(ApplicationError,match='UNTRUSTED_REVIEWER'):
            _assign(case,author,'actual-source-self-review')
        native_authority.denied.add('read')
        with pytest.raises(ApplicationError,match='AGENT_REVIEW_AUTHORITY_UNAVAILABLE'):
            _assign(case,reviewer.projection(),'actual-source-read-revoked')
        native_authority.denied.remove('read')
        result=_assign(case,reviewer.projection(),'actual-source-assigned')
        assert result.status=='completed'
        with env['factory'].begin(DOMAIN_SCOPE,'read') as uow:
            stored,control=uow.reviewer_assignments.active_for_review(env['plan'].review_id)
            assert stored.reviewer_agent_ref==reviewer.projection()
            assert stored.author_agent_ref==author and control.state=='active'
            assert stored.issuer_principal_id=='review-assignment-issuer'
        assert source.records._db.total_changes==before
        assert source.records._db.execute("SELECT count(*) FROM operations WHERE operation='turn'").fetchone()==(0,)
    finally:source.records.close()
