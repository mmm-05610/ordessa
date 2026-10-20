"""Proposal commands on the real schema-7 UoW with test-only authority ports."""
from __future__ import annotations
from ordessa_engineering.application.usecases.material_closure import verify_material

from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader

from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
import sys

import pytest
import asyncio
from types import SimpleNamespace
from ordessa_infrastructure.encoding import canonical_bytes, decode_json

from ordessa_engineering.adapters.persistence.sqlite import engineering_library as storage
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import (
    SQLiteUoWFactory,
    SQLiteEngineeringUoW,
)
from ordessa_engineering.adapters.persistence.sqlite.proposal_repository import SQLiteProposalRepository
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.usecases.changes.proposals import ProposalUseCases
from ordessa_engineering.domain.artifacts.models import Artifact, ArtifactRevision, InlinePayload
from ordessa_engineering.domain.artifacts.provenance import (Claim)
from ordessa_engineering.domain.common.models.selection import (ContentSelector)
from ordessa_engineering.domain.artifacts.method_binding import (MethodRef)
from ordessa_engineering.domain.changes.refs import (ProposalRef)
from ordessa_engineering.domain.changes.models import (Change)
from ordessa_engineering.domain.common.models.values import (Digest)
from ordessa_engineering.domain.common.models.identity import (Scope)
from ordessa_engineering.domain.common.models.identity import (ActorRef)
from ordessa_engineering.domain.reviews.models import (CriterionSetRef)
from ordessa_engineering.domain.reviews.codec import decode_requirement
from ordessa_engineering.domain.reviews.requirements import (
    ReviewRequirementTemplate, TemplateCheck, TemplateTarget, SubjectSelector,
)
from ordessa_engineering.methods import compile_method
from ordessa_engineering.methods.definitions.models import CompilationCapabilities, MethodSource
from ordessa_engineering.methods.loading.loader import load_method
from ordessa_engineering.application.usecases.publish_snapshot import freeze_method


LIBRARY_ID = "test.proposal-usecases"
CREATED_AT = "2026-10-09T12:00:00.000000Z"
ACTOR = ActorRef("test-human", "human", "synthetic-proposal-test")
SCOPE = Scope("realm-proposal", "project-proposal")


class SyntheticAccess:
    """Test allow port only; ActorRef fields do not authenticate a caller."""

    def __init__(self):
        self.calls = []

    def require(self, context, operation):
        self.calls.append((context, operation))


class EmptyCatalog:
    __test__ = False

    def read_current(self):
        return CompilationCapabilities((), "synthetic-empty-catalog", "host")


class SyntheticControlAdmission:
    """Explicit test evidence port with hooks for ordering and CAS races."""

    def __init__(self, library):
        self.library = library
        self.depth = 0
        self.calls = []
        self.on_guard = None

    @contextmanager
    def guard_control(self, context, proposal, control, disposition, replacement):
        assert not self.library._connection.in_transaction
        self.depth += 1
        self.calls.append((context, proposal.ref, control, disposition, replacement))
        callback, self.on_guard = self.on_guard, None
        try:
            if callback is not None:
                callback(proposal, control)
            yield (Digest("sha256", "d" * 64),)
        finally:
            if not self.library._closed:
                assert not self.library._connection.in_transaction
            self.depth -= 1


@pytest.fixture
def environment(tmp_path: Path):
    path = (tmp_path / "proposals.sqlite").resolve()
    library = EngineeringLibrary.create(path, library_id=LIBRARY_ID, schema_version=7)
    factory = SQLiteUoWFactory(library)
    access = SyntheticAccess()
    method_ref = _publish_method(library, tmp_path / "published-method")
    try:
        yield library, factory, access, method_ref
    finally:
        library.close()


def _source_stack(library):
    """Assemble the explicitly test-only source chain on this exact UoW factory."""
    import importlib.util
    helper_path = Path(__file__).with_name("test_package_document_source_phase1.py")
    spec = importlib.util.spec_from_file_location("_proposal_source_chain_fixtures", helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("source-chain test fixture could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    factory = SQLiteUoWFactory(library)
    blobs = SQLiteBlobStore(library)
    sources = module._SourceMaterials(factory, {
        module.BASELINE.content_identity: module.BASE_RAW,
        module.CANDIDATE.content_identity: module.CANDIDATE_RAW,
    })
    method_guard = module._MethodGuard(factory)
    standard = module._Standard()
    plan = module._plan(standard)
    bindings = module._SourceReviewBindings(plan, standard)
    reviewer = module._ReviewerSource(standard)
    admission = module.EngineeringReviewAdmission(
        factory, module._MethodControl(factory), None, reviewer,
        source_materials=sources, method_guard=method_guard,
        source_review_bindings=bindings,
    )
    service = module.EngineeringService(
        factory, module._Access(), review_admission=admission,
        source_materials=sources, method_guard=method_guard,
        source_review_bindings=bindings, blobs=blobs,
    )
    return SimpleNamespace(
        module=module, library=library, factory=factory, blobs=blobs,
        sources=sources, method_guard=method_guard, service=service,
    )


@pytest.fixture
def source_environment(tmp_path: Path):
    library = EngineeringLibrary.create(
        (tmp_path / "proposal-source-chain.sqlite").resolve(),
        library_id="test.proposal-source-chain", schema_version=16,
    )
    stack = _source_stack(library)
    try:
        yield stack
    finally:
        library.close()


def _source_create(stack, request_id, *, change_id=None, expected_version=0,
                   context=None, draft=None, operation="engineering.proposals.create"):
    module = stack.module
    context = module._ctx(request_id) if context is None else context
    draft = module._draft() if draft is None else draft
    return asyncio.run(stack.service.execute(
        operation,
        {"change_id": change_id, "expected_version": expected_version,
         "draft": draft} if operation == "engineering.proposals.create" else draft,
        context,
    ))


def _publish_method(library, root):
    root.mkdir()
    workflow = {
        "schema_version": 1, "entry": "done",
        "steps": [{"id": "done", "kind": "stop", "outcome": "finished"}],
        "stop_outcomes": ["finished"], "wait_kinds": [],
    }
    raw = json.dumps(workflow, separators=(",", ":")).encode()
    (root / "workflow.yaml").write_bytes(raw)
    manifest = {
        "schema_version": 1, "method_id": "test.proposal.method", "release_version": "1.0.0",
        "compiler_contract": "ordessa.methods/v1", "entry": {"resource": "workflow.main"},
        "resources": [{"id": "workflow.main", "kind": "workflow", "path": "workflow.yaml",
                       "media_type": "application/yaml", "sha256": hashlib.sha256(raw).hexdigest()}],
        "requires": [],
    }
    (root / "method.yaml").write_text(json.dumps(manifest, separators=(",", ":")))
    loaded = load_method(MethodSource(root), reader=FileResourceReader())
    assert loaded.ok and loaded.value is not None, loaded.error
    compiled = compile_method(loaded.value, CompilationCapabilities(()), "test.compiler/1")
    assert compiled.ok and compiled.value is not None, compiled.error
    store = SQLiteSnapshotStore(library)
    frozen = freeze_method(compiled.value, store, store, capability_catalog=EmptyCatalog())
    assert frozen.ok and frozen.value is not None, frozen.error
    released = frozen.value.ref
    return MethodRef(released.method_id, released.release_version, released.schema_version,
                     Digest("sha256", released.snapshot_digest))


def _ctx(scope=SCOPE, request_id="request-1"):
    return CommandContext(scope, "principal-1", ACTOR, request_id, CREATED_AT, "trace-1")


def _proposal_ref(value):
    return ProposalRef(value["realm_id"], value["project_id"], value["change_id"],
                       value["proposal_id"], Digest(**value["digest"]))


def _usecases(factory, access, control=None):
    return ProposalUseCases(factory, access, control)


def _digest(raw: bytes) -> Digest:
    return Digest("sha256", hashlib.sha256(raw).hexdigest())


def _artifact_graph(factory, *, claim_text="supported statement"):
    """Persist a real owner and a two-node revision graph with a verifiable claim."""
    claim_selector = ContentSelector("json_pointer", pointer="/statement")
    payload = InlinePayload.from_value("application/json", "urn:test:proposal", {"statement": claim_text})
    # The claim digest is over the exact selected canonical JSON bytes.
    claim = Claim("claim-1", claim_selector, _digest(canonical_bytes(claim_text)))
    with factory.begin(SCOPE) as uow:
        uow.engineering.create(Artifact(SCOPE, "artifact-1", "plan", CREATED_AT))
        base = ArtifactRevision(SCOPE, "artifact-1", "revision-base", CREATED_AT, ACTOR,
                                payload, schema_version=2, claims=(claim,))
        verify_material(base, uow.engineering.validated_budget())
        base_ref = uow.engineering.append_revision(base, expected_version=0)
        proposed = ArtifactRevision(SCOPE, "artifact-1", "revision-proposed", CREATED_AT, ACTOR,
                                    InlinePayload.from_value("application/json", "urn:test:proposal",
                                                             {"statement": claim_text, "proposed": True}),
                                    schema_version=2, parent_revision_refs=(base_ref,))
        verify_material(proposed, uow.engineering.validated_budget())
        proposed_ref = uow.engineering.append_revision(proposed, expected_version=1)
        uow.commit()
    return base_ref, proposed_ref, claim


def _template(method_ref, *, claim_id="claim-1"):
    specifications = (
        ("primary", SubjectSelector("self_proposal"), None),
        ("base", SubjectSelector("base_mutation", 0), None),
        ("proposed", SubjectSelector("proposed_mutation", 0), None),
        ("support", SubjectSelector("claim_owner", 0), claim_id),
    )
    targets = tuple(TemplateTarget(role, selector) for role, selector, _claim in specifications)
    checks = tuple(TemplateCheck(target, f"criterion-{index}", claim_id)
                   if _claim is not None else TemplateCheck(target, f"criterion-{index}")
                   for index, (target, (_role, _selector, _claim)) in enumerate(zip(targets, specifications)))
    return ReviewRequirementTemplate(
        SCOPE, "template-proposal", 1, "quality", targets, method_ref,
        CriterionSetRef("criteria-proposal", 1, Digest("sha256", "a" * 64)),
        checks, ("reviewer",), "proposal-phase",
    )


def _draft(method_ref, base_ref, proposed_ref, claim, *, template=True, supersedes=(), intent=None):
    from dataclasses import asdict
    from ordessa_engineering.domain.artifacts.provenance import (ClaimRef)
    claim_ref = ClaimRef(base_ref, "claim-1", claim.statement_digest)
    fields = {
        "intent": "Revise the plan from verified source material.",
        "rationale": "The proposed revision is bounded by the stored base.",
        "mutations": [{"artifact_id": "artifact-1", "operation": "revise",
                       "base_ref": asdict(base_ref), "proposed_ref": asdict(proposed_ref)}],
        "basis_sources": [], "claim_refs": [asdict(claim_ref)], "evidence_links": [],
        "method_ref": asdict(method_ref),
        "review_requirement_templates": [asdict(_template(method_ref))] if template else [],
        "implementation_intent": None if intent is None else asdict(intent),
        "supersedes_refs": [asdict(ref) for ref in supersedes],
    }
    return fields


def _rows(library, table):
    assert table in {
        "eng_changes", "eng_proposals", "eng_proposal_mutations", "eng_proposal_controls",
        "eng_proposal_control_events", "eng_review_requirements", "eng_commands",
        "eng_artifacts", "eng_artifact_revisions",
    }
    return library._connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _create(factory, access, method_ref, base_ref, proposed_ref, claim, request_id, *,
            change_id=None, expected_version=0, supersedes=(), template=True, intent=None):
    """Legacy fixture projection backed by an explicit historical-v1 seed.

    This helper exists for read/control consumers that need old canonical rows;
    it does not invoke ProposalUseCases.create or represent a journaled command.
    """
    change_id = change_id or f"historical-change-{request_id}"
    ref = _seed_historical_v1(
        factory, method_ref, base_ref, proposed_ref, claim,
        proposal_id=f"historical-{request_id}", change_id=change_id,
        expected_version=expected_version, supersedes=supersedes,
        template=template, create_change=expected_version == 0,
    )
    return HistoricalSeedProjection(ref, change_id)


@dataclass(frozen=True)
class HistoricalSeedProjection:
    """Small test-only reference projection; it has no command status/result."""

    proposal_ref: ProposalRef
    change_id: str

    @property
    def result(self):
        return {"proposal_ref": asdict(self.proposal_ref),
                "change": {"change_id": self.change_id}}


def _seed_historical_v1(factory, method_ref, base_ref, proposed_ref, claim, *,
                        proposal_id, change_id, expected_version=0,
                        supersedes=(), template=True, create_change=True):
    """Seed a historical v1 row directly; never routes through the new writer."""
    from ordessa_engineering.domain.changes.codec import decode_draft
    from ordessa_engineering.application.usecases.proposal_closure import validate_create

    draft = _draft(method_ref, base_ref, proposed_ref, claim,
                   template=template, supersedes=supersedes)
    # Match the public command's canonical JSON boundary before invoking the
    # historical decoder; tuple/list normalization remains codec-owned.
    wire_draft = decode_json(canonical_bytes(draft))
    record = decode_draft(SCOPE, proposal_id, CREATED_AT, ACTOR, change_id,
                          wire_draft, schema_version=1)
    with factory.begin(SCOPE, "write") as uow:
        if create_change:
            uow.proposals.create_change(Change(SCOPE, change_id, CREATED_AT))
        budget = uow.proposals.validated_budget()
        requirements = validate_create(record, uow.proposals, budget)
        ref = uow.proposals.create_proposal(
            record, expected_version=expected_version, budget=budget,
            requirements=requirements,
        )
        uow.commit()
    return ref


def test_facade_proposal_create_exact_query_control_and_retry(environment):
    from ordessa_engineering.application.api.service import EngineeringService
    library, factory, access, method_ref = environment
    base_ref, proposed_ref, claim = _artifact_graph(factory)
    admission = SyntheticControlAdmission(library)
    facade = EngineeringService(factory, access, proposal_control_admission=admission)
    historical_ref = _seed_historical_v1(
        factory, method_ref, base_ref, proposed_ref, claim,
        proposal_id="historical-facade-proposal", change_id="historical-facade-change",
    )
    ref = asdict(historical_ref)
    saved = asyncio.run(facade.query("engineering.proposals.get", {"proposal_ref": ref}, _ctx(request_id="facade-read")))
    assert saved.ref == _proposal_ref(ref) and saved.method_ref == method_ref
    assert asyncio.run(facade.query("engineering.references.resolve", {"ref": ref}, _ctx(request_id="facade-read"))) == saved
    control = asyncio.run(facade.query("engineering.proposals.get_control", {"proposal_ref": ref}, _ctx(request_id="facade-read")))
    withdrawn = asyncio.run(facade.execute("engineering.proposals.withdraw",
        {"proposal_ref": ref, "expected_version": control.version, "reason": "synthetic withdrawal"},
        _ctx(request_id="facade-withdraw")))
    assert withdrawn.status == "completed"
    assert asyncio.run(facade.execute("engineering.proposals.withdraw",
        {"proposal_ref": ref, "expected_version": control.version, "reason": "synthetic withdrawal"},
        _ctx(request_id="facade-withdraw"))) == withdrawn
    assert len(admission.calls) == 1
    assert _rows(library, "eng_proposals") == 1


def test_historical_v1_claim_templates_and_material_closure_remain_readable(environment):
    library, factory, _access, method_ref = environment
    base_ref, proposed_ref, claim = _artifact_graph(factory)
    proposal_ref = _seed_historical_v1(
        factory, method_ref, base_ref, proposed_ref, claim,
        proposal_id="historical-material-proposal", change_id="historical-material-change",
    )
    assert _rows(library, "eng_proposals") == _rows(library, "eng_proposal_controls") == 1
    assert _rows(library, "eng_proposal_control_events") == 1
    assert _rows(library, "eng_review_requirements") == 1
    with factory.begin(SCOPE, "read") as uow:
        saved = uow.proposals.get_proposal(proposal_ref)
        requirement_bytes = uow._access.execute(
            "SELECT canonical_bytes FROM eng_review_requirements LIMIT 1").fetchone()[0]
        uow.commit()
    assert saved.method_ref == method_ref
    assert saved.claim_refs[0].owner_revision_ref == base_ref
    requirement = decode_requirement(requirement_bytes)
    target_by_role = {target.role: target.ref for target in requirement.expected_targets.targets}
    assert type(target_by_role["primary"]) is ProposalRef
    assert target_by_role["base"] == base_ref
    assert target_by_role["proposed"] == proposed_ref
    assert target_by_role["support"] == base_ref
    claim_checks = [key for key in requirement.required_check_keys if key.claim_id == "claim-1"]
    assert len(claim_checks) == 1 and claim_checks[0].target.ref == base_ref
    artifact_state = library._connection.execute(
        "SELECT version,head_revision_id FROM eng_artifacts WHERE artifact_id='artifact-1'").fetchone()
    assert artifact_state == (2, None)
    assert _rows(library, "eng_commands") == 0  # history seed is not a new command


def test_fresh_v1_proposal_write_is_refused_before_change_or_journal(environment):
    _library, factory, access, method_ref = environment
    base_ref, proposed_ref, claim = _artifact_graph(factory)
    context = _ctx(request_id="fresh-v1-refusal")
    parameters = {"change_id": None, "expected_version": 0,
                  "draft": _draft(method_ref, base_ref, proposed_ref, claim)}
    with pytest.raises(ApplicationError) as caught:
        _usecases(factory, access).create(parameters, context)
    assert caught.value.code == "INVALID_INPUT"
    assert _rows(_library, "eng_changes") == _rows(_library, "eng_proposals") == 0
    assert _rows(_library, "eng_commands") == 0


def test_schema2_change_cas_refusal_is_journaled_without_partial_proposal(source_environment):
    stack = source_environment
    library = stack.library
    module = stack.module
    first = _source_create(stack, "first-schema2-change")
    assert first.status == "completed"
    from ordessa_engineering.domain.changes.ref_codec import decode_proposal_ref
    proposal_ref = decode_proposal_ref(first.result["proposal_ref"])
    counts = tuple(_rows(library, table) for table in (
        "eng_proposals", "eng_proposal_mutations", "eng_proposal_controls", "eng_review_requirements"))
    rejected = _source_create(stack, "stale-schema2-change", change_id=proposal_ref.change_id,
                              expected_version=0)
    assert rejected.status == "rejected" and rejected.result == {"code": "VERSION_CONFLICT"}
    assert tuple(_rows(library, table) for table in (
        "eng_proposals", "eng_proposal_mutations", "eng_proposal_controls", "eng_review_requirements")) == counts
    assert _rows(library, "eng_commands") == 2


@pytest.mark.parametrize("identity_factor", [
    "draft", "change_id", "expected_version", "project", "operation",
])
def test_schema2_same_request_key_rejects_changed_proposal_identity(
    source_environment, identity_factor,
):
    stack = source_environment
    module = stack.module
    request_id = f"schema2-identity-{identity_factor}"
    first = _source_create(stack, request_id)
    assert first.status == "completed"
    from ordessa_engineering.domain.changes.ref_codec import decode_proposal_ref
    proposal_ref = decode_proposal_ref(first.result["proposal_ref"])
    if identity_factor == "draft":
        changed = module._draft()
        changed["rationale"] = "changed under the same durable request key"
        context = module._ctx(request_id)
        operation = "engineering.proposals.create"
        change_id, expected_version, parameters = None, 0, changed
    elif identity_factor == "change_id":
        context = module._ctx(request_id)
        operation = "engineering.proposals.create"
        change_id, expected_version, parameters = "different-change-id", 0, module._draft()
    elif identity_factor == "expected_version":
        context = module._ctx(request_id)
        operation = "engineering.proposals.create"
        change_id, expected_version, parameters = proposal_ref.change_id, 1, module._draft()
    elif identity_factor == "project":
        context = replace(module._ctx(request_id),
                          scope=Scope(module.SCOPE.realm_id, "other-project"))
        operation = "engineering.proposals.create"
        change_id, expected_version, parameters = None, 0, module._draft()
    else:
        context = module._ctx(request_id)
        operation = "engineering.proposals.select"
        change_id, expected_version = None, 0
        parameters = {"proposal_ref": asdict(proposal_ref), "expected_version": 0}

    counts = tuple(_rows(stack.library, table) for table in
                   ("eng_changes", "eng_proposals", "eng_commands"))
    with pytest.raises(ApplicationError) as conflict:
        if operation == "engineering.proposals.select":
            _usecases(stack.factory, module._Access()).select(parameters, context)
        else:
            _source_create(stack, request_id, change_id=change_id,
                           expected_version=expected_version, context=context,
                           draft=parameters, operation=operation)
    expected_code = "SCOPE_MISMATCH" if identity_factor == "project" else "REQUEST_IDENTITY_CONFLICT"
    assert conflict.value.code == expected_code
    assert tuple(_rows(stack.library, table) for table in
                 ("eng_changes", "eng_proposals", "eng_commands")) == counts


def test_fresh_v1_claim_input_is_refused_before_change_or_journal(environment):
    library, factory, access, method_ref = environment
    base_ref, proposed_ref, claim = _artifact_graph(factory)
    draft = _draft(method_ref, base_ref, proposed_ref, claim, template=False)
    # These old artifact/claim/template and implementation-intent inputs belong
    # only to historical v1 records. They cannot enter the schema2 writer.
    draft["claim_refs"][0]["statement_digest"] = asdict(Digest("sha256", "f" * 64))
    context = _ctx(request_id="fresh-v1-claim-refusal")
    with pytest.raises(ApplicationError) as refused:
        _usecases(factory, access).create(
            {"change_id": None, "expected_version": 0, "draft": draft}, context,
        )
    assert refused.value.code == "INVALID_INPUT"
    assert _rows(library, "eng_commands") == 0
    assert _rows(library, "eng_proposals") == _rows(library, "eng_changes") == 0


def test_missing_access_and_missing_control_admission_refuse_without_new_command(environment):
    library, factory, access, method_ref = environment
    base_ref, proposed_ref, claim = _artifact_graph(factory)
    parameters = {"change_id": None, "expected_version": 0,
                  "draft": _draft(method_ref, base_ref, proposed_ref, claim, template=False)}
    with pytest.raises(ApplicationError) as no_access:
        _usecases(factory, None).create(parameters, _ctx(request_id="no-access"))
    assert no_access.value.code == "ACCESS_AUTHORITY_UNAVAILABLE"
    historical_ref = _seed_historical_v1(
        factory, method_ref, base_ref, proposed_ref, claim,
        proposal_id="historical-control-target", change_id="historical-control-change",
        template=False,
    )
    control = asdict(historical_ref)
    count = _rows(library, "eng_commands")
    with pytest.raises(ApplicationError) as no_control:
        _usecases(factory, access).withdraw(
            {"proposal_ref": control, "expected_version": 0, "reason": "synthetic"},
            _ctx(request_id="no-control-admission"),
        )
    assert no_control.value.code == "PROPOSAL_CONTROL_AUTHORITY_UNAVAILABLE"
    assert _rows(library, "eng_commands") == count
    assert _rows(library, "eng_proposal_controls") == 1


def test_select_and_supersedes_refs_leave_controls_available_until_explicit_control(
    environment,
):
    library, factory, access, method_ref = environment
    base_ref, proposed_ref, claim = _artifact_graph(factory)
    first = _create(factory, access, method_ref, base_ref, proposed_ref, claim, "first-proposal")
    first_ref = _proposal_ref(first.result["proposal_ref"])
    change_id = first.result["change"]["change_id"]
    second = _create(factory, access, method_ref, base_ref, proposed_ref, claim, "second-proposal",
                     change_id=change_id, expected_version=1, supersedes=(first_ref,), template=False)
    second_ref = _proposal_ref(second.result["proposal_ref"])
    control = _usecases(factory, access, SyntheticControlAdmission(library))
    selected = control.select({"proposal_ref": asdict(second_ref), "expected_version": 2},
                              _ctx(request_id="select-second"))
    assert selected.status == "completed"
    assert selected.result["change"]["selected_proposal_id"] == second_ref.proposal_id
    assert control.get_control(first_ref, _ctx(request_id="read-first-control")).disposition == "available"
    assert control.get_control(second_ref, _ctx(request_id="read-second-control")).disposition == "available"
    assert _rows(library, "eng_proposal_control_events") == 2


def test_withdraw_guard_spans_commit_and_control_cas_is_journaled(environment, monkeypatch):
    library, factory, access, method_ref = environment
    base_ref, proposed_ref, claim = _artifact_graph(factory)
    created = _create(factory, access, method_ref, base_ref, proposed_ref, claim, "control-target",
                      template=False)
    ref = _proposal_ref(created.result["proposal_ref"])
    admission = SyntheticControlAdmission(library)
    usecases = _usecases(factory, access, admission)
    original_commit = SQLiteEngineeringUoW.commit
    def checked_commit(uow):
        assert admission.depth == 1
        return original_commit(uow)
    monkeypatch.setattr(SQLiteEngineeringUoW, "commit", checked_commit)
    withdrawn = usecases.withdraw(
        {"proposal_ref": asdict(ref), "expected_version": 0, "reason": "withdraw test"},
        _ctx(request_id="withdraw-once"),
    )
    assert withdrawn.status == "completed"
    assert admission.depth == 0 and len(admission.calls) == 1
    assert usecases.get_control(ref, _ctx(request_id="control-read")).disposition == "withdrawn"
    assert _rows(library, "eng_proposal_control_events") == 2


def test_control_cas_race_commits_only_inner_transition_and_outer_rejection(environment):
    library, factory, access, method_ref = environment
    base_ref, proposed_ref, claim = _artifact_graph(factory)
    created = _create(factory, access, method_ref, base_ref, proposed_ref, claim, "cas-control-target",
                      template=False)
    ref = _proposal_ref(created.result["proposal_ref"])
    admission = SyntheticControlAdmission(library)
    journal_before = _rows(library, "eng_commands")
    def race(proposal, current):
        with factory.begin(SCOPE) as uow:
            uow.proposals.control(proposal.ref, expected_version=current.version,
                disposition="withdrawn", replacement_ref=None,
                evidence=(Digest("sha256", "c" * 64),), at=CREATED_AT, actor=ACTOR,
                reason="concurrent transition")
            uow.commit()
    admission.on_guard = race
    outer = _usecases(factory, access, admission).withdraw(
        {"proposal_ref": asdict(ref), "expected_version": 0, "reason": "late transition"},
        _ctx(request_id="cas-control-outer"),
    )
    assert outer.status == "rejected" and outer.result == {"code": "PROPOSAL_CONTROL_CHANGED"}
    assert _rows(library, "eng_proposal_control_events") == 2
    # The historical seed creates no command row; only the outer journaled
    # rejection adds one. The inner repository control mutation is not journaled.
    assert _rows(library, "eng_commands") == journal_before + 1
    assert _usecases(factory, access).get_control(ref, _ctx(request_id="cas-control-read")).disposition == "withdrawn"


@pytest.mark.parametrize("fault", ["proposal_insert", "proposal_after_insert", "journal_complete"])
def test_schema2_proposal_and_journal_faults_rollback_together(
    source_environment, monkeypatch, fault,
):
    stack = source_environment
    library = stack.library
    sql = []
    if fault == "proposal_insert":
        library._connection.execute("""
            CREATE TEMP TRIGGER fail_proposal_insert BEFORE INSERT ON eng_proposals
            BEGIN SELECT RAISE(ABORT, 'injected proposal insert failure'); END
        """)
    elif fault == "proposal_after_insert":
        original_create = SQLiteProposalRepository.create_proposal
        def fail_after_insert(self, *args, **kwargs):
            original_create(self, *args, **kwargs)
            raise ApplicationError("STORAGE_UNAVAILABLE", retry="reconcile")
        monkeypatch.setattr(SQLiteProposalRepository, "create_proposal", fail_after_insert)
    else:
        from ordessa_engineering.adapters.persistence.sqlite.command_journal import (
            SQLiteCommandJournal,
        )
        def fail_complete(self, *args, **kwargs):
            raise ApplicationError("STORAGE_UNAVAILABLE", retry="reconcile")
        monkeypatch.setattr(SQLiteCommandJournal, "complete", fail_complete)
    library._connection.set_trace_callback(sql.append)
    try:
        with pytest.raises(ApplicationError):
            _source_create(stack, f"schema2-fault-{fault}")
    finally:
        library._connection.set_trace_callback(None)
    if fault == "proposal_insert":
        assert any(statement.lstrip().upper().startswith("INSERT")
                   and "INTO ENG_PROPOSALS" in statement.upper() for statement in sql)
    assert _rows(library, "eng_changes") == _rows(library, "eng_proposals") == 0
    assert _rows(library, "eng_proposal_mutations") == _rows(library, "eng_proposal_controls") == 0
    assert _rows(library, "eng_review_requirements") == 0
    assert _rows(library, "eng_commands") == 0


def test_commit_lost_reply_reopens_and_replays_durable_proposal_without_duplicate(
    tmp_path: Path, monkeypatch,
):
    path = (tmp_path / "proposal-commit-lost.sqlite").resolve()
    initial = EngineeringLibrary.create(path, library_id="test.proposal-commit-lost", schema_version=16)
    initial.close()
    base_connection = storage._LibraryConnection
    class LostCommitReply(base_connection):
        def commit(self):
            result = super().commit()
            if getattr(self, "lose_next_proposal_reply", False):
                self.lose_next_proposal_reply = False
                raise RuntimeError("synthetic committed proposal reply loss")
            return result
    monkeypatch.setattr(storage, "_LibraryConnection", LostCommitReply)
    uncertain_library = EngineeringLibrary.open(path, library_id="test.proposal-commit-lost")
    uncertain_stack = _source_stack(uncertain_library)
    uncertain_library._connection.lose_next_proposal_reply = True
    params = {"change_id": None, "expected_version": 0,
              "draft": uncertain_stack.module._draft()}
    context = uncertain_stack.module._ctx("proposal-commit-lost")
    with pytest.raises(ApplicationError) as uncertain:
        asyncio.run(uncertain_stack.service.execute("engineering.proposals.create", params, context))
    assert uncertain.value.code == "COMMIT_UNKNOWN" and uncertain_library._closed
    reopened = EngineeringLibrary.open(path, library_id="test.proposal-commit-lost")
    try:
        restored_stack = _source_stack(reopened)
        saved = asyncio.run(restored_stack.service.execute("engineering.proposals.create", params, context))
        assert saved.status == "completed"
        assert asyncio.run(restored_stack.service.execute("engineering.proposals.create", params, context)) == saved
        assert _rows(reopened, "eng_changes") == _rows(reopened, "eng_proposals") == 1
        assert _rows(reopened, "eng_proposal_controls") == _rows(reopened, "eng_commands") == 1
        assert _rows(reopened, "eng_review_requirements") == 0
    finally:
        reopened.close()
