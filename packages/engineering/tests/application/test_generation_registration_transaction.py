"""Registration re-verifies the admission in the same transaction (no TOCTOU).

The declared `prepare-spec-kit-package` step validates the produced package and
then archives its exact document bytes before it registers the package. This
file drives a change into that validation-to-registration window and proves the
registering transaction re-reads the Work, the proposal/change, the review, the
method pins and the original dispatch: a changed admitted fact refuses the
registration, the original native receipt is preserved, and no `eng_packages`
row is created. The unchanged flow still registers exactly one package.

Three windows are exercised, in order of narrowing:

* between the package validation and the guards (the document archive loop);
* inside the held method/plan/trust guards, after the native receipt has been
  re-read and before the registering transaction opens;
* inside the registering transaction itself, before its COMMIT.

Every refusal is checked against the whole `eng_packages` identity set (never a
count for one `package_id`), against the original dispatch row read by its exact
dispatch key, step, attempt and scope, and against the receipt that attempt
produced. The method-control change made inside the registering transaction is
rolled back by the held method fence rather than refused by this step's code, so
the assertion says what actually happened instead of what would be convenient.
"""
import hashlib
from dataclasses import asdict, replace

import pytest
from work_step_access_fixture import enable_controlled_work_steps

from test_itemized_source_chain import build_itemized_chain
from test_real_source_chain import NOW, SCOPE, close_chain, context, run_full_chain
from test_work_invoke_generation import (
    WORK_ID, _Transport, _command_payload, _command_status, _invoke_generation,
    _prepared_output)
from ordessa_engineering.adapters.persistence.sqlite.migrations import migrate_schema16
from ordessa_engineering.application.contracts.dispatch_identity import work_dispatch_key
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.changes.dispatch_codec import (
    decode_dispatch, encode_dispatch)
from ordessa_engineering.domain.common.mechanisms.codec import decode_blob_ref
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.packages.codec import decode_package_ref
from ordessa_engineering.domain.reviews.models import ReviewControlExpectation
from ordessa_infrastructure.encoding import canonical_bytes, decode_json


@pytest.fixture(autouse=True)
def controlled_work_step_admission(monkeypatch):
    enable_controlled_work_steps(monkeypatch)


GENERATED_PACKAGE_ID = "generated-package-1"
GENERATION_ACTION_ID = "incremental.prepare-packages"
GENERATION_STEP_ID = "draft"
GENERATION_ATTEMPT = 1
OTHER_WORK_ID = "declarative-work-2"
_ARCHIVE_MEDIA_TYPE = "text/markdown"


def _generation_case(tmp_path):
    """The real chain, migrated to 17, with the declared generation handles."""
    env = build_itemized_chain(tmp_path)
    migrate_schema16(env.library,
                     backup_path=(tmp_path / "schema16.backup.sqlite").resolve())
    chain = run_full_chain(env)
    captured = _prepared_output(env, chain.review_ref, chain.successor)
    blob = env.blobs.put_verified(
        captured, Digest("sha256", hashlib.sha256(captured).hexdigest()),
        "application/json")
    transport = _Transport(blob, blobs=env.blobs)
    env.service.attach_declared_generation_handles(
        blobs=env.blobs, execution=transport,
        unit_ref_resolver=lambda context, binding, profile_ref: {
            "environmentNamespace": "env", "unitId": "unit-1",
            "ownerProviderRef": {"provider": "local"}, "sourceRevision": "rev-1"})
    return env, chain, transport


def _dispatch_key(work_id=WORK_ID):
    """The one internal key this exact declared Work step is dispatched under."""
    return work_dispatch_key(work_id, GENERATION_ACTION_ID, GENERATION_STEP_ID)


def _package_identities(env):
    """Every `eng_packages` identity in the library, not one package_id count."""
    return set(env.library._connection.execute(
        "SELECT realm_id, project_id, package_id, digest FROM eng_packages").fetchall())


def _dispatch_row(env, work_id=WORK_ID):
    """This exact Work step's dispatch row, read through its own owner.

    The dispatch key, the step and the attempt are all given, and the scope is
    the reading transaction's own, so a row belonging to another Work, another
    step or another attempt is never returned as this run's row.
    """
    with env.factory.begin(SCOPE, "read") as uow:
        return uow.work_dispatch.get(_dispatch_key(work_id), GENERATION_STEP_ID,
                                     GENERATION_ATTEMPT, SCOPE)


def _dispatch_row_count(env, work_id=WORK_ID):
    """How many rows exist for the exact dispatch key, step and attempt."""
    return env.library._connection.execute(
        "SELECT COUNT(*) FROM work_step_log WHERE dispatch_key=? AND step_id=? AND attempt=?",
        (_dispatch_key(work_id), GENERATION_STEP_ID, GENERATION_ATTEMPT)).fetchone()[0]


def _dispatch_rows_for_step(env):
    """How many rows a read *without* the exact dispatch key would see."""
    return env.library._connection.execute(
        "SELECT COUNT(*) FROM work_step_log WHERE step_id=? AND attempt=?",
        (GENERATION_STEP_ID, GENERATION_ATTEMPT)).fetchone()[0]


def _observed_dispatch(env):
    """The dispatch as it stands: its phase, receipt ref and receipt summary."""
    row = _dispatch_row(env)
    blob_json = row["result_blob_json"]
    assert blob_json is not None, "the completed dispatch has no result blob"
    ref = decode_blob_ref(decode_json(blob_json))
    receipt = decode_json(env.blobs.read_verified(ref))
    return row["dispatch_phase"], asdict(ref), receipt["summary"]


def _inject_other_work_dispatch_row(env, row):
    """Add one reserved dispatch row that belongs to *another* declared Work.

    Its binding is a real schema-2 declared-Work binding for that other Work -
    the same frozen fields under its own key - inserted as its own row. The
    relation then holds a second row for the same step and attempt, so a read
    that is not keyed on the exact dispatch key cannot be mistaken for this
    run's row, and the exact key is what makes the read unique.
    """
    key = _dispatch_key(OTHER_WORK_ID)
    binding = decode_dispatch(row["binding_bytes"])
    other = replace(binding, run_id=key,
                    work={**binding.work, "work_id": OTHER_WORK_ID, "dispatch_key": key})
    encoded = encode_dispatch(other)
    digest = hashlib.sha256(encoded).hexdigest()
    operation_ref = "other-work-operation-1"
    marker = canonical_bytes({"dispatch": "reserved", "binding_digest": digest,
                              "operation_ref": operation_ref}).decode("utf-8")
    scope_json = canonical_bytes(asdict(SCOPE)).decode("utf-8")
    env.library._connection.execute(
        "INSERT INTO work_step_log (dispatch_key,ordinal,step_id,operation,attempt,status,"
        "receipt_ref_json,dispatch_scope_json,binding_digest,binding_bytes,"
        "execution_operation_ref,dispatch_phase,dispatch_version,dispatch_fence,"
        "result_blob_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (key, 0, GENERATION_STEP_ID, "engineering.execution.dispatch", GENERATION_ATTEMPT,
         "reserved", marker, scope_json, digest, encoded, operation_ref, "reserved", 0, 1,
         None))
    env.library._connection.commit()
    return key


def _assert_exact_dispatch_intact(env, observed):
    """The original attempt is still the completed, exactly-keyed one.

    `observed` is the `(phase, receipt_ref, receipt_summary)` captured before the
    registration was refused. The interference row added here belongs to another
    declared Work, so the read below is proven to be keyed on the exact dispatch
    key rather than on the step, the attempt or the table's own ordering.
    """
    phase, ref, summary = observed
    row = _dispatch_row(env)
    assert row["dispatch_phase"] == phase == "completed", row["dispatch_phase"]
    blob_json = row["result_blob_json"]
    assert blob_json is not None
    frozen = decode_dispatch(row["binding_bytes"])
    receipt = decode_json(env.blobs.read_verified(decode_blob_ref(decode_json(blob_json))))
    # The receipt and the row carry the frozen binding's own operation and fence.
    assert receipt["operationRef"] == frozen.execution_operation_ref
    assert row["execution_operation_ref"] == frozen.execution_operation_ref
    assert row["dispatch_fence"] == frozen.fence
    # The receipt reference and the receipt summary are the ones observed before.
    assert (asdict(decode_blob_ref(decode_json(blob_json))), receipt["summary"]) == (ref, summary)
    assert _dispatch_row_count(env) == 1
    decoy_key = _inject_other_work_dispatch_row(env, row)
    assert decoy_key != _dispatch_key()
    # The interference row is really in the relation, and it really makes a
    # read without the exact key ambiguous ...
    assert _dispatch_rows_for_step(env) >= 2
    assert _dispatch_row_count(env, OTHER_WORK_ID) == 1
    # ... while the exact key still names exactly this one completed attempt.
    assert _dispatch_row_count(env) == 1
    decoy = _dispatch_row(env, OTHER_WORK_ID)
    assert (decoy["dispatch_phase"], decoy["result_blob_json"]) == ("reserved", None)
    assert _dispatch_row(env)["result_blob_json"] == blob_json


def _install_between_validation_hook(monkeypatch, env, mutate):
    """Run `mutate` exactly once while the step archives its document bytes.

    The archive loop is the only real work between the package validation and
    the registering transaction, so mutating there drives the exact window this
    file exercises. The captured output and native receipt blobs are written
    with an `application/json` media type and are not affected. The completed
    dispatch as it stands is recorded here too: this is the state the refused
    registration must leave untouched.
    """
    original_put = env.blobs.put_verified
    state = {"mutated": False}

    def hook(raw_bytes, digest, media_type):
        if not state["mutated"] and media_type == _ARCHIVE_MEDIA_TYPE:
            state["mutated"] = True
            state["observed"] = _observed_dispatch(env)
            mutate()
        return original_put(raw_bytes, digest, media_type)

    monkeypatch.setattr(env.blobs, "put_verified", hook)
    return state


def _install_after_receipt_hook(monkeypatch, env, mutate=None):
    """Observe - and optionally mutate - in the held-guard window.

    `_verify_native_receipt` is the last owner re-read before the registering
    transaction opens: the method/plan/trust guards have been entered and not
    yet exited, and no business transaction is open. The hook records that
    window and the completed dispatch itself, so the test proves where it ran
    instead of assuming it; `mutate` then runs in exactly that window.
    """
    from ordessa_engineering.application.orchestration.steps.declared_generation_port import (
        DeclaredGenerationPort)
    original = DeclaredGenerationPort._verify_native_receipt
    state = {"ran": False}

    def hook(self, outcome, dispatch_binding, generated_text):
        original(self, outcome, dispatch_binding, generated_text)
        if not state["ran"]:
            state["ran"] = True
            state["method_guards"] = len(getattr(env.library._method_guard_fences,
                                                 "values", ()))
            state["declaration_guards"] = len(getattr(
                env.library._method_declaration_fences, "values", ()))
            state["in_transaction"] = env.library._connection.in_transaction
            state["observed"] = _observed_dispatch(env)
            if mutate is not None:
                mutate()

    monkeypatch.setattr(DeclaredGenerationPort, "_verify_native_receipt", hook)
    return state


def _install_registration_hook(monkeypatch, env, mutate):
    """Run `mutate` inside the registering transaction, before its COMMIT.

    The registration callback is the composition seam that runs inside the very
    transaction that creates the package row, so a change made here is a change
    made inside that transaction - the one the held fences must answer for.
    """
    steps = env.service._prepare_packages_steps
    original = steps.verify_generated_registration
    state = {"ran": False}

    def hook(uow, step_context, binding, record, held_review, held_trust):
        result = original(uow, step_context, binding, record, held_review, held_trust)
        if not state["ran"]:
            state["ran"] = True
            state["in_transaction"] = env.library._connection.in_transaction
            mutate(uow)
        return result

    monkeypatch.setattr(steps, "verify_generated_registration", hook)
    return state


def _void_admitted_review(env, chain):
    """A concurrent writer voids the review control this run was admitted on."""
    with env.factory.begin(SCOPE) as uow:
        uow.reviews.control_group(
            (ReviewControlExpectation(chain.review_ref, 0),),
            state="voided", reason="concurrent void of the admitted review",
            evidence=(Digest("sha256", "a" * 64),))
        uow.commit()


def _disable_pinned_method(env):
    """A concurrent writer disables the pinned method declaration's control."""
    env.management.control(env.method, context("concurrent-method-disable"),
                           expected_version=1, enabled=False,
                           reason="controlled concurrent method stop")


def _advance_work_revision(env):
    """A concurrent writer advances the Work to a new material revision."""
    from ordessa_engineering.application.contracts.work_context import (
        WORK_CONTEXT_KIND, WORK_STABLE_ID_PREFIX, decode_work_binding,
        work_binding_projection)
    with env.factory.begin(SCOPE) as uow:
        head = uow.workflow.head_ref(WORK_CONTEXT_KIND,
                                     WORK_STABLE_ID_PREFIX + WORK_ID)
        binding = decode_work_binding(uow.workflow.read(head))
        bumped = replace(binding, revision=binding.revision + 1)
        uow.workflow.write_work_context(stable_id=bumped.stable_id,
                                        revision=bumped.revision,
                                        body=work_binding_projection(bumped))
        uow.commit()


@pytest.mark.parametrize("scenario,expected_code", (
    ("review", "WORK_ACTION_ADMISSION_EXACT_INPUTS_FAILED"),
    ("method", "METHOD_DISABLED"),
    ("work", "WORK_ACTION_GENERATION_WORK_CHANGED"),
))
def test_change_between_validation_and_registration_refuses_registration(
        tmp_path, monkeypatch, scenario, expected_code):
    """Each mutated admitted fact refuses; the receipt stays, no package row."""
    env, chain, transport = _generation_case(tmp_path)
    try:
        def mutate():
            if scenario == "review":
                _void_admitted_review(env, chain)
            elif scenario == "method":
                _disable_pinned_method(env)
            else:
                _advance_work_revision(env)

        before = _package_identities(env)
        state = _install_between_validation_hook(monkeypatch, env, mutate)
        with pytest.raises(ApplicationError) as raised:
            _invoke_generation(env, chain, transport)
        assert state["mutated"] is True, "the window mutation never ran"
        assert raised.value.code == expected_code, raised.value.code
        # The native dispatch did happen, and its original receipt is preserved.
        assert transport.sends == 1
        # Not one `package_id` count: the whole identity set is untouched.
        assert _package_identities(env) == before
        _assert_exact_dispatch_intact(env, state["observed"])
    finally:
        close_chain(env)


@pytest.mark.parametrize("scenario,expected_code", (
    ("review", "WORK_ACTION_ADMISSION_EXACT_INPUTS_FAILED"),
    ("work", "WORK_ACTION_GENERATION_WORK_CHANGED"),
))
def test_change_inside_held_guards_refuses_registration(
        tmp_path, monkeypatch, scenario, expected_code):
    """A change made while the guards are held still refuses the registration."""
    env, chain, transport = _generation_case(tmp_path)
    try:
        def mutate():
            if scenario == "review":
                _void_admitted_review(env, chain)
            else:
                _advance_work_revision(env)

        before = _package_identities(env)
        state = _install_after_receipt_hook(monkeypatch, env, mutate)
        with pytest.raises(ApplicationError) as raised:
            _invoke_generation(env, chain, transport)
        assert state["ran"] is True, "the held-guard window never ran"
        # The hook proves the window it ran in: the method and declaration
        # guards are held, and no business transaction is open yet - so the
        # refusal below is not an artefact of either.
        assert state["method_guards"] >= 1 and state["declaration_guards"] >= 1
        assert state["in_transaction"] is False
        assert raised.value.code == expected_code, raised.value.code
        assert transport.sends == 1
        assert _package_identities(env) == before
        _assert_exact_dispatch_intact(env, state["observed"])
    finally:
        close_chain(env)


def test_method_control_change_inside_registration_transaction_is_rolled_back(
        tmp_path, monkeypatch):
    """The held method fence rolls back a control change made in the same TX.

    The change goes through the registering transaction's own method
    repository, after the registering callback re-verified the admission and
    before that transaction commits. The schema-2 method fence is rechecked at
    COMMIT, so the control change and the package row are rolled back together:
    the method is still enabled at its original version, and nothing was
    registered. That is the fence doing its job, not a refusal invented here.
    """
    env, chain, transport = _generation_case(tmp_path)
    try:
        before = _package_identities(env)

        def mutate(uow):
            uow.methods.control_declaration(
                env.method, 1, False, Digest("sha256", "e" * 64),
                "concurrent method stop inside the registering transaction", NOW)

        observed = _install_after_receipt_hook(monkeypatch, env)
        mutated = _install_registration_hook(monkeypatch, env, mutate)
        with pytest.raises(ApplicationError) as raised:
            _invoke_generation(env, chain, transport)
        assert mutated["ran"] is True, "the in-transaction mutation never ran"
        assert mutated["in_transaction"] is True, \
            "the method control was not changed inside the registering transaction"
        assert raised.value.code == "METHOD_CONTROL_CHANGED", raised.value.code
        # The fence rolled the change back: the method is exactly as it was.
        with env.factory.begin(SCOPE, "read") as uow:
            control = uow.methods.control(env.method)
        assert (control.enabled, control.version) == (True, 1)
        # And no package row survived the rolled-back transaction.
        assert _package_identities(env) == before
        assert observed["ran"] is True
        assert observed["in_transaction"] is False
        assert transport.sends == 1
        _assert_exact_dispatch_intact(env, observed["observed"])
    finally:
        close_chain(env)


def test_unchanged_admission_still_registers_the_package(tmp_path, monkeypatch):
    """The guard closes the window without blocking an unchanged registration."""
    env, chain, transport = _generation_case(tmp_path)
    try:
        before = _package_identities(env)
        observed = _install_after_receipt_hook(monkeypatch, env)
        result = _invoke_generation(env, chain, transport)
        payload = _command_payload(result)
        assert _command_status(result) == "completed", payload
        step = next(item for item in payload["steps"]
                    if item.get("business", {}).get("package_ref"))
        assert decode_package_ref(step["business"]["package_ref"]).package_id \
            == GENERATED_PACKAGE_ID
        assert transport.sends == 1
        # Exactly one new identity, and it is this run's generated package.
        after = _package_identities(env)
        assert before <= after
        assert len(after - before) == 1
        added = next(iter(after - before))
        assert (added[0], added[1], added[2]) == (
            SCOPE.realm_id, SCOPE.project_id, GENERATED_PACKAGE_ID)
        # The native receipt remains the one this exact dispatch produced.
        assert observed["ran"] is True
        _assert_exact_dispatch_intact(env, observed["observed"])
    finally:
        close_chain(env)
