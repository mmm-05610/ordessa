"""Real schema17 generation effect guard, with a controlled local SDK thread."""
import asyncio
import hashlib
import queue
import sys
import time
import traceback
from dataclasses import asdict, replace
from threading import Thread
from types import SimpleNamespace

from ordessa_engineering.adapters.native_records.recorded_dispatch import (
    engineering_effect_write_guard_factory)
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.dispatch_identity import work_dispatch_key
from ordessa_engineering.application.orchestration.steps.declared_generation_dispatch import (
    DeclaredGenerationDispatch)
from ordessa_engineering.domain.changes.dispatch import DispatchBinding
from ordessa_engineering.domain.changes.dispatch_codec import encode_dispatch
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_interfaces.system_access.access_control.authentication import (
    AccessGrant, InstanceAccessAuthority)
from ordessa_interfaces.system_access.contracts.refs import Scope as WireScope
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
from ordessa_infrastructure.encoding import canonical_bytes
from test_declarative_work import start_params
from test_itemized_source_chain import build_itemized_chain
from test_real_source_chain import NOW, SCOPE, close_chain, context, run_full_chain
from ordessa_engineering.adapters.persistence.sqlite.migrations import migrate_schema16

WORK_ID = "generation-effect-guard-work"
ACTION_ID = "incremental.prepare-packages"
STEP_ID = "draft"
DISPATCH = "engineering.executions.dispatch"
TOKEN = "declared-generation-effect-guard-token"
UNIT_REF = {"environmentNamespace": "effect-test", "unitId": "unit-guard",
            "ownerProviderRef": {"provider": "local"}, "sourceRevision": "rev-1"}


class _Records:
    def acp_prompt_input_digest(self, unit_ref, params):
        return "sha256:" + hashlib.sha256(canonical_bytes(params)).hexdigest()


def _digest(raw):
    return Digest("sha256", hashlib.sha256(raw).hexdigest())


def _environment(tmp_path):
    env = build_itemized_chain(tmp_path)
    migrate_schema16(env.library, backup_path=(tmp_path / "schema16.backup.sqlite").resolve())
    chain = run_full_chain(env)
    started = asyncio.run(env.service.execute("engineering.work.start",
        start_params(env, work_id=WORK_ID,
                     associations=(("proposal", chain.successor),)),
        context("generation-effect-start")))
    assert getattr(started, "status", None) == "completed"
    authority = InstanceAccessAuthority(lambda: TOKEN, principal_id="controlled-local-principal",
        legacy_principal=None,
        grants=(AccessGrant(WireScope(SCOPE.realm_id, SCOPE.project_id), (DISPATCH,)),))
    caller = authority.authenticate(f"Bearer {TOKEN}")
    access = EngineeringCommandAccess(authority)
    records = _Records()
    execution = SimpleNamespace(records=records)
    dispatch = DeclaredGenerationDispatch(env.factory, access, blobs=env.blobs,
        execution=execution, review_admission=env.service._review_admission,
        method_guard=env.service._method_guard)
    fixed = engineering_effect_write_guard_factory(None, None, records, env.blobs,
                                                    generation_dispatch=dispatch)
    return env, chain, authority, caller, access, dispatch, fixed, records


def _binding(env, chain, attempt, *, review_ref=None, method_ref=None):
    review_ref = review_ref or chain.review_ref
    method_ref = method_ref or env.method
    params = {"prompt": [], "sessionId": "fixed-session"}
    raw = canonical_bytes(params)
    digest = _digest(raw)
    prompt_ref = env.blobs.put_verified(raw, digest, "application/json")
    identity = work_dispatch_key(WORK_ID, ACTION_ID, STEP_ID)
    op = f"effect-operation-{attempt}"
    evidence = {"review_ref": asdict(review_ref), "change_ref": asdict(chain.successor),
        "method_ref": asdict(method_ref), "inputs_digest": asdict(_digest(b"qualified-inputs"))}
    binding = DispatchBinding(SCOPE, identity, STEP_ID, attempt, 1,
        None, None, None, None, (("generate_package", f"gen-instance-{attempt}"),),
        canonical_bytes(UNIT_REF), op, prompt_ref, digest, f"query-{attempt}",
        ("reserved", "possibly_written", "completed", "failed", "unknown"),
        binding_version=2,
        work={"work_id": WORK_ID, "action_id": ACTION_ID, "step_id": STEP_ID,
              "dispatch_key": identity},
        subject={"subject_kind": "reviewed_change", "subject_ref": evidence})
    with env.factory.begin(SCOPE) as uow:
        encoded = encode_dispatch(binding)
        uow.work_dispatch.reserve(identity, STEP_ID, attempt, SCOPE, encoded,
                                  _digest(encoded), op)
        uow.work_dispatch.transition(identity, STEP_ID, attempt, SCOPE,
            expected_version=0, fence=1, phase="possibly_written")
        uow.commit()
    return binding


def _identity(binding, **changes):
    value = {"unitRef": UNIT_REF, "operationRef": binding.execution_operation_ref,
        "inputDigest": "sha256:" + binding.prompt_input_digest.hex,
        "requestId": "sdk-request-1", "frameDigest": "sha256:" + "f" * 64}
    value.update(changes)
    return value


def _target_call(dispatch, context, binding, identity, handoff, result):
    async def run():
        async with dispatch.acquire_effect_write(context, binding, identity,
                time.monotonic() + 5, handoff=handoff):
            result.append("allowed")
    try:
        asyncio.run(run())
    except BaseException as exc:
        result.append(exc)


def _run_handoff(access, caller, dispatch, binding, identity, *, wrong_thread=False,
                 revoke=None):
    result = []
    token_queue = queue.Queue()

    def target_run():
        item = token_queue.get(timeout=5)
        if item is not None:
            _target_call(dispatch, item[0], item[1], item[2], item[3], result)

    target = Thread(target=target_run, name="declared-generation-sdk-target")
    target.start()
    with access.admit(caller, WireScope(SCOPE.realm_id, SCOPE.project_id), DISPATCH,
            request_id=f"generation-effect-{binding.attempt}", trace_id="guard-test") as context:
        try:
            with access.handoff_effect_write(context,
                    invocation_key=bytes.fromhex(binding.digest.hex),
                    action_instances=binding.action_instances, target_thread=target,
                    expires_at=time.monotonic() + 5) as handoff:
                if revoke is not None:
                    revoke()
                if wrong_thread:
                    worker = Thread(target=_target_call,
                        args=(dispatch, context, binding, identity, handoff, result),
                        name="declared-generation-effect-caller")
                    worker.start()
                    worker.join(5)
                    assert not worker.is_alive()
                    token_queue.put(None)
                else:
                    token_queue.put((context, binding, identity, handoff))
                    target.join(5)
                    if target.is_alive():
                        frame = sys._current_frames().get(target.ident)
                        if frame is not None:
                            traceback.print_stack(frame, file=sys.stderr)
                    assert not target.is_alive()
        except ApplicationError as exc:
            result.append(exc)
    if target.is_alive():
        token_queue.put(None)
        target.join(5)
    assert not target.is_alive()
    return result


def _run_factory_guard(access, caller, fixed, binding):
    """Exercise factory routing through the public Unit EffectWriteGuard."""
    result = []
    params = {"prompt": [], "sessionId": "fixed-session"}
    input_digest = "sha256:" + binding.prompt_input_digest.hex
    frame = canonical_bytes({"jsonrpc": "2.0", "method": "session/prompt",
                             "params": params, "id": "sdk-request-1"})
    token_queue = queue.Queue()

    def target_run():
        guard = token_queue.get(timeout=5)
        if guard is not None:
            async def run():
                async with guard.hold(frame):
                    result.append("allowed")
            try:
                asyncio.run(run())
            except BaseException as exc:
                result.append(exc)

    target = Thread(target=target_run, name="declared-generation-sdk-target")
    target.start()
    with access.admit(caller, WireScope(SCOPE.realm_id, SCOPE.project_id), DISPATCH,
            request_id=f"generation-factory-{binding.attempt}", trace_id="guard-test") as context:
        try:
            with fixed.guard_effect_handoff(context, binding, access=access, timeout=5,
                                            target_thread=target):
                guard = fixed(UNIT_REF, binding.execution_operation_ref, input_digest, params)
                token_queue.put(guard)
                target.join(5)
                if target.is_alive():
                    frame = sys._current_frames().get(target.ident)
                    if frame is not None:
                        traceback.print_stack(frame, file=sys.stderr)
                assert not target.is_alive()
        except ApplicationError as exc:
            result.append(exc)
    if target.is_alive():
        token_queue.put(None)
        target.join(5)
    assert not target.is_alive()
    return result


def test_reviewed_change_effect_cut_checks_identity_and_live_authority(tmp_path):
    env, chain, _authority, caller, access, dispatch, fixed, _records = _environment(tmp_path)
    try:
        binding = _binding(env, chain, 1)
        assert _run_handoff(access, caller, dispatch, binding,
                            _identity(binding)) == ["allowed"]
        factory_binding = _binding(env, chain, 2)
        assert _run_factory_guard(access, caller, fixed, factory_binding) == ["allowed"]
        for attempt, changed in ((3, {"frameDigest": "sha256:bad"}),
                                 (4, {"inputDigest": "sha256:" + "0" * 64}),
                                 (5, {"requestId": ""})):
            binding = _binding(env, chain, attempt)
            result = _run_handoff(access, caller, dispatch, binding,
                                  _identity(binding, **changed))
            assert len(result) == 1 and isinstance(result[0], ApplicationError)
            assert result[0].code == "WORK_ACTION_GENERATION_EFFECT_BINDING_MISMATCH"

        changed_method = replace(env.method, snapshot_digest=_digest(b"other-method"))
        method_binding = _binding(env, chain, 6, method_ref=changed_method)
        result = _run_handoff(access, caller, dispatch, method_binding,
                              _identity(method_binding))
        assert len(result) == 1 and isinstance(result[0], ApplicationError)
        assert result[0].code == "WORK_ACTION_ADMISSION_EXACT_INPUTS_FAILED"

        from ordessa_engineering.domain.reviews.refs import ReviewRef
        wrong_review = ReviewRef(SCOPE.realm_id, SCOPE.project_id, "other-review",
                                 _digest(b"other-review"))
        review_binding = _binding(env, chain, 7, review_ref=wrong_review)
        result = _run_handoff(access, caller, dispatch, review_binding,
                              _identity(review_binding))
        assert len(result) == 1 and isinstance(result[0], ApplicationError)
        assert result[0].code == "WORK_ACTION_ADMISSION_EXACT_INPUTS_FAILED"

        cross_thread = _binding(env, chain, 8)
        result = _run_handoff(access, caller, dispatch, cross_thread,
                              _identity(cross_thread), wrong_thread=True)
        assert len(result) == 1 and isinstance(result[0], ApplicationError)
        assert result[0].code in {"EFFECT_HANDOFF_MISMATCH", "EFFECT_HANDOFF_UNAVAILABLE"}

        revoked = _binding(env, chain, 9)
        result = _run_handoff(access, caller, dispatch, revoked,
                              _identity(revoked), revoke=_authority.revoke)
        assert result and all(isinstance(item, ApplicationError) for item in result)
    finally:
        close_chain(env)
