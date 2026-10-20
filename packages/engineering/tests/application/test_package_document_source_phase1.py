"""External source-reference proposal/review/package chain on original SQLite UoW.

Every external method, reviewer and source authority below is explicitly test
only. These fixtures are unpublished and cannot establish production trust.
"""
from contextlib import contextmanager
from dataclasses import asdict
from hashlib import sha256
import sqlite3
from types import SimpleNamespace

import pytest

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.api.service import EngineeringService
from ordessa_engineering.application.assembly import EngineeringPorts, build_engineering_service
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.reviewer_admission import (
    CriterionAnswer, SourceReviewBinding, VerifiedReviewResponse,
)
from ordessa_engineering.application.usecases.reviews.admission import (
    EngineeringReviewAdmission, review_observations,
)
from ordessa_engineering.domain.artifacts.method_binding import ExactMethodResourceRef, MethodRef
from ordessa_engineering.domain.artifacts.provenance import SourceLocator, SourceRef, VersionCapture
from ordessa_engineering.domain.changes.codec import encode_proposal
from ordessa_engineering.domain.changes.models import Proposal, SourceChange
from ordessa_engineering.domain.changes.ref_codec import decode_proposal_ref
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.packages.codec import decode_package, encode_package
from ordessa_engineering.domain.packages.models import (
    ImplementationPackage, PackageDocument, PreparedPackagePayload,
)
from ordessa_engineering.domain.reviews.evidence import VerifiedReviewerEvidence
from ordessa_engineering.domain.reviews.identity import RecordIdentity
from ordessa_engineering.domain.reviews.models import (
    AggregationPolicy, CheckKey, CheckPolicy, CriterionSetRef, CurrentReviewTrust,
    Observation, ReviewPlan, ReviewRequirement, observations_digest,
)
from ordessa_engineering.domain.reviews.targets import Target, TargetSet
from ordessa_engineering.methods.definitions.models.identity import ResourceRef


SCOPE = Scope("realm-external-chain-test", "project-external-chain-test")
ACTOR = ActorRef("test-author", "human", "explicit-test-only")
REVIEWER = ActorRef("test-reviewer", "human", "controlled-test-reviewer")
NOW = "2026-10-14T05:00:00.000000Z"
METHOD = MethodRef("test.unpublished.source-method", "0.0-test", 2, Digest("sha256", "a" * 64))
RESOURCE_BYTES = b"test-only exact method bytes"
RESOURCE = ExactMethodResourceRef(METHOD, "source/review.yaml",
    Digest("sha256", sha256(RESOURCE_BYTES).hexdigest()), "source-review")
BASE_RAW = b"DID: original\n"
CANDIDATE_RAW = b"DID: proposed\n"
LOCATOR = SourceLocator("document", provider="test-only-source", document_id="fixture:DID.md")


def _source(source_id, version, raw):
    return SourceRef(source_id, "document", LOCATOR,
        VersionCapture(version, Digest("sha256", sha256(raw).hexdigest())), NOW, ACTOR,
        "text/markdown", len(raw))


BASELINE = _source("baseline", "v1", BASE_RAW)
CANDIDATE = _source("candidate", "v2", CANDIDATE_RAW)


class _Access:
    def require(self, context, operation):
        return None


class _SourceMaterials:
    def __init__(self, factory, sources):
        self.factory = factory
        self.sources = dict(sources)
        self.read_count = 0

    def read(self, context, source_ref):
        self.read_count += 1
        try:
            return self.sources[source_ref.content_identity]
        except KeyError as exc:
            raise ApplicationError("SOURCE_VERSION_UNAVAILABLE") from exc


class _MethodGuard:
    def __init__(self, factory, *, required_roles=("design",)):
        self.factory = factory
        self.required_roles = required_roles
        self.active = 0
        self.definition = SimpleNamespace(method_ref=SimpleNamespace(
            method_id=METHOD.method_id, release_version=METHOD.release_version,
            schema_version=METHOD.schema_version, snapshot_digest=METHOD.snapshot_digest.hex),
            resources=(SimpleNamespace(resource_id=RESOURCE.resource_id,
                                       sha256=RESOURCE.resource_digest.hex),))

    @contextmanager
    def guard(self, context, method_ref):
        if method_ref != METHOD:
            raise ApplicationError("METHOD_PIN_MISMATCH")
        self.active += 1
        try:
            yield self.definition
        finally:
            self.active -= 1

    def read_resource(self, context, exact_ref):
        if exact_ref != RESOURCE:
            raise ApplicationError("METHOD_RESOURCE_MISMATCH")
        return RESOURCE_BYTES

    def preparation_roles(self, context, definition, resource_refs):
        assert definition is self.definition
        assert resource_refs == (RESOURCE,)
        return self.required_roles


class _SourceReviewBindings:
    def __init__(self, plan, standard):
        self.plan, self.standard = plan, standard

    def resolve_source_plan(self, context, plan, definition):
        if plan != self.plan or definition.method_ref.method_id != METHOD.method_id:
            raise ApplicationError("METHOD_REVIEW_PLAN_CHANGED")
        return SourceReviewBinding(self.plan, self.standard)


class _ReviewerSource:
    """Controlled synthetic reviewer. Evidence is not production authentication."""
    def __init__(self, standard, *, answer_status="satisfied", stale_trust=False):
        self.standard = standard
        self.answer_status = answer_status
        self.stale_trust = stale_trust
        self.trust_active = 0

    def verify_response(self, context, plan, request, raw_ref, *, standard):
        check_keys = plan.check_keys[:-1] if self.answer_status == "incomplete" else plan.check_keys
        status = "satisfied" if self.answer_status == "incomplete" else self.answer_status
        answers = tuple(CriterionAnswer(key, status, (), "test-only review")
                        for key in check_keys)
        observations = review_observations(plan, standard, answers)
        evidence = VerifiedReviewerEvidence(context.scope, REVIEWER, ("reviewer",),
            "test-verifier", "test/1", 7, plan.request_digest, raw_ref.digest,
            observations_digest(observations), Digest("sha256", "c" * 64))
        return VerifiedReviewResponse(evidence, answers)

    @contextmanager
    def guard_trust(self, context, records):
        self.trust_active += 1
        try:
            yield tuple(CurrentReviewTrust(record.ref,
                record.reviewer_evidence.verifier_id,
                record.reviewer_evidence.trust_version + int(self.stale_trust))
                for record in records)
        finally:
            self.trust_active -= 1


class _Standard:
    standard_id = "test-source-standard"

    def __init__(self):
        self.resource_ref = ResourceRef(RESOURCE.resource_id, RESOURCE.resource_digest.hex, "standard")
        check = SimpleNamespace(bindings={})
        policy = SimpleNamespace(satisfied="pass", violated="block", insufficient="manual", unknown="manual")
        self.criteria = (SimpleNamespace(criterion_id="source-consistency", checks=(check,),
            decision_policy=None, policy=policy),)


class _MethodControl:
    def __init__(self, factory):
        self.factory = factory


def _plan(standard):
    targets = TargetSet((Target.external("base", SCOPE, BASELINE),
                         Target.external("proposed", SCOPE, CANDIDATE)))
    keys = tuple(CheckKey(target, "source-consistency") for target in targets.targets)
    requirement = ReviewRequirement(SCOPE, "test-source-review", 1, "quality", targets, METHOD,
        CriterionSetRef(standard.standard_id, 1, Digest("sha256", RESOURCE.resource_digest.hex)),
        keys, ("reviewer",), "test-source-review", 2, (RESOURCE,))
    return ReviewPlan("test-source-review-1", requirement,
        tuple(CheckPolicy(key, True, True) for key in keys), AggregationPolicy(), ("reviewer",))


def _ctx(request_id):
    return CommandContext(SCOPE, "test-principal", ACTOR, request_id, NOW, "test-trace")


def _draft(proposal_id="draft"):
    value = Proposal(SCOPE, proposal_id, NOW, ACTOR, "change-unspecified", "External change",
        "Test-only source chain", (), (), (), (), METHOD, (), None, (), 2,
        SourceChange(BASELINE, CANDIDATE, (RESOURCE,)))
    projected = decode_json(encode_proposal(value))
    return {key: projected[key] for key in (
        "intent", "rationale", "mutations", "basis_sources", "claim_refs", "evidence_links",
        "method_ref", "review_requirement_templates", "implementation_intent", "supersedes_refs",
        "source_change")}


@pytest.fixture
def chain(tmp_path):
    library = EngineeringLibrary.create((tmp_path / "chain.sqlite").resolve(),
        library_id="test.external-record-chain", schema_version=16)
    factory = SQLiteUoWFactory(library)
    blobs = SQLiteBlobStore(library)
    sources = _SourceMaterials(factory, {
        BASELINE.content_identity: BASE_RAW, CANDIDATE.content_identity: CANDIDATE_RAW,
    })
    guard = _MethodGuard(factory)
    standard = _Standard()
    plan = _plan(standard)
    bindings = _SourceReviewBindings(plan, standard)
    reviewer = _ReviewerSource(standard)
    admission = EngineeringReviewAdmission(factory, _MethodControl(factory), None, reviewer,
        source_materials=sources, method_guard=guard, source_review_bindings=bindings)
    service = build_engineering_service(factory, EngineeringPorts(_Access(), review_admission=admission,
        source_materials=sources, method_guard=guard, source_review_bindings=bindings, blobs=blobs))
    try:
        yield SimpleNamespace(library=library, factory=factory, blobs=blobs, sources=sources,
            guard=guard, standard=standard, plan=plan, admission=admission,
            reviewer=reviewer, service=service)
    finally:
        library.close()


def _create_proposal(env, request_id="create-proposal"):
    result = __import__("asyncio").run(env.service.execute("engineering.proposals.create",
        {"change_id": None, "expected_version": 0, "draft": _draft()}, _ctx(request_id)))
    assert result.status == "completed"
    return decode_proposal_ref(result.result["proposal_ref"])


def _record_review(env):
    import asyncio
    request = asyncio.run(env.service.execute("engineering.reviews.request",
        {"plan": decode_json(__import__("ordessa_engineering.domain.reviews.codec", fromlist=["encode_plan"])
            .encode_plan(env.plan))}, _ctx("request-review")))
    assert request.status == "completed"
    return asyncio.run(env.service.execute("engineering.reviews.record", {
        "review_id": env.plan.review_id, "request_version": 0, "fence": 1,
        "raw_response_utf8": "test-only controlled reviewer response",
    }, _ctx("record-review")))


def _prepared_package(env, proposal_ref, review_ref, package_id="prepared-test"):
    payload = PreparedPackagePayload(BASELINE, CANDIDATE, proposal_ref, (review_ref,), METHOD,
        (RESOURCE,), (PackageDocument("design", CANDIDATE),))
    return ImplementationPackage(SCOPE, package_id, NOW, ACTOR, payload)


def test_public_chain_create_review_associate_freeze_get_reopen_same_refs(chain, monkeypatch):
    import asyncio
    env = chain
    from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteEngineeringUoW
    commits = []
    original_commit = SQLiteEngineeringUoW.commit
    def observe_commit(uow):
        commits.append((env.guard.active, env.reviewer.trust_active, env.sources.read_count))
        return original_commit(uow)
    monkeypatch.setattr(SQLiteEngineeringUoW, "commit", observe_commit)
    capabilities = {item.capability_id for item in env.service.bound_operation_capabilities().capabilities}
    assert {"engineering.proposals.create", "engineering.proposals.associate_review",
            "engineering.packages.freeze", "engineering.reviews.request"} <= capabilities
    proposal_ref = _create_proposal(env)
    assert _create_proposal(env) == proposal_ref
    review_result = _record_review(env)
    assert review_result.status == "completed" and review_result.result["verdict"] == "pass"
    from ordessa_engineering.domain.reviews.ref_codec import decode_review_ref
    review_ref = decode_review_ref(review_result.result["review_ref"])
    successor = asyncio.run(env.service.execute("engineering.proposals.associate_review", {
        "proposal_ref": asdict(proposal_ref), "expected_version": 1,
        "review_ref": asdict(review_ref),
    }, _ctx("associate-review")))
    assert successor.status == "completed"
    successor_ref = decode_proposal_ref(successor.result["proposal_ref"])
    package = _prepared_package(env, successor_ref, review_ref)
    package_wire = decode_json(encode_package(package))
    assert decode_package(canonical_bytes(package_wire)) == package
    frozen = asyncio.run(env.service.execute("engineering.packages.freeze",
        {"record": package_wire}, _ctx("freeze-prepared")))
    assert frozen.status == "completed" and frozen.result["dispatchable"] is False
    from ordessa_engineering.domain.packages.codec import decode_package_ref
    package_ref = decode_package_ref(frozen.result["package_ref"])
    replay = asyncio.run(env.service.execute("engineering.packages.freeze",
        {"record": package_wire}, _ctx("freeze-prepared")))
    assert replay == frozen
    altered = _prepared_package(env, successor_ref, review_ref, "same-key-different-content")
    with pytest.raises(ApplicationError, match="REQUEST_IDENTITY_CONFLICT"):
        asyncio.run(env.service.execute("engineering.packages.freeze",
            {"record": decode_json(encode_package(altered))}, _ctx("freeze-prepared")))
    assert any(method_active and reviewer_active and source_reads > 0
               for method_active, reviewer_active, source_reads in commits)
    with env.factory.begin(SCOPE, "read") as uow:
        stored = uow.implementation.resolve_package(package_ref)
        assert stored == package and stored.ref == package_ref
        assert uow.proposals.get_proposal(successor_ref).source_change.review_refs == (review_ref,)
        with pytest.raises(ApplicationError, match="IMPLEMENTATION_ENVELOPE_UNAVAILABLE"):
            from ordessa_engineering.application.usecases.packages.implementation import ImplementationUseCases
            ImplementationUseCases._resolve_package(uow, stored, now=NOW)
    # Historical decoding/readback is independent of a live external provider.
    env.sources.sources.clear()
    with env.factory.begin(SCOPE, "read") as uow:
        assert uow.proposals.get_proposal(successor_ref).ref == successor_ref
    env.library.close()
    reopened = EngineeringLibrary.open(env.library.path, library_id="test.external-record-chain")
    try:
        reopened_factory = SQLiteUoWFactory(reopened)
        reopened_service = build_engineering_service(reopened_factory, EngineeringPorts(_Access()))
        restored_package = asyncio.run(reopened_service.query("engineering.references.resolve",
            {"ref": asdict(package_ref)}, _ctx("read-reopened-package")))
        restored_proposal = asyncio.run(reopened_service.query("engineering.proposals.get",
            {"proposal_ref": asdict(successor_ref)}, _ctx("read-reopened-proposal")))
        assert restored_package.ref == package_ref
        assert restored_proposal.ref == successor_ref
        before_replay = reopened._connection.execute("SELECT COUNT(*) FROM eng_packages").fetchone()[0]
        reopened_replay = asyncio.run(reopened_service.execute("engineering.packages.freeze",
            {"record": package_wire}, _ctx("freeze-prepared")))
        assert reopened_replay == frozen
        assert reopened._connection.execute("SELECT COUNT(*) FROM eng_packages").fetchone()[0] == before_replay
    finally:
        reopened.close()


def test_withdrawn_proposal_control_blocks_prepared_package_freeze(chain):
    import asyncio
    from ordessa_engineering.domain.reviews.ref_codec import decode_review_ref
    env = chain
    proposal_ref = _create_proposal(env, "withdrawn-before-freeze")
    review_result = _record_review(env)
    review_ref = decode_review_ref(review_result.result["review_ref"])
    associated = asyncio.run(env.service.execute("engineering.proposals.associate_review", {
        "proposal_ref": asdict(proposal_ref), "expected_version": 1,
        "review_ref": asdict(review_ref),
    }, _ctx("associate-before-withdrawal")))
    final_ref = decode_proposal_ref(associated.result["proposal_ref"])
    package = _prepared_package(env, final_ref, review_ref, "withdrawn-package")
    with env.factory.begin(SCOPE) as uow:
        control = uow.proposals.control(final_ref, expected_version=0, disposition="withdrawn",
            replacement_ref=None, evidence=(Digest("sha256", "a" * 64),),
            at=NOW, actor=ACTOR, reason="controlled test withdrawal")
        assert control.disposition == "withdrawn"
        uow.commit()
    with pytest.raises(ApplicationError, match="PACKAGE_SOURCE_BINDING_MISMATCH"):
        asyncio.run(env.service.execute("engineering.packages.freeze",
            {"record": decode_json(encode_package(package))}, _ctx("freeze-withdrawn")))
    assert env.library._connection.execute("SELECT count(*) FROM eng_packages").fetchone()[0] == 0


def test_fresh_v1_proposal_write_is_refused_before_change_or_journal(chain):
    import asyncio
    env = chain
    legacy = _draft()
    legacy.pop("source_change")
    before = (env.library._connection.execute("SELECT count(*) FROM eng_changes").fetchone()[0],
              env.library._connection.execute("SELECT count(*) FROM eng_commands").fetchone()[0])
    with pytest.raises(ApplicationError, match="INVALID_INPUT"):
        asyncio.run(env.service.execute("engineering.proposals.create",
            {"change_id": None, "expected_version": 0, "draft": legacy}, _ctx("legacy-write")))
    assert before == (env.library._connection.execute("SELECT count(*) FROM eng_changes").fetchone()[0],
                      env.library._connection.execute("SELECT count(*) FROM eng_commands").fetchone()[0])


def test_historical_v1_package_is_not_a_new_package_write(chain):
    import asyncio
    import runpy
    helpers = runpy.run_path(str(__import__("pathlib").Path(__file__).parents[1]
        / "domain" / "test_implementation_package.py"))
    legacy = helpers["make_package"]()
    ctx = CommandContext(legacy.scope, "test-principal", legacy.created_by,
        "legacy-package-write", legacy.created_at, "test-trace")
    with pytest.raises(ApplicationError, match="IMPLEMENTATION_ENVELOPE_UNAVAILABLE"):
        asyncio.run(chain.service.execute("engineering.packages.freeze",
            {"record": decode_json(encode_package(legacy))}, ctx))
    assert chain.library._connection.execute("SELECT count(*) FROM eng_packages").fetchone()[0] == 0


def test_create_idempotency_and_conflicting_request_identity(chain):
    import asyncio
    env = chain
    ctx = _ctx("create-idempotent")
    params = {"change_id": None, "expected_version": 0, "draft": _draft()}
    first = asyncio.run(env.service.execute("engineering.proposals.create", params, ctx))
    assert asyncio.run(env.service.execute("engineering.proposals.create", params, ctx)) == first
    changed = {**params, "draft": {**params["draft"], "rationale": "changed under same key"}}
    with pytest.raises(ApplicationError, match="REQUEST_IDENTITY_CONFLICT"):
        asyncio.run(env.service.execute("engineering.proposals.create", changed, ctx))


def test_missing_baseline_source_authority_refuses_fresh_proposal_without_record(chain):
    import asyncio
    env = chain
    env.sources.sources.pop(BASELINE.content_identity)
    before = env.library._connection.execute("SELECT count(*) FROM eng_proposals").fetchone()[0]
    with pytest.raises(ApplicationError, match="SOURCE_VERSION_UNAVAILABLE"):
        asyncio.run(env.service.execute("engineering.proposals.create",
            {"change_id": None, "expected_version": 0, "draft": _draft()}, _ctx("baseline-missing")))
    assert env.library._connection.execute("SELECT count(*) FROM eng_proposals").fetchone()[0] == before


@pytest.mark.parametrize("mismatch", ["digest", "scope", "method", "resource", "change"])
def test_prepared_package_exact_links_and_external_pins_are_required(chain, mismatch):
    import asyncio
    from dataclasses import replace
    from ordessa_engineering.domain.reviews.ref_codec import decode_review_ref
    from ordessa_engineering.domain.packages.codec import encode_package
    from ordessa_engineering.domain.reviews.refs import ReviewRef
    env = chain
    proposal_ref = _create_proposal(env, f"create-{mismatch}")
    review_result = _record_review(env)
    review_ref = decode_review_ref(review_result.result["review_ref"])
    associated = asyncio.run(env.service.execute("engineering.proposals.associate_review", {
        "proposal_ref": asdict(proposal_ref), "expected_version": 1,
        "review_ref": asdict(review_ref),
    }, _ctx(f"associate-{mismatch}")))
    final_ref = decode_proposal_ref(associated.result["proposal_ref"])
    package = _prepared_package(env, final_ref, review_ref, f"bad-{mismatch}")
    payload = package.payload
    with pytest.raises((ApplicationError, ReferenceError)):
        if mismatch == "digest":
            bad_source = _source("candidate-bad-digest", "v2", b"different candidate\n")
            env.sources.sources[bad_source.content_identity] = CANDIDATE_RAW
            payload = replace(payload, candidate=bad_source)
        elif mismatch == "scope":
            from ordessa_engineering.domain.common.models.identity import Scope
            foreign_ref = replace(payload.change_ref, realm_id="foreign-realm")
            foreign_reviews = tuple(replace(ref, realm_id="foreign-realm") for ref in payload.review_refs)
            bad_package = replace(package, scope=Scope("foreign-realm", SCOPE.project_id),
                payload=replace(payload, change_ref=foreign_ref, review_refs=foreign_reviews))
            asyncio.run(env.service.execute("engineering.packages.freeze",
                {"record": decode_json(encode_package(bad_package))}, _ctx("freeze-bad-scope")))
            return
        elif mismatch == "method":
            other_method = replace(METHOD, method_id="wrong-method")
            other_resource = replace(RESOURCE, method_ref=other_method)
            payload = replace(payload, method_ref=other_method, method_resource_refs=(other_resource,))
        elif mismatch == "resource":
            payload = replace(payload, method_resource_refs=(ExactMethodResourceRef(METHOD,
                "source/other.yaml", Digest("sha256", "d" * 64), "other-resource"),))
        else:
            payload = replace(payload, change_ref=replace(final_ref, proposal_id="other"))
        bad_package = replace(package, payload=payload)
        asyncio.run(env.service.execute("engineering.packages.freeze",
            {"record": decode_json(encode_package(bad_package))}, _ctx(f"freeze-bad-{mismatch}")))


def test_completed_but_indeterminate_review_cannot_advance_proposal(chain):
    import asyncio
    env = chain
    proposal_ref = _create_proposal(env, "indeterminate-proposal")
    env.reviewer.answer_status = "unknown"
    result = _record_review(env)
    assert result.status == "completed" and result.result["verdict"] == "indeterminate"
    from ordessa_engineering.domain.reviews.ref_codec import decode_review_ref
    with pytest.raises(ApplicationError, match="PROPOSAL_REVIEW_ASSOCIATION_INVALID"):
        asyncio.run(env.service.execute("engineering.proposals.associate_review", {
            "proposal_ref": asdict(proposal_ref), "expected_version": 1,
            "review_ref": asdict(decode_review_ref(result.result["review_ref"])),
        }, _ctx("associate-indeterminate")))
    with env.factory.begin(SCOPE, "read") as uow:
        assert uow.proposals.get_change(proposal_ref.change_id).version == 1


def test_fail_verdict_and_changed_trust_cannot_advance_proposal(chain):
    import asyncio
    env = chain
    proposal_ref = _create_proposal(env, "failed-proposal")
    env.reviewer.answer_status = "violated"
    result = _record_review(env)
    assert result.status == "completed" and result.result["verdict"] == "fail"
    from ordessa_engineering.domain.reviews.ref_codec import decode_review_ref
    review_ref = decode_review_ref(result.result["review_ref"])
    with pytest.raises(ApplicationError, match="PROPOSAL_REVIEW_ASSOCIATION_INVALID"):
        asyncio.run(env.service.execute("engineering.proposals.associate_review", {
            "proposal_ref": asdict(proposal_ref), "expected_version": 1,
            "review_ref": asdict(review_ref),
        }, _ctx("associate-fail")))


def test_incomplete_reviewer_answers_create_no_review_and_do_not_advance_change(chain):
    import asyncio
    from ordessa_engineering.domain.reviews.models import ReviewSetKey
    env = chain
    proposal_ref = _create_proposal(env, "incomplete-review-proposal")
    env.reviewer.answer_status = "incomplete"
    with pytest.raises(ApplicationError, match="REVIEW_SOURCE_INCOMPLETE"):
        _record_review(env)
    with env.factory.begin(SCOPE, "read") as uow:
        assert uow.reviews.read_set(ReviewSetKey.for_requirement(env.plan.requirement)).reviews == ()
        assert uow.proposals.get_change(proposal_ref.change_id).version == 1


def test_association_rechecks_current_trust_and_change_cas(chain):
    import asyncio
    from dataclasses import replace
    env = chain
    proposal_ref = _create_proposal(env, "trust-proposal")
    result = _record_review(env)
    from ordessa_engineering.domain.reviews.ref_codec import decode_review_ref
    review_ref = decode_review_ref(result.result["review_ref"])
    env.reviewer.stale_trust = True
    with pytest.raises(ApplicationError, match="UNTRUSTED_REVIEWER"):
        asyncio.run(env.service.execute("engineering.proposals.associate_review", {
            "proposal_ref": asdict(proposal_ref), "expected_version": 1,
            "review_ref": asdict(review_ref),
        }, _ctx("associate-stale-trust")))
    env.reviewer.stale_trust = False
    with pytest.raises(ApplicationError, match="SCOPE_MISMATCH"):
        asyncio.run(env.service.execute("engineering.proposals.associate_review", {
            "proposal_ref": asdict(proposal_ref), "expected_version": 1,
            "review_ref": asdict(replace(review_ref, realm_id="foreign-realm")),
        }, _ctx("associate-foreign-review")))
    with env.factory.begin(SCOPE, "read") as uow:
        assert uow.proposals.get_change(proposal_ref.change_id).version == 1


def test_withdrawn_review_request_cannot_advance_proposal(chain):
    import asyncio
    from ordessa_engineering.application.usecases.reviews.service import ReviewUseCases
    from ordessa_engineering.domain.reviews.refs import ReviewRef
    env = chain
    proposal_ref = _create_proposal(env, "cancelled-proposal")
    asyncio.run(env.service.execute("engineering.reviews.request", {
        "plan": decode_json(__import__("ordessa_engineering.domain.reviews.codec", fromlist=["encode_plan"])
            .encode_plan(env.plan))}, _ctx("request-to-cancel")))
    review_usecases = ReviewUseCases(env.factory, _Access(), env.admission, blobs=env.blobs)
    withdrawn = review_usecases.withdraw(env.plan.review_id, _ctx("withdraw-review"),
        expected_request_version=0, fence=1)
    assert withdrawn.status == "completed"
    missing_review = ReviewRef(SCOPE.realm_id, SCOPE.project_id, env.plan.review_id,
                               Digest("sha256", "e" * 64))
    with pytest.raises(ApplicationError, match="NOT_FOUND"):
        asyncio.run(env.service.execute("engineering.proposals.associate_review", {
            "proposal_ref": asdict(proposal_ref), "expected_version": 1,
            "review_ref": asdict(missing_review),
        }, _ctx("associate-cancelled")))
    with env.factory.begin(SCOPE, "read") as uow:
        assert uow.proposals.get_change(proposal_ref.change_id).version == 1


def test_immutable_trigger_blocks_tampering_and_corrupt_read_is_not_source_unavailable(chain):
    import asyncio
    env = chain
    proposal_ref = _create_proposal(env, "tamper-control-proposal")
    with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE_RECORD"):
        env.library._connection.execute(
            "UPDATE eng_proposals SET canonical_bytes=? WHERE realm_id=? AND project_id=? AND proposal_id=?",
            (b"{}", proposal_ref.realm_id, proposal_ref.project_id, proposal_ref.proposal_id))
    trigger_sql = env.library._connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name='eng_proposals_no_update'").fetchone()[0]
    env.library._connection.execute("DROP TRIGGER eng_proposals_no_update")
    env.library._connection.execute(
        "UPDATE eng_proposals SET canonical_bytes=? WHERE realm_id=? AND project_id=? AND proposal_id=?",
        (b"{}", proposal_ref.realm_id, proposal_ref.project_id, proposal_ref.proposal_id))
    env.library._connection.execute(trigger_sql)
    with env.factory.begin(SCOPE, "read") as uow:
        with pytest.raises(ApplicationError, match="RECORD_CORRUPT"):
            uow.proposals.get_proposal(proposal_ref)


def test_missing_actual_method_or_source_binding_refuses_and_is_not_advertised(chain):
    import asyncio
    env = chain
    incomplete = EngineeringService(env.factory, _Access(), blobs=env.blobs)
    incomplete_capabilities = {item.capability_id
        for item in incomplete.bound_operation_capabilities().capabilities}
    assert "engineering.proposals.create" not in incomplete_capabilities
    assert "engineering.proposals.associate_review" not in incomplete_capabilities
    assert "engineering.packages.freeze" not in incomplete_capabilities
    with pytest.raises(ApplicationError):
        asyncio.run(incomplete.execute("engineering.proposals.create",
            {"change_id": None, "expected_version": 0, "draft": _draft()}, _ctx("no-source-authority")))
