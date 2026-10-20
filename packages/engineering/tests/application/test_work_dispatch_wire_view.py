"""The query view of a generation attempt: JSON-safe in public, raw inside.

Two sides of one boundary are asserted here, both about the *read* of a declared
generation step rather than about a fresh write:

* the **public** view `engineering.work.get` returns is JSON-safe. It carries a
  `binding_digest` but never the stored `binding_bytes`, so it crosses the formal
  encoder the Engineering wire binding uses for this exact query; and
* the **internal** observation (`WorkQueries._generation_dispatch`) still carries
  the original stored bytes, which is precisely why the public projection exists.

The second fact is a *refusal*, not a projection: a pre-fix folded key is cut to
the key bound, so two distinct long Work ids can share one stored key. A stored
row found under such a colliding key whose own binding names *another* Work must
be refused by name, never reported as the requested Work's result.

The library, relation, repository, codec, identity contract and query are the
real ones. The caller's access is a labelled local read double; no platform
identity, credential or network is involved.
"""
import hashlib
from dataclasses import asdict

import pytest

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_infrastructure.encoding.canonical_json import CanonicalJSONError
from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_engineering.adapters.persistence.sqlite.dispatch_schema import (
    WORK_DISPATCH_SCHEMA_VERSION)
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import (
    EngineeringLibrary)
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.dispatch_identity import (
    is_folded_work_key, work_dispatch_key, work_dispatch_key_candidates)
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.work_context import (
    WORK_STABLE_ID_PREFIX, WorkBinding, work_binding_projection)
from ordessa_engineering.application.usecases.queries.works import (
    GENERATION_DISPATCH_PUBLIC_FIELDS, WorkQueries, generation_dispatch_view)
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.changes.dispatch import DispatchBinding
from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch, encode_dispatch
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.refs import ReviewRef

ACTION = 'incremental.prepare-packages'
STEP = 'draft'
_DISPATCH_OPERATION = 'engineering.execution.dispatch'


class _ReadAccess:
    """The caller's own UoW-shaped read access, as a labelled local double.

    A Work read is admitted by the real access authority in production; here the
    double only records that it was asked, so the query path under test is the
    real one and nothing about a credential is claimed.
    """

    def __init__(self, scope):
        self.scope = scope

    def require(self, context, operation):
        assert operation == 'engineering.work.get'


def _context(scope, request_id):
    return CommandContext(scope, 'wire-view-principal',
                          ActorRef('wire-view-actor', 'service', 'wire-view-issuer'),
                          request_id, '2026-10-16T00:00:00.000000Z', request_id)


def _library(tmp_path):
    return EngineeringLibrary.create((tmp_path / 'work-dispatch-wire.sqlite').resolve(),
                                     library_id='work-dispatch-wire',
                                     schema_version=WORK_DISPATCH_SCHEMA_VERSION)


def _write_work(factory, scope, work_id):
    """Persist one declarative Work row through its sole authorized writer."""
    binding = WorkBinding(work_id, scope,
                          MethodRef('incremental-engineering', '2.7.2', 1, Digest('sha256', 'a' * 64)),
                          1)
    with factory.begin(scope) as uow:
        uow.workflow.write_work_context(stable_id=WORK_STABLE_ID_PREFIX + work_id,
                                        revision=1, body=work_binding_projection(binding))
        uow.commit()


def _unit_bytes():
    return canonical_bytes({'environmentNamespace': 'env', 'unitId': 'unit-1',
                            'ownerProviderRef': {'provider': 'local'}, 'sourceRevision': 'rev-1'})


def _prompt_ref():
    return BlobRef(Digest('sha256', 'c' * 64), 10, 'application/json', 'prompt-object')


def _generation_subject(scope):
    """The reviewed-change subject a generation binding acts on."""
    return {'review_ref': asdict(ReviewRef(scope.realm_id, scope.project_id, 'review-1',
                                           Digest('sha256', 'd' * 64))),
            'change_ref': asdict(ProposalRef(scope.realm_id, scope.project_id, 'change-1',
                                             'proposal-1', Digest('sha256', 'f' * 64))),
            'method_ref': asdict(MethodRef('ordessa.incremental-engineering', '2.7.2', 1,
                                           Digest('sha256', 'b' * 64))),
            'inputs_digest': asdict(Digest('sha256', 'e' * 64))}


def _generation_binding(scope, *, work_id, key):
    return DispatchBinding(
        scope, key, STEP, 1, 1, None, None, None, None,
        (('generate_package', 'instance-1'),), _unit_bytes(), 'operation-1',
        _prompt_ref(), Digest('sha256', 'd' * 64), 'q' * 64, ('submission',),
        binding_version=2,
        work={'work_id': work_id, 'action_id': ACTION, 'step_id': STEP, 'dispatch_key': key},
        subject={'subject_kind': 'reviewed_change', 'subject_ref': _generation_subject(scope)})


def _seed_reserved(library, scope, dispatch_key, raw, operation_ref):
    """Store one dispatch row exactly as the writer leaves it: raw bytes, reserved.

    Nothing here re-encodes or re-derives the binding; the row carries the
    original bytes and their digest under the original key, inserted at the SQL
    layer instead of through a current `reserve`.
    """
    digest_hex = hashlib.sha256(raw).hexdigest()
    scope_json = canonical_bytes(asdict(scope)).decode('utf-8')
    marker = canonical_bytes({'dispatch': 'reserved', 'binding_digest': digest_hex,
                              'operation_ref': operation_ref}).decode('utf-8')
    with library.transaction() as connection:
        connection.execute(
            'INSERT INTO work_step_log (dispatch_key,ordinal,step_id,operation,attempt,status,'
            'receipt_ref_json,dispatch_scope_json,binding_digest,binding_bytes,'
            'execution_operation_ref,dispatch_phase,dispatch_version,dispatch_fence,'
            'result_blob_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (dispatch_key, 0, STEP, _DISPATCH_OPERATION, 1, 'reserved', marker, scope_json,
             digest_hex, raw, operation_ref, 'reserved', 0, 1, None))


# --------------------------------------------------------------------------
# The public view crosses the wire; the internal one keeps the raw bytes.
# --------------------------------------------------------------------------

def test_the_public_generation_view_is_wire_safe_while_the_internal_keeps_bytes(tmp_path):
    scope = Scope('wire-view-realm', 'wire-view-project')
    work_id = 'wire-view-work'
    library = _library(tmp_path)
    try:
        factory = SQLiteUoWFactory(library)
        _write_work(factory, scope, work_id)
        key = work_dispatch_key(work_id, ACTION, STEP)
        raw = encode_dispatch(_generation_binding(scope, work_id=work_id, key=key))
        _seed_reserved(library, scope, key, raw, 'operation-wire-view')

        queries = WorkQueries(factory, _ReadAccess(scope))
        context = _context(scope, 'read-wire-view')

        # The internal observation is the stored row with its original bytes.
        internal = queries._generation_dispatch(context, work_id)
        assert internal is not None
        assert internal['binding_bytes'] == raw
        assert internal['dispatch_key'] == key

        # The public query view is exactly its JSON-safe projection.
        view = queries.read({'work_id': work_id}, context)
        public = view['generation_dispatch']
        assert public == generation_dispatch_view(internal)
        assert set(public) == set(GENERATION_DISPATCH_PUBLIC_FIELDS)
        assert 'binding_bytes' not in public
        assert not any(isinstance(value, (bytes, bytearray)) for value in public.values())
        assert public['binding_digest'] == {
            'algorithm': 'sha256', 'hex': hashlib.sha256(raw).hexdigest()}
        assert public['retry_allowed'] is False

        # The public view crosses the formal encoder the wire binding uses for
        # this exact query: the strict mapping encoder and the canonical JSON
        # round-trip both accept it, and the whole Work view is JSON-safe too.
        assert isinstance(safe_json(public), str)
        assert decode_json(canonical_bytes(public)) == public
        # The whole Work view crosses the same encoder; its declared-action
        # sequences are the immutable tuples the wire projection materializes.
        restored = decode_json(canonical_bytes(view))
        assert isinstance(restored, dict)
        assert restored['generation_dispatch'] == public

        # The raw bytes are not a wire value: the internal observation cannot be
        # encoded by the same formal encoder, which is why the projection exists.
        with pytest.raises(CanonicalJSONError):
            safe_json(internal)
        with pytest.raises(CanonicalJSONError):
            canonical_bytes(internal)
    finally:
        library.close()


# --------------------------------------------------------------------------
# A colliding truncated key never reports another Work's result.
# --------------------------------------------------------------------------

def test_a_colliding_truncated_key_never_reports_another_work(tmp_path):
    """Two distinct Work ids share one cut key; the row names only one of them.

    A pre-fix folded key kept the fields and cut the result to the key bound, so
    two long ids sharing that window produced one identical key. The stored row
    belongs to the first Work; the second Work's candidate list resolves to the
    same row, so the reader must refuse it by name instead of reporting the first
    Work's result as the second's.

    Both ids are legal: `declarative-work:` plus either stays inside the
    192-character material-identifier bound, so both Works are really written.
    """
    scope = Scope('wire-collision-realm', 'wire-collision-project')
    # Each `:` escapes to `%3A`, so the first id's escaped form is exactly the
    # first 508 characters of the second's; both spelled keys exceed the
    # 512-character key bound, so the pre-fix algorithm folded both and cut both
    # folded results inside that shared window.
    first, second = ':' * 170, ':' * 170 + 'a'
    assert first != second
    assert len(WORK_STABLE_ID_PREFIX + first) <= 192
    assert len(WORK_STABLE_ID_PREFIX + second) <= 192
    library = _library(tmp_path)
    try:
        factory = SQLiteUoWFactory(library)
        _write_work(factory, scope, first)
        _write_work(factory, scope, second)

        # The current keys are distinct; the historical folded forms collide.
        assert work_dispatch_key(first, ACTION, STEP) != work_dispatch_key(second, ACTION, STEP)
        first_candidates = work_dispatch_key_candidates(first, ACTION, STEP)
        second_candidates = work_dispatch_key_candidates(second, ACTION, STEP)
        assert len(first_candidates) == 2 and len(second_candidates) == 2
        historical = first_candidates[1]
        # One identical cut key, and it is the shape the pre-fix writer left.
        assert historical == second_candidates[1]
        assert historical.startswith('w1h') and len(historical) == 512
        assert is_folded_work_key(historical)
        assert historical != work_dispatch_key(first, ACTION, STEP)
        assert historical != work_dispatch_key(second, ACTION, STEP)

        raw = encode_dispatch(_generation_binding(scope, work_id=first, key=historical))
        _seed_reserved(library, scope, historical, raw, 'operation-collision')
        # The collision is in the *key* only: the stored bytes name the first Work.
        assert decode_dispatch(raw).work['work_id'] == first

        queries = WorkQueries(factory, _ReadAccess(scope))
        context = _context(scope, 'read-collision')

        # Its own Work finds the row under its own original key.
        own = queries._generation_dispatch(context, first)
        assert own is not None
        assert own['dispatch_key'] == historical
        assert own['binding_bytes'] == raw

        # The colliding Work is refused by name, never handed this row.
        with pytest.raises(ApplicationError) as exc:
            queries._generation_dispatch(context, second)
        assert exc.value.code == 'WORK_DISPATCH_RECONCILIATION_REQUIRED'
        # The refusal is the collision itself, not a missing row: the stored row
        # is still there, still the first Work's, and unchanged by the refusal.
        still = queries._generation_dispatch(context, first)
        assert still is not None and still['dispatch_key'] == historical
        assert still['binding_bytes'] == raw

        # The public read path refuses the same way instead of returning a view.
        with pytest.raises(ApplicationError) as public:
            queries.read({'work_id': second}, context)
        assert public.value.code == 'WORK_DISPATCH_RECONCILIATION_REQUIRED'
    finally:
        library.close()
