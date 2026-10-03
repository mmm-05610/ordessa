"""T07 credential glue: unified two-layer secret resolution, fail-closed.

FR-08 / ``docs/design/mcp/contracts.md`` §5 / data-model "秘密与留存" /
verification counterexample 8. The MCP domain owns **no vault**: secrets are
resolved only through the unified credential reference service, at the
controlled launch/request instant, and never reach persisted definitions,
frontend DTOs, events, logs or generated native files.

Two layers exist on the host today (binding table G7,
``specs/011-q4-mcp/t00-interface-bindings.md``): ``CredentialRecords``
(``apps/server/.../credentials.py``, port ``credentials``) names the
credential id -> locator identity, and the ``SecretStore`` protocol
(``packages/pacthold/.../storage/secrets.py``, port ``secret_store``) reads
the bytes at a locator; ``secret_store`` is ``None`` off Windows NT. This
module defines the consumer port :class:`CredentialPort`
(``has``/``read``) over exactly those two layers via
:func:`host_credential_port`, a **thin adapter that injects the host objects
rather than importing host internals** (import-boundary rule), and the plan
machinery:

* :class:`LaunchPlan` binds ``credentialRefRevisions`` - slot entries shaped
  like ``backend/resolve.py``'s snapshot ``credential_ref_revisions``
  (definition_id / revision / slot / credential_id) plus the credential
  revision/digest observed when the plan was frozen;
* :func:`resolve_for_launch` re-reads every slot at the launch instant and
  compares against the bound revision: any rotation, revocation, expiry or
  mismatch is a typed ``PLAN_STALE`` / ``SECRET_UNRESOLVED`` refusal and
  **the whole batch fails - no partial injection**;
* a ``None`` secret store (non-NT) fails closed with
  ``SECRET_UNRESOLVED`` on any resolution request (G7 convention);
* :func:`redact` and :class:`ResolvedSecrets` provide the leak guarantees:
  repr/str/log serialisation only ever shows slot + credential id +
  revision, and deep-scan redaction replaces any resolved value in
  strings/dicts/lists/tuples/sets/bytes with ``***``.

Zero file IO, zero network, zero spawn in this module - enforced by an AST
pin in ``tests/permissions`` (dispatch: 绝不写盘明文).

New codes registered in this module (``errors.py`` untouched per dispatch):
``PLAN_STALE`` (rotated/revoked/expired plan binding, FR-08 "凭据轮换使计划
过期"), ``MCP_PLAN_BINDING_INVALID`` (plan shape errors). ``SECRET_UNRESOLVED``
is the FR-10 code already in ``backend/errors.py``.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Protocol, Sequence, Tuple, Union, runtime_checkable

from .errors import (
    MCP_PLAN_BINDING_INVALID,
    PLAN_STALE,
    SECRET_UNRESOLVED,
    McpError,
)

# T014 converge: PLAN_STALE / MCP_PLAN_BINDING_INVALID are registered in
# backend/errors.py; this module keeps re-exporting them for its consumers.

REDACTION = "***"
_SLOT_KINDS = ("env", "header")


@runtime_checkable
class CredentialPort(Protocol):
    """Consumer port over the host's two credential layers.

    ``read`` returns ``(plaintext, revision)``: the plaintext lives only for
    the controlled launch instant, and ``revision`` is whatever identity of
    the stored bytes the layer can offer (a content digest under the host
    adapter - see :func:`host_credential_port`; the Q5/C0 unified
    "resolve-at-authorization API" may replace it with a service revision).
    """

    def has(self, credential_id: str) -> bool: ...

    def read(self, credential_id: str) -> Tuple[str, str]: ...


class HostCredentialPort:
    """Thin adapter over ``CredentialRecords`` + ``SecretStore`` (G7, injected).

    The host objects are passed in, not imported: the plugin keeps its
    zero-product-dependency boundary while the composition (T09) wires the
    real ports. ``secret_store`` may be ``None`` (non-NT deployments): then
    every resolution request is a typed ``SECRET_UNRESOLVED`` refusal, and
    ``has`` answers ``False`` so planning fails closed instead of pretending.

    The host offers no credential revision counter (registered limitation):
    the adapter digests the stored bytes (``sha256:<hex>``, never the
    plaintext) and uses that as the revision identity - rotation changes
    the bytes, hence the digest, hence the plan comparison, exactly as a
    revision counter would; revocation removes the record and ``has`` fails.
    """

    def __init__(self, *, credential_records: Any, secret_store: Any) -> None:
        self._records = credential_records
        self._store = secret_store

    def has(self, credential_id: str) -> bool:
        if self._store is None or self._records is None:
            return False
        try:
            return bool(self._records.exists(credential_id))
        except Exception:
            return False

    def read(self, credential_id: str) -> Tuple[str, str]:
        if self._store is None:
            raise McpError(
                SECRET_UNRESOLVED,
                f"credential {credential_id!r}: no secret store is available on this "
                "platform (secret_store=None); resolution fails closed (G7)")
        if self._records is None:
            raise McpError(
                SECRET_UNRESOLVED,
                f"credential {credential_id!r}: no credential record layer is wired")
        try:
            row = self._records.get(credential_id)
            locator = row["secret_locator"]
            raw = self._store.read(locator)
        except McpError:
            raise
        except Exception as exc:
            # the host layers carry the locator in their own messages; the
            # typed refusal here quotes only the error type, never locator
            # paths or secret bytes.
            raise McpError(
                SECRET_UNRESOLVED,
                f"credential {credential_id!r} did not resolve: {type(exc).__name__}") from exc
        plaintext = raw.decode("utf-8", errors="strict") if isinstance(raw, (bytes, bytearray)) else str(raw)
        revision = "sha256:" + hashlib.sha256(raw if isinstance(raw, (bytes, bytearray))
                                              else plaintext.encode("utf-8")).hexdigest()
        return plaintext, revision


def host_credential_port(*, credential_records: Any, secret_store: Any) -> HostCredentialPort:
    """Wire the two existing host layers into one :class:`CredentialPort`."""
    return HostCredentialPort(credential_records=credential_records, secret_store=secret_store)


@dataclass(frozen=True)
class CredentialBinding:
    """One slot of ``credentialRefRevisions``: the resolve-snapshot entry
    (``definition_id``/``revision``/``slot``/``credential_id`` as produced by
    ``backend/resolve.py``) plus the credential ``bound_revision`` frozen at
    plan time and the slot's injection kind."""

    definition_id: str
    revision: int
    slot: str
    credential_id: str
    bound_revision: str
    kind: str = "env"

    def __post_init__(self) -> None:
        for name in ("definition_id", "slot", "credential_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise McpError(MCP_PLAN_BINDING_INVALID, f"binding needs a non-empty {name}")
        if not isinstance(self.revision, int) or self.revision < 1:
            raise McpError(MCP_PLAN_BINDING_INVALID, "binding revision must be a positive int")
        if not isinstance(self.bound_revision, str) or not self.bound_revision:
            raise McpError(
                MCP_PLAN_BINDING_INVALID,
                f"binding {self.slot!r} must carry the credential revision frozen at plan time")
        if self.kind not in _SLOT_KINDS:
            raise McpError(MCP_PLAN_BINDING_INVALID, f"binding kind must be one of {_SLOT_KINDS}")

    @property
    def key(self) -> str:
        return f"{self.definition_id}#{self.revision}#{self.kind}#{self.slot}"


@dataclass(frozen=True)
class LaunchPlan:
    """A pre-launch plan bound to principal, session and the credential
    revision set (contracts §5); applying it re-verifies before any effect."""

    principal: str
    bindings: Tuple[CredentialBinding, ...] = ()
    session_ref: Optional[str] = None
    expires_at: Optional[float] = None

    def __post_init__(self) -> None:
        if not isinstance(self.principal, str) or not self.principal:
            raise McpError(MCP_PLAN_BINDING_INVALID, "a launch plan needs a principal")
        if not isinstance(self.bindings, tuple):
            raise McpError(MCP_PLAN_BINDING_INVALID, "bindings must be a tuple")
        keys = [b.key for b in self.bindings]
        if len(keys) != len(set(keys)):
            raise McpError(MCP_PLAN_BINDING_INVALID, "duplicate slot binding in one plan")
        if self.expires_at is not None and not isinstance(self.expires_at, (int, float)):
            raise McpError(MCP_PLAN_BINDING_INVALID, "expires_at must be numeric epoch seconds")


@dataclass(frozen=True)
class SlotProof:
    """Per-slot resolution certificate: names and revisions only, never the
    plaintext; safe for audit events and API responses."""

    slot: str
    definition_id: str
    credential_id: str
    bound_revision: str
    resolved_revision: str

    def as_record(self) -> dict:
        return {
            "slot": self.slot, "definitionId": self.definition_id,
            "credentialId": self.credential_id,
            "boundRevision": self.bound_revision,
            "resolvedRevision": self.resolved_revision,
        }


class ResolvedSecrets:
    """Ephemeral holder of resolved slot values plus their proofs.

    ``env``/``headers`` are the transient injection maps (slot key ->
    plaintext) meant for exactly one launch/request; everything else about
    this container - ``repr``, ``str``, :meth:`references`, pickling - is
    plaintext-free by construction (slot name + credential id + revision
    only).
    """

    __slots__ = ("_env", "_headers", "_proofs")

    def __init__(self, env: Mapping[str, str], headers: Mapping[str, str],
                 proofs: Sequence[SlotProof]) -> None:
        self._env = dict(env)
        self._headers = dict(headers)
        self._proofs = tuple(proofs)

    @property
    def env(self) -> Mapping[str, str]:
        return self._env

    @property
    def headers(self) -> Mapping[str, str]:
        return self._headers

    @property
    def proofs(self) -> Tuple[SlotProof, ...]:
        return self._proofs

    def plaintext_values(self) -> Tuple[str, ...]:
        """The values :func:`redact` needs; explicit on purpose - injection
        code should read ``env``/``headers``, logging code should never call
        this."""
        return tuple(self._env.values()) + tuple(self._headers.values())

    def references(self) -> Tuple[dict, ...]:
        """Ref-only view for persistence and API: slot, credential id and
        revisions; no value material whatsoever."""
        return tuple(p.as_record() for p in self._proofs)

    def __repr__(self) -> str:
        return ("ResolvedSecrets(env=%r, headers=%r, proofs=%r)"
                % (_slot_names(self._env), _slot_names(self._headers), self._proofs))

    def __str__(self) -> str:
        return repr(self)

    def __getstate__(self):  # never carry plaintext across pickling/copy
        raise McpError(SECRET_UNRESOLVED, "resolved secrets are transient: containers "
                                          "holding them are never serialisable (FR-08)")

    def __deepcopy__(self, memo):
        raise McpError(SECRET_UNRESOLVED, "resolved secrets are transient: containers "
                                          "holding them are never serialisable (FR-08)")


def _slot_names(mapping: Mapping[str, str]) -> Tuple[str, ...]:
    return tuple(sorted(mapping))


def snapshot_credential_bindings(
    snapshot: Any, revisions_by_credential_id: Mapping[str, str],
    kinds_by_slot: Optional[Mapping[Tuple[str, int, str], str]] = None,
) -> Tuple[CredentialBinding, ...]:
    """Freeze a plan's ``credentialRefRevisions`` from an effective snapshot.

    The snapshot entries (``backend/resolve.py``
    ``credential_ref_revisions``) carry definition/slot/credential identity;
    the caller supplies the credential revisions observed at plan time (via
    ``port``), and any slot without one is a typed fail-closed refusal - a
    plan never carries an unbound secret slot.
    """
    if isinstance(snapshot, Mapping):
        entries = snapshot.get("credential_ref_revisions",
                               snapshot.get("credentialRefRevisions", ())) or ()
    else:
        entries = getattr(snapshot, "credential_ref_revisions", ()) or ()
    bindings = []
    for entry in entries:
        record = dict(entry)
        definition_id = record.get("definition_id")
        revision = record.get("revision")
        slot = record.get("slot")
        credential_id = record.get("credential_id")
        bound = revisions_by_credential_id.get(credential_id)
        if bound is None:
            raise McpError(
                SECRET_UNRESOLVED,
                f"credential {credential_id!r} for slot {slot!r} of {definition_id!r} "
                "has no revision bound at plan time")
        kind = "env"
        if kinds_by_slot:
            kind = kinds_by_slot.get((definition_id, revision, slot), kind)
        bindings.append(CredentialBinding(
            definition_id=definition_id, revision=revision, slot=slot,
            credential_id=credential_id, bound_revision=str(bound), kind=kind))
    return tuple(bindings)


def resolve_for_launch(plan: LaunchPlan, port: CredentialPort, now: float) -> ResolvedSecrets:
    """Resolve every bound slot at the launch instant, or nothing at all.

    Re-validation order (contracts §5 / FR-08): plan expiry first (an
    expired plan never touches the store), then per slot ``has`` (revoked ->
    ``SECRET_UNRESOLVED``), then ``read`` and revision comparison (rotated
    -> ``PLAN_STALE``). Any single bad slot aborts the whole batch: partial
    injection would silently start a server with half its secret surface,
    which is exactly what the counterexample forbids ("整批不解析").
    Refusal messages name slots and credential ids only - never plaintext.
    """
    if not isinstance(plan, LaunchPlan):
        raise McpError(MCP_PLAN_BINDING_INVALID, "resolve_for_launch needs a LaunchPlan")
    if not isinstance(now, (int, float)):
        raise McpError(MCP_PLAN_BINDING_INVALID, "now must be numeric epoch seconds")
    if plan.expires_at is not None and now > plan.expires_at:
        raise McpError(
            PLAN_STALE,
            f"stale plan: plan of principal {plan.principal!r} expired at {plan.expires_at!r}")

    env: dict = {}
    headers: dict = {}
    proofs = []
    stale = []
    missing = []
    causes = {}
    for binding in plan.bindings:
        try:
            present = port.has(binding.credential_id)
        except Exception:
            present = False
        if not present:
            missing.append(binding)
            continue
        try:
            plaintext, revision = port.read(binding.credential_id)
        except McpError as exc:
            missing.append(binding)
            causes[binding.key] = exc.message
            continue
        except Exception as exc:
            raise McpError(
                SECRET_UNRESOLVED,
                f"credential {binding.credential_id!r} for slot {binding.slot!r} "
                f"did not resolve: {type(exc).__name__}") from exc
        if str(revision) != binding.bound_revision:
            stale.append(binding)
            continue
        target = env if binding.kind == "env" else headers
        target[binding.key] = plaintext
        proofs.append(SlotProof(
            slot=binding.key, definition_id=binding.definition_id,
            credential_id=binding.credential_id, bound_revision=binding.bound_revision,
            resolved_revision=str(revision)))

    # batch semantics: evaluate every slot, but release nothing on any fault.
    if missing:
        raise McpError(
            SECRET_UNRESOLVED,
            "credential(s) unresolved for slots "
            + ", ".join(b.key for b in missing)
            + ("; cause: " + sorted(causes.values())[0] if causes else "")
            + "; the whole batch stayed unresolved")
    if stale:
        raise McpError(
            PLAN_STALE,
            "stale plan: credential revision moved (rotation/revocation) for slots "
            + ", ".join(b.key for b in stale) + "; the whole batch stayed unresolved")
    return ResolvedSecrets(env=env, headers=headers, proofs=proofs)


def _secret_strings(secrets: Union[ResolvedSecrets, Iterable[Any], Any]) -> Tuple[str, ...]:
    if isinstance(secrets, ResolvedSecrets):
        values = secrets.plaintext_values()
    elif isinstance(secrets, (bytes, bytearray)):
        values = (secrets.decode("utf-8", errors="replace"),)
    elif isinstance(secrets, str):
        values = (secrets,)
    elif isinstance(secrets, Iterable):
        values = tuple(
            v.decode("utf-8", errors="replace") if isinstance(v, (bytes, bytearray)) else str(v)
            for v in secrets if isinstance(v, (str, bytes, bytearray)))
    else:
        values = (str(secrets),)
    return tuple(v for v in values if v)


def redact(obj: Any, secrets: Union[ResolvedSecrets, Iterable[Any], Any]) -> Any:
    """Deep-scan a dict/list/tuple/set/str/bytes structure and replace every
    occurrence of any resolved value with ``***``.

    Keys are scanned too (slot maps can carry values as keys), and the
    result keeps the shape of the input. Intended for event payloads, error
    contexts and log records that must be provably plaintext-free even when
    a host layer already interpolated a secret into a message.
    """
    values = _secret_strings(secrets)
    if not values:
        return obj

    def _scrub_text(text: str) -> str:
        for value in values:
            if value in text:
                text = text.replace(value, REDACTION)
        return text

    def _walk(node: Any) -> Any:
        if isinstance(node, str):
            return _scrub_text(node)
        if isinstance(node, (bytes, bytearray)):
            decoded = bytes(node).decode("utf-8", errors="replace")
            scrubbed = _scrub_text(decoded)
            return scrubbed.encode("utf-8") if scrubbed != decoded else node
        if isinstance(node, Mapping):
            return {_walk(k): _walk(v) for k, v in node.items()}
        if isinstance(node, tuple):
            return tuple(_walk(item) for item in node)
        if isinstance(node, list):
            return [_walk(item) for item in node]
        if isinstance(node, (set, frozenset)):
            return type(node)(_walk(item) for item in node)
        return node

    return _walk(obj)
