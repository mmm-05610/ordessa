"""Versioned human-readable chat binding on the original approval records.

All chat text and identities in this module are synthetic test values. The
tests exercise the host presentation guard and original challenge gates; they
do not record a real answer or issue a grant.
"""
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone, timedelta
import hashlib
from pathlib import Path

import pytest

from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.adapters.confirmation.conversation import ConversationAdmission
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.approvals.consent import (
    ConsentChallenge,
    ConsentPolicyRef,
    AuthorizationIntent,
    ConversationEvidence,
    ConversationNotice,
    ConversationSource,
    WorkPackageNotice,
)
from ordessa_engineering.domain.approvals.implementation import (
    ActionBudgetSlot,
    WorkPackageAuthorization,
    WorkPackageAuthorizationIntent,
)
from ordessa_engineering.domain.approvals.scope import ActionScope, PathRule, RepositoryScope
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
from ordessa_engineering.domain.common.models.identity import Scope as DomainScope
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.packages.refs import ImplementationPackageRef
from ordessa_engineering.domain.reviews.models import CheckKey, CriterionSetRef, ReviewRequirement
from ordessa_engineering.domain.reviews.targets import Target, TargetSet
from ordessa_server.composition.engineering_chat_confirmation import (
    CANONICAL_PRESENTATION_CONTRACT,
    HUMAN_PRESENTATION_CONTRACT,
    FrozenChatPresentation,
    MainAgentChatConfirmation,
    confirmation_presentation,
)
from ordessa_server.composition.engineering_human_source import SOURCE_LIMITATION
from ordessa_server.composition.conversation_attestor import RegisteredMainAgentAttestor
from ordessa_interfaces.system_access.access_control.authentication import (
    AccessGrant,
    AccessError,
    InstanceAccessAuthority,
)
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess

from .test_engineering_slice import SCOPE


CAPS = (
    "engineering.approvals.get_challenge",
    "engineering.approvals.record_conversation",
    "engineering.conversation.attest",
)
LOCATOR = "chat://synthetic-human-presentation-test"
NOW = "2026-10-17T10:00:00.000000Z"
PRINCIPAL = "registered-main-agent"
NONCE = "synthetic-human-presentation-nonce"
CHALLENGE_ID = "human-presentation-pending"
LEGACY_CHALLENGE_ID = "canonical-presentation-pending"


def _iso(value):
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _human_renderer(intent, notice, *, presented_at):
    authorization = intent.authorization
    context = (
        "Synthetic approved scope:\n"
        f"Work: {authorization.work_id} revision {authorization.work_revision}\n"
        f"Package: {authorization.package_ref.package_id}\n"
        f"Actions: {', '.join(authorization.actions)}\n"
        "Paths: catalog/views.py (modify only)\n"
        f"Valid until: {authorization.expires_at}"
    )
    question = (
        "Synthetic status: review is complete; implementation has not started.\n\n"
        "Synthetic request: approve only the following frozen work and scope.\n\n"
        f"{context}\n\n"
        "Synthetic reply instruction: answer explicitly; review completion alone is not approval."
    )
    return {"question": question, "necessary_context": context}


@pytest.fixture
def schema17_factory(tmp_path):
    library = EngineeringLibrary.create(
        (tmp_path / "human-binding-schema17.sqlite").resolve(),
        library_id="human-binding-schema17",
        schema_version=17,
    )
    try:
        yield SQLiteUoWFactory(library)
    finally:
        library.close()


def _setup(factory, *, expires_at="2027-01-01T00:00:00.000000Z", presented_at=None):
    policy_path = Path(__file__).resolve().parents[3] / (
        "methods/incremental-engineering/policies/product-chat-confirmation.v1.yaml"
    )
    raw_policy = policy_path.read_bytes()
    policy = ConsentPolicyRef(
        "ordessa.product.v1.chat-attested-confirmation",
        1,
        Digest("sha256", hashlib.sha256(raw_policy).hexdigest()),
    )
    scope = DomainScope(SCOPE.realm_id, SCOPE.project_id)

    source = ConversationSource(
        LOCATOR,
        (),
        "Synthetic notice source; no actual human or platform identity is asserted.",
        PRINCIPAL,
        NOW,
    )
    target_ref = ArtifactRevisionRef(
        scope.realm_id,
        scope.project_id,
        "synthetic-artifact",
        "synthetic-revision",
        Digest("sha256", "0" * 64),
    )
    method_ref = MethodRef("synthetic-method", "1.0", 1, Digest("sha256", "1" * 64))
    target = Target("primary", target_ref)
    requirement = ReviewRequirement(
        scope,
        "synthetic-requirement",
        1,
        "quality",
        TargetSet((target,)),
        method_ref,
        CriterionSetRef("synthetic-criteria", 1, Digest("sha256", "2" * 64)),
        (CheckKey(target, "synthetic-check"),),
        ("reviewer",),
        "synthetic-phase",
    )
    legacy_notice = ConversationNotice(
        scope,
        "human-binding-legacy-notice",
        (target_ref,),
        target_ref,
        "Synthetic canonical notice.",
        source,
        policy,
    )
    legacy_intent = AuthorizationIntent(
        scope,
        "human-binding-legacy-intent",
        (target_ref,),
        method_ref,
        legacy_notice.ref,
        policy,
        (requirement,),
        "reference",
        "Synthetic canonical intent.",
        "2026-01-01T00:00:00.000000Z",
        "2027-01-01T00:00:00.000000Z",
    )

    intent_id = "human-binding-work-package-intent"
    action_scope = ActionScope(
        SCOPE.project_id,
        (RepositoryScope("synthetic-catalog", (PathRule("catalog/views.py", "exact", ("modify",)),)),),
        (),
        (),
        (),
        intent_id,
    )
    authorization = WorkPackageAuthorization(
        scope=scope,
        intent_id=intent_id,
        work_id="synthetic-work-package-review",
        work_revision=1,
        work_digest=Digest("sha256", "1" * 64),
        action_id="incremental.implement-package",
        step_id="implement",
        package_ref=ImplementationPackageRef(
            scope.realm_id,
            scope.project_id,
            "synthetic-package",
            Digest("sha256", "2" * 64),
        ),
        method_ref=method_ref,
        actions=("edit_repository",),
        scope_by_action=(("edit_repository", action_scope),),
        action_budgets=(ActionBudgetSlot("edit_repository", 1),),
        request_summary="Synthetic closed authorization summary.",
        not_before="2026-01-01T00:00:00.000000Z",
        expires_at=expires_at,
    )
    human_notice = WorkPackageNotice(
        "human-binding-work-package-notice",
        authorization,
        "Synthetic notice body for presentation-binding tests.",
        source,
        policy,
    )
    human_intent = WorkPackageAuthorizationIntent(authorization, human_notice.ref, policy)

    authority = InstanceAccessAuthority(
        lambda: "synthetic-human-presentation-token",
        principal_id=PRINCIPAL,
        legacy_principal=None,
        grants=(AccessGrant(SCOPE, CAPS),),
    )
    access = EngineeringCommandAccess(authority)
    attestor = RegisteredMainAgentAttestor(
        access,
        scope=SCOPE,
        principal_id=PRINCIPAL,
        selected_policy_ref=policy,
    )

    @contextmanager
    def intent_guard(context, selected):
        if selected.scope != legacy_intent.scope or selected.policy_ref != policy:
            raise ApplicationError("METHOD_SUBJECT_BINDING_MISMATCH")
        yield

    admission = ConversationAdmission(
        raw_policy,
        policy,
        attestor_guard=attestor.guard,
        intent_guard=intent_guard,
    )
    presented_at = presented_at or _iso(datetime.now(timezone.utc) - timedelta(seconds=2))
    binding = FrozenChatPresentation(
        human_intent,
        human_notice,
        presented_at,
        _human_renderer,
    )
    service = MainAgentChatConfirmation(
        factory,
        admission,
        conversation_locator=LOCATOR,
        presentation_binding=binding,
    )

    nonce_digest = Digest("sha256", hashlib.sha256(NONCE.encode()).hexdigest())
    legacy_nonce = "synthetic-legacy-nonce"
    with factory.begin(legacy_intent.scope, "write") as uow:
        repo = uow.authorization
        repo.put_notice(legacy_notice)
        repo.put_intent(legacy_intent)
        repo.put_notice(human_notice)
        repo.put_intent(human_intent)
        repo.put_challenge(
            ConsentChallenge(
                human_intent.scope,
                CHALLENGE_ID,
                human_intent.intent_id,
                human_intent.digest,
                human_notice.digest,
                nonce_digest,
                human_intent.expires_at,
            )
        )
        repo.put_challenge(
            ConsentChallenge(
                legacy_intent.scope,
                LEGACY_CHALLENGE_ID,
                legacy_intent.intent_id,
                legacy_intent.digest,
                legacy_notice.digest,
                Digest("sha256", hashlib.sha256(legacy_nonce.encode()).hexdigest()),
                legacy_intent.expires_at,
            )
        )
        uow.commit()
    return {
        "access": access,
        "authority": authority,
        "binding": binding,
        "factory": factory,
        "human_intent": human_intent,
        "human_notice": human_notice,
        "legacy_intent": legacy_intent,
        "legacy_notice": legacy_notice,
        "legacy_nonce": legacy_nonce,
        "policy": policy,
        "service": service,
    }


def _context(setup, capability, request_id):
    caller = setup["authority"].authenticate("Bearer synthetic-human-presentation-token")
    return setup["access"].admit(caller, SCOPE, capability, request_id=request_id, trace_id=request_id)


def _evidence(setup, context, *, question=None, necessary_context=None, limitations=None):
    presentation = setup["service"]._presentation(
        setup["human_intent"], setup["human_notice"]
    )[0]
    source = ConversationSource(
        LOCATOR,
        ("synthetic-question-ref", "synthetic-answer-ref"),
        limitations or (
            SOURCE_LIMITATION
            + "; presentation_contract="
            + HUMAN_PRESENTATION_CONTRACT
        ),
        context.principal_id,
        context.received_at,
    )
    return ConversationEvidence(
        "synthetic-human-presentation-evidence",
        presentation["question"] if question is None else question,
        presentation["necessary_context"] if necessary_context is None else necessary_context,
        "Synthetic explicit consent answer for this test only.",
        source,
        setup["policy"],
        setup["human_intent"].digest,
        setup["human_notice"].ref,
        "confirm",
    )


def _assert_pending(setup, challenge_id=CHALLENGE_ID):
    with setup["factory"].begin(setup["human_intent"].scope, "read") as uow:
        assert uow.authorization.get_challenge(challenge_id)[1:] == ("pending", 0)


def test_human_presentation_displays_and_accepts_the_exact_full_message(schema17_factory):
    setup = _setup(schema17_factory)
    with _context(setup, CAPS[0], "human-presentation-prepare") as context:
        view = setup["service"].prepare(setup["access"], context, CHALLENGE_ID)
    assert view["presentation_contract"] == HUMAN_PRESENTATION_CONTRACT
    assert view["display_text"] == view["question"]
    assert view["question"].count(view["necessary_context"]) == 1
    assert view["necessary_context"] in view["display_text"]
    assert "nonce" not in view

    with _context(setup, CAPS[1], "human-presentation-guard") as context:
        evidence = _evidence(setup, context)
        with setup["service"].guard_evidence(context, setup["human_intent"], evidence):
            pass
    _assert_pending(setup)


@pytest.mark.parametrize(
    "change",
    ["missing-marker", "wrong-marker", "duplicate-marker", "changed-question", "changed-context"],
)
def test_human_presentation_refuses_changed_text_or_contract_before_any_grant(schema17_factory, change):
    setup = _setup(schema17_factory)
    with _context(setup, CAPS[1], "human-presentation-negative-" + change) as context:
        presentation = setup["service"]._presentation(
            setup["human_intent"], setup["human_notice"]
        )[0]
        limitations = SOURCE_LIMITATION + "; presentation_contract=" + HUMAN_PRESENTATION_CONTRACT
        question = presentation["question"]
        necessary_context = presentation["necessary_context"]
        if change == "missing-marker":
            limitations = SOURCE_LIMITATION
        elif change == "wrong-marker":
            limitations = SOURCE_LIMITATION + "; presentation_contract=ordessa.work-package-chat-human/2"
        elif change == "duplicate-marker":
            limitations += "; presentation_contract=" + HUMAN_PRESENTATION_CONTRACT
        elif change == "changed-question":
            question += " changed"
        elif change == "changed-context":
            necessary_context += " changed"
        evidence = _evidence(
            setup,
            context,
            question=question,
            necessary_context=necessary_context,
            limitations=limitations,
        )
        with pytest.raises(ApplicationError, match="CONSENT_PRESENTATION_CHANGED"):
            with setup["service"].guard_evidence(context, setup["human_intent"], evidence):
                pytest.fail("changed human presentation accepted")
    _assert_pending(setup)


def test_selected_intent_digest_mismatch_does_not_fall_back_to_canonical(schema17_factory):
    setup = _setup(schema17_factory)
    with _context(setup, CAPS[1], "human-presentation-digest-mismatch") as context:
        evidence = _evidence(setup, context)
        altered_authorization = replace(
            setup["human_intent"].authorization,
            request_summary="Changed authorization under the same stable intent id.",
        )
        altered_intent = WorkPackageAuthorizationIntent(
            altered_authorization,
            setup["human_notice"].ref,
            setup["policy"],
        )
        altered_evidence = replace(
            evidence,
            intent_digest=altered_intent.digest,
        )
        with pytest.raises(ApplicationError, match="CONSENT_BINDING_MISMATCH"):
            with setup["service"].guard_evidence(context, altered_intent, altered_evidence):
                pytest.fail("selected id with changed authorization fell back")
    _assert_pending(setup)


def test_selected_intent_id_with_changed_scope_is_not_routed_to_canonical(schema17_factory):
    setup = _setup(schema17_factory)
    original_authorization = setup["human_intent"].authorization
    altered_scope = replace(original_authorization.scope, project_id="different-project")
    altered_authorization = replace(
        original_authorization,
        scope=altered_scope,
        package_ref=replace(original_authorization.package_ref, project_id=altered_scope.project_id),
        scope_by_action=tuple(
            (action, replace(scope, project_id=altered_scope.project_id))
            for action, scope in original_authorization.scope_by_action
        ),
    )
    altered_notice = replace(setup["human_notice"], authorization=altered_authorization)
    altered_intent = WorkPackageAuthorizationIntent(
        altered_authorization,
        altered_notice.ref,
        setup["policy"],
    )
    with pytest.raises(ApplicationError, match="CONSENT_BINDING_MISMATCH"):
        setup["service"]._presentation(altered_intent, altered_notice)


def test_other_intent_keeps_exact_legacy_canonical_presentation(schema17_factory):
    setup = _setup(schema17_factory)
    with _context(setup, CAPS[0], "legacy-canonical-prepare") as context:
        view = setup["service"].prepare(setup["access"], context, LEGACY_CHALLENGE_ID)
    expected = confirmation_presentation(setup["legacy_intent"], setup["legacy_notice"])
    assert view["presentation_contract"] == CANONICAL_PRESENTATION_CONTRACT
    assert view["question"] == expected["question"]
    assert view["necessary_context"] == expected["necessary_context"]
    assert view["display_text"] == expected["question"] + "\n\n" + expected["necessary_context"]

    with _context(setup, CAPS[1], "legacy-canonical-guard") as context:
        evidence = ConversationEvidence(
            "synthetic-legacy-evidence",
            expected["question"],
            expected["necessary_context"],
            "Synthetic legacy-format confirmation only.",
            ConversationSource(LOCATOR, ("synthetic-legacy-ref",), SOURCE_LIMITATION,
                context.principal_id, context.received_at),
            setup["policy"],
            setup["legacy_intent"].digest,
            setup["legacy_notice"].ref,
            "confirm",
        )
        with setup["service"].guard_evidence(context, setup["legacy_intent"], evidence):
            pass


def test_selected_human_intent_cannot_switch_to_canonical_marker(schema17_factory):
    setup = _setup(schema17_factory)
    with _context(setup, CAPS[1], "human-marker-cannot-switch") as context:
        evidence = _evidence(
            setup,
            context,
            limitations=(SOURCE_LIMITATION + "; presentation_contract="
                         + CANONICAL_PRESENTATION_CONTRACT),
        )
        with pytest.raises(ApplicationError, match="CONSENT_PRESENTATION_CHANGED"):
            with setup["service"].guard_evidence(context, setup["human_intent"], evidence):
                pytest.fail("human presentation was accepted under canonical marker")
    _assert_pending(setup)


@pytest.mark.parametrize("captured_at", ["before", "after-expiry"])
def test_human_capture_must_be_after_presentation_and_before_expiry(schema17_factory, captured_at):
    if captured_at == "after-expiry":
        now = datetime.now(timezone.utc)
        expiry = _iso(now - timedelta(seconds=5))
        presented_at = _iso(now - timedelta(seconds=10))
    else:
        expiry = "2027-01-01T00:00:00.000000Z"
        presented_at = None
    setup = _setup(schema17_factory, expires_at=expiry, presented_at=presented_at)
    binding = setup["binding"]
    if captured_at == "before":
        instant = _iso(datetime.fromisoformat(binding.presented_at.replace("Z", "+00:00"))
                       - timedelta(microseconds=1))
    else:
        instant = setup["human_intent"].expires_at
    with _context(setup, CAPS[1], "human-capture-time-" + captured_at) as context:
        evidence = _evidence(setup, context)
        evidence = replace(evidence, source=replace(evidence.source, captured_at=instant))
        with pytest.raises(ApplicationError, match="INVALID_CONSENT_TIME"):
            with setup["service"].guard_evidence(context, setup["human_intent"], evidence):
                pytest.fail("capture outside the displayed validity interval was accepted")
    _assert_pending(setup)


def test_revoked_original_authority_refuses_human_evidence(schema17_factory):
    setup = _setup(schema17_factory)
    setup["authority"].revoke()
    with pytest.raises(AccessError):
        with _context(setup, CAPS[1], "human-authority-revoked"):
            pytest.fail("revoked instance authority admitted human evidence")
    _assert_pending(setup)


def test_admission_assembly_keeps_host_selected_presentation_binding(schema17_factory):
    from ordessa_server.composition.engineering_admission import assemble_engineering_admission

    setup = _setup(schema17_factory)
    policy_path = Path(__file__).resolve().parents[3] / (
        "methods/incremental-engineering/policies/product-chat-confirmation.v1.yaml"
    )
    raw_policy = policy_path.read_bytes()

    class SelectedOwner:
        pass

    def selected_intent_guard_factory(_controls, _bindings):
        def guard(_context, _intent):
            raise ApplicationError("METHOD_SELECTION_UNAVAILABLE")
        return guard

    # The composition owns the binding; it is supplied through the host API,
    # never recovered from caller-controlled wire arguments.
    assembly = assemble_engineering_admission(
        setup["factory"], setup["access"], SCOPE,
        management=SelectedOwner(),
        bindings=SelectedOwner(),
        reviewer_source=SelectedOwner(),
        policy_bytes=raw_policy,
        policy_ref=setup["policy"],
        intent_guard_factory=selected_intent_guard_factory,
        conversation_locator=LOCATOR,
        presentation_binding=setup["binding"],
    )
    conversation = assembly.application_ports.conversation_admission
    assert isinstance(conversation, MainAgentChatConfirmation)
    assert conversation.presentation_binding is setup["binding"]
    assert assembly.methods.factory is setup["factory"]
    assert assembly.application_ports.review_admission.factory is setup["factory"]
    with _context(setup, CAPS[0], "assembled-human-binding-method-guard") as context:
        with pytest.raises(ApplicationError, match="METHOD_SELECTION_UNAVAILABLE"):
            conversation.prepare(setup["access"], context, CHALLENGE_ID)
    _assert_pending(setup)


def test_original_nonce_and_review_gates_still_block_recording(schema17_factory):
    setup = _setup(schema17_factory)
    with _context(setup, CAPS[0], "human-record-prepare") as context:
        view = setup["service"].prepare(setup["access"], context, CHALLENGE_ID)

    with _context(setup, CAPS[1], "human-record-wrong-nonce") as context:
        with pytest.raises(ApplicationError, match="CONSENT_BINDING_MISMATCH"):
            setup["service"].record(
                setup["access"], None, context,
                challenge_id=CHALLENGE_ID,
                nonce="wrong-synthetic-nonce",
                expected_version=0,
                evidence_id="synthetic-wrong-nonce",
                question=view["question"],
                necessary_context=view["necessary_context"],
                user_answer="Synthetic explicit answer.",
                disposition="confirm",
                message_refs=("synthetic-question-ref", "synthetic-answer-ref"),
                captured_at=context.received_at,
            )
    _assert_pending(setup)

    with _context(setup, CAPS[1], "human-record-review-gate") as context:
        with pytest.raises(ApplicationError, match="REVIEW_AUTHORITY_UNAVAILABLE"):
            setup["service"].record(
                setup["access"], None, context,
                challenge_id=CHALLENGE_ID,
                nonce=NONCE,
                expected_version=0,
                evidence_id="synthetic-answer-without-review-authority",
                question=view["question"],
                necessary_context=view["necessary_context"],
                user_answer="Synthetic explicit answer.",
                disposition="confirm",
                message_refs=("synthetic-question-ref", "synthetic-answer-ref"),
                captured_at=context.received_at,
            )
    _assert_pending(setup)
