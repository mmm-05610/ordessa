"""Versioned internal dispatch identity for declared Work steps.

The active write path takes a **Work**, never a run. The internal dispatch key
is namespaced and versioned so it can never collide with a historical run id
nor with a same-named step belonging to another action of the same Work. The
public view and the stored binding keep the original individual fields
(`work_id`, `action_id`, `step_id`, `attempt`) and validate that they agree with
the key instead of reconstructing them from it.

Ids that are legal but too long to spell out are folded into one fixed-size
digest of the whole field set — never truncated, because a cut key would let two
distinct identities share one.

Two identity entries are kept apart on purpose:

* the **current** canonical identity (`work_dispatch_key`, `identity_is_current`)
  is what an active write mints and what a current lookup reads back; and
* the **explicit historical** verification (`historical_identity_agrees`,
  `work_dispatch_key_candidates`) recomputes the pre-fix folded form from the
  original fields, so a row written before the key fix is recognised for
  read/reconciliation instead of reading as absent.

The current entry never accepts a historical key (a new write must not adopt an
old one); the historical entry never mints a new write. Old rows keep their
original schema and are read-only: nothing here rewrites existing canonical bytes
or re-verifies an old digest against a new schema.
"""

import hashlib
from dataclasses import asdict

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_infrastructure.encoding import canonical_bytes
from .commands import CommandContext, CommandKey
from .work_context import work_binding_projection
from ...domain.common.models.identity import Scope
from ...domain.common.models.values import Digest, validate_id

WORK_DISPATCH_KEY_VERSION = "w1"
"""Version prefix of the namespaced internal dispatch key."""

SUBJECT_KINDS = ("reviewed_change", "frozen_package")
"""What a declared step acts on.

`reviewed_change`  - the already reviewed change (generation: no package exists
                     yet, so the subject is never a `package_ref`).
`frozen_package`   - a frozen, admitted package (implementation).
"""

UNIT_BOOTSTRAP_OPERATION = "engineering.execution.unit-bootstrap"


def unit_bootstrap_operation_id(scope, work_id):
    """One journal operation for the Work's original generation Unit creation.

    Unlike a caller request key, this identity remains the same across callers
    and retries. The original journal's realm/operation uniqueness protects the
    pre-dispatch effect without inventing a Unit ref or dispatch binding.
    """
    if type(scope) is not Scope:
        raise ApplicationError("SCOPE_MISMATCH")
    validate_id(work_id)
    raw = canonical_bytes({"scope": asdict(scope), "work_id": work_id,
        "action_id": "incremental.prepare-packages", "step_id": "draft", "attempt": 1})
    return "work-unit-bootstrap-" + hashlib.sha256(raw).hexdigest()


def unit_bootstrap_request_key(context):
    """Keep the real caller while separating the internal bootstrap command."""
    if type(context) is not CommandContext:
        raise ApplicationError("INVALID_CONTEXT")
    request_id = "unit-bootstrap-" + hashlib.sha256(context.request_id.encode()).hexdigest()
    return CommandKey(context.scope.realm_id, context.principal_id, request_id)


def unit_bootstrap_digest(work_binding, profile_ref, owner_identity):
    """Pin the existing Work and opaque host selection, never grant permission."""
    if (type(profile_ref) is not dict or not profile_ref
            or type(owner_identity) is not str or not owner_identity.startswith("sha256:")
            or len(owner_identity) != 71
            or any(char not in "0123456789abcdef" for char in owner_identity[7:])):
        raise ApplicationError("WORK_ACTION_GENERATION_UNIT_BINDING_INVALID")
    raw = canonical_bytes({"work": work_binding_projection(work_binding),
        "profile_ref": profile_ref, "owner_identity": owner_identity})
    return Digest("sha256", hashlib.sha256(raw).hexdigest())

_MAX_KEY = 512
_SEPARATOR = ":"
_FOLDED_PREFIX = "w1h"
# The folded form is exactly this prefix plus one sha256 hex digest: a fixed
# size, so a folded key never depends on how long the original fields are.
_FOLDED_HEAD = _FOLDED_PREFIX + _SEPARATOR + "sha256:"
_ESCAPES = {"%": "%25", ":": "%3A"}


def _escape(value, field):
    """Reversible escaping: any legal public id stays representable."""
    if type(value) is not str or not value:
        raise ApplicationError("WORK_DISPATCH_IDENTITY_INVALID")
    return "".join(_ESCAPES.get(char, char) for char in value)


def _unescape(value):
    out, index = [], 0
    while index < len(value):
        char = value[index]
        if char == "%":
            code = value[index + 1:index + 3]
            if code == "25":
                out.append("%")
            elif code == "3A":
                out.append(":")
            else:
                raise ApplicationError("WORK_DISPATCH_IDENTITY_INVALID")
            index += 3
        else:
            out.append(char)
            index += 1
    return "".join(out)


def _canonical_ref(value, field):
    return value


def _fields(work_id, action_id, step_id):
    """The escaped original fields, in the one order the key is built from."""
    return tuple(_escape(value, field)
                 for value, field in ((work_id, "work_id"), (action_id, "action_id"),
                                      (step_id, "step_id")))


def _folded_key(parts):
    """The fixed-size key for ids too long to spell out.

    The *whole* field set is folded into one digest. Nothing is truncated, so
    two distinct identities can never share a folded key however long they are.
    """
    return _FOLDED_HEAD + hashlib.sha256(canonical_bytes(list(parts))).hexdigest()


def _historical_folded_key(parts):
    """The pre-fix folded form: the fields, then their digest, cut to the bound.

    Rows already stored under this form keep their bytes and their digest. This
    recomputes that exact key so such a row can still be verified against its own
    original fields — it never rewrites a stored row.
    """
    folded = _SEPARATOR.join((_FOLDED_PREFIX,) + tuple(parts) + (digest_of(list(parts)),))
    return folded if len(folded) <= _MAX_KEY else folded[:_MAX_KEY]


def _historical_folding_applies(parts):
    """Did the pre-fix algorithm actually fold this field set?

    The pre-fix key spelled the fields out and folded *only* when that spelled
    key exceeded `_MAX_KEY`. A short id combination was therefore never folded:
    its sole historical form is the spelled-out key, which is already the current
    key. Recognising a folded form for such a combination would invent a key the
    old algorithm could not have written.
    """
    spelled = _SEPARATOR.join((WORK_DISPATCH_KEY_VERSION,) + tuple(parts))
    return len(spelled) > _MAX_KEY


def _is_current_folded(key):
    tail = key[len(_FOLDED_HEAD):]
    return (key.startswith(_FOLDED_HEAD) and len(tail) == 64
            and all(char in "0123456789abcdef" for char in tail))


def work_dispatch_key(work_id, action_id, step_id):
    """Stable, collision-free internal key for one declared Work step.

    `w1:<work_id>:<action_id>:<step_id>` — the step's own id alone would collide
    across actions (and with historical run ids), so the action is part of the
    key. `attempt` stays a separate column, exactly as before.

    A legal id may still be long enough that the spelled-out key exceeds
    `_MAX_KEY`; then the whole field set folds into one fixed-size digest
    (`w1h:<digest>`). Truncation is never used: cutting the key would let two
    distinct identities share one.
    """
    parts = _fields(work_id, action_id, step_id)
    key = _SEPARATOR.join((WORK_DISPATCH_KEY_VERSION,) + parts)
    return key if len(key) <= _MAX_KEY else _folded_key(parts)


def split_work_dispatch_key(key):
    """Recover the fields of a spelled-out v1 Work key; refuse anything else.

    A folded key states no recoverable fields, so it is refused here; its
    original fields are verified with `identity_agrees`, which recomputes the
    digest from them.
    """
    if type(key) is not str:
        raise ApplicationError("WORK_DISPATCH_IDENTITY_INVALID")
    parts = key.split(_SEPARATOR)
    if len(parts) != 4 or parts[0] != WORK_DISPATCH_KEY_VERSION:
        raise ApplicationError("WORK_DISPATCH_IDENTITY_INVALID")
    return _unescape(parts[1]), _unescape(parts[2]), _unescape(parts[3])


def identity_is_current(key, work_id, action_id, step_id):
    """The *current* canonical identity: exactly the key a new write mints.

    This is the entry an active write (and a current lookup) uses. It is exact on
    purpose: a key produced by the pre-fix algorithm — the truncated folded form —
    is **not** current, so an active writer can never adopt a historical key.
    """
    if type(key) is not str:
        return False
    try:
        expected = work_dispatch_key(work_id, action_id, step_id)
    except ApplicationError:
        return False
    return key == expected


def historical_identity_agrees(key, work_id, action_id, step_id):
    """Explicit historical verification: recompute the key from the original fields.

    A row written before the key fix keeps its original bytes and digest. This is
    the one entry that still recognises such a key: the historical folded form is
    recomputed from the original fields and compared, so an old row is verified —
    or reconciled — instead of reading as absent. It never mints a new write.

    The folded form is only recognised where the pre-fix algorithm would actually
    have folded: a short id combination keeps exactly one historical form, the
    spelled-out key, which is already the current key.
    """
    if type(key) is not str:
        return False
    try:
        parts = _fields(work_id, action_id, step_id)
    except ApplicationError:
        return False
    if key == work_dispatch_key(work_id, action_id, step_id):
        return True
    if (key.split(_SEPARATOR)[:1] == [_FOLDED_PREFIX]
            and _historical_folding_applies(parts)):
        return key == _historical_folded_key(parts)
    return False


def identity_agrees(key, work_id, action_id, step_id):
    """Historical-tolerant comparison, retained as the pre-split entry point.

    New *writes* must use `identity_is_current`; a read that must recognise a row
    written before the key fix uses `historical_identity_agrees`. This name keeps
    the original historical-tolerant behaviour for existing callers and tests.
    """
    return historical_identity_agrees(key, work_id, action_id, step_id)


def work_dispatch_key_candidates(work_id, action_id, step_id):
    """Every key form that can name this declared step, the current key first.

    A read reconciles these candidates: the row may have been written under the
    current key *or* under the explicit historical folded form. A new *write*
    never uses a candidate — it mints exactly `work_dispatch_key`.

    A short id combination has only one real form: the pre-fix algorithm never
    folded it, so the spelled-out current key is its whole history. Offering a
    folded candidate there would be a ghost — a key no writer ever minted.
    """
    parts = _fields(work_id, action_id, step_id)
    current = work_dispatch_key(work_id, action_id, step_id)
    if not _historical_folding_applies(parts):
        return (current,)
    historical = _historical_folded_key(parts)
    return (current,) if historical == current else (current, historical)


def is_work_key(key):
    """True for any key this module mints (spelled out or folded)."""
    if type(key) is not str:
        return False
    parts = key.split(_SEPARATOR)
    if parts[0] == WORK_DISPATCH_KEY_VERSION:
        return len(parts) == 4
    if parts[0] == _FOLDED_PREFIX:
        # The current form is exact. A historical row is the escaped fields plus
        # their digest, cut to the key bound, so only its prefix is checkable.
        return _is_current_folded(key) or (len(parts) >= 2 and len(key) <= _MAX_KEY)
    return False


def is_folded_work_key(key):
    return (is_work_key(key)
            and key.split(_SEPARATOR)[:1] == [_FOLDED_PREFIX])


def subject_of(kind, ref):
    """A declared step's subject: kind plus its exact reference (never renamed)."""
    if kind not in SUBJECT_KINDS:
        raise ApplicationError("WORK_DISPATCH_SUBJECT_INVALID")
    if type(ref) is not dict or not ref:
        raise ApplicationError("WORK_DISPATCH_SUBJECT_INVALID")
    return {"subject_kind": kind, "subject_ref": dict(ref)}


def digest_of(value):
    """Digest recorded for a new binding; new schema only, old rows untouched."""
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


__all__ = ["WORK_DISPATCH_KEY_VERSION", "SUBJECT_KINDS", "work_dispatch_key",
           "split_work_dispatch_key", "identity_agrees", "identity_is_current",
           "historical_identity_agrees", "work_dispatch_key_candidates",
           "is_work_key", "subject_of", "digest_of", "UNIT_BOOTSTRAP_OPERATION",
           "unit_bootstrap_operation_id", "unit_bootstrap_request_key",
           "unit_bootstrap_digest"]
