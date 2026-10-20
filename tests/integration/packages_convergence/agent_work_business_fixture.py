"""New 2.7.3 fixture: same original Work consent/review/control construction.

The original nightly test file and all its assertions stay unchanged. This
fixture selects the explicit new action candidate; controlled provider and
consent attestation do not claim production human authentication.
"""
import asyncio, hashlib, sys
from pathlib import Path
from contextlib import contextmanager
from dataclasses import asdict
ROOT=Path(__file__).parents[3]
SUPPORT=ROOT/'packages/engineering/tests/application'
if str(SUPPORT) not in sys.path:sys.path.insert(0,str(SUPPORT))
from test_work_package_approval_flow_v2 import (
    _open_work, _Admission, _start_approval, _answer,
    ConsentPolicyRef, ConversationSource, RepositoryScope, PathRule, ActionScope,
    WorkPackageAuthorization, ActionBudgetSlot, WorkPackageNotice,
    WorkPackageAuthorizationIntent, ConversationAdmission, ImplementationIntentAdmission,
    EngineeringService, WORK_CONTEXT_KIND, WORK_STABLE_ID_PREFIX, WORK_ID,
    EnvironmentRef, POLICY_PATH, PRINCIPAL, NOW, SCOPE, Digest, migrations,
    run_full_chain, close_chain, ApplicationError)
from test_itemized_source_chain import itemized_entries, ItemizedControlledProvider
from test_real_source_chain import build_local_chain


def build_agent_candidate_chain(directory, *, method_directory=None):
    entries=itemized_entries()
    return build_local_chain(directory,ItemizedControlledProvider(),
        method_directory=method_directory or ROOT/'methods/incremental-engineering/candidates/2.7.3',
        material_entries=entries,caller_material_index=len(entries)-1)


@contextmanager
def build_agent_work_package_approval(tmp_path, *, issue_grant=False, environment_ref=None, method_directory=None):
    env = build_agent_candidate_chain(tmp_path, method_directory=method_directory)
    try:
        chain = run_full_chain(env)
        if method_directory is None:
            assert env.method.release_version == "2.7.3"
        else:
            import json
            assert env.method.release_version == json.loads((Path(method_directory)/'method.json').read_text())['release_version']
        opened = _open_work(env, chain.package_ref)
        assert opened.status == "completed"
        # The real Work/package records are written first; schema17 is then
        # explicitly applied to this isolated fixture database.
        migrations.migrate_schema16(env.library, backup_path=(tmp_path / "schema16-backup.sqlite").resolve())
        # Schema migration mutates this isolated EngineeringLibrary in place;
        # retain its original factory so every authority shares its identity.
        factory = env.factory
        with factory.begin(SCOPE, "read") as uow:
            head = uow.workflow.head_ref(WORK_CONTEXT_KIND, WORK_STABLE_ID_PREFIX + WORK_ID)
        assert head is not None and head.revision == 1

        raw_policy = POLICY_PATH.read_bytes()
        policy = ConsentPolicyRef(
            "ordessa.product.v1.chat-attested-confirmation", 1,
            Digest("sha256", hashlib.sha256(raw_policy).hexdigest()))
        source = ConversationSource("controlled-test/transcript", (),
            "Synthetic captured test transcript; no platform identity is asserted.", PRINCIPAL, NOW)
        intent_id = "work-package-approval-intent"
        repository_scope = RepositoryScope("test-repository", (
            PathRule("src", "subtree", ("modify",)),))
        environment_refs = () if environment_ref is None else (environment_ref,)
        if environment_ref is not None and type(environment_ref) is not EnvironmentRef:
            raise TypeError("environment_ref must be an EnvironmentRef")
        action_scope = ActionScope(SCOPE.project_id, (repository_scope,), environment_refs,
                                   (), (), intent_id)
        authorization = WorkPackageAuthorization(
            scope=SCOPE, intent_id=intent_id, work_id=WORK_ID, work_revision=head.revision,
            work_digest=Digest("sha256", head.digest.removeprefix("sha256:")),
            action_id="incremental.implement-package", step_id="implement",
            package_ref=chain.package_ref, method_ref=env.method,
            actions=("edit_repository", "run_checks"),
            scope_by_action=(("edit_repository", action_scope), ("run_checks", action_scope)),
            action_budgets=(ActionBudgetSlot("edit_repository", 1), ActionBudgetSlot("run_checks", 1)),
            request_summary="Approve implementation of this exact frozen package.",
            not_before=NOW, expires_at="2026-10-15T12:00:00.000000Z")
        notice = WorkPackageNotice("work-package-approval-notice", authorization,
            "Approve this exact frozen Work/package.", source, policy)
        intent = WorkPackageAuthorizationIntent(authorization, notice.ref, policy)

        @contextmanager
        def attestor_guard(ctx, selected_policy):
            if ctx.principal_id != PRINCIPAL or selected_policy != policy:
                raise ApplicationError("UNTRUSTED_CONSENT_ATTESTOR")
            yield

        @contextmanager
        def intent_guard(ctx, selected_intent):
            if selected_intent.method_ref != env.method or selected_intent.authorization.work_id != WORK_ID:
                raise ApplicationError("METHOD_SUBJECT_BINDING_MISMATCH")
            yield

        conversation = ConversationAdmission(raw_policy, policy,
            attestor_guard=attestor_guard, intent_guard=intent_guard)
        implementation_admission = ImplementationIntentAdmission(factory, env.controls, bindings=object())
        admission = _Admission(conversation, implementation_admission)
        service = EngineeringService(factory, env.service._access,
            review_admission=env.admission, blobs=env.blobs, conversation_admission=admission,
            method_guard=env.controls, source_materials=env.materials,
            source_review_bindings=env.bindings)
        fixture = {"env": env, "factory": factory, "service": service, "head": head,
                   "authorization": authorization, "notice": notice, "intent": intent,
                   "source": source, "policy": policy, "package_ref": chain.package_ref}
        if issue_grant:
            _notice, _prepared, challenge = _start_approval(fixture)
            fixture["challenge"] = challenge
            fixture["grant_result"] = _answer(fixture, challenge)
        yield fixture
    finally:
        close_chain(env)

