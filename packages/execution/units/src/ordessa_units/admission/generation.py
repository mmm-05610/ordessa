"""Durable owner-generation allocation on the original Unit store.

The generation high-water mark assigns identity only: it never becomes a
second activation or lifecycle account. Role catalogs own their registrations.
Persistence reuses the existing DomainStorePort and
DomainWrite CAS on the same Store; no second database, registry or persistent
identifier is created.

The fresh-environment initialization evidence is written by the deployment in
the same transaction that creates a new persistent EnvironmentId on its own
exclusive root. It is never a request parameter or plugin declaration. An
existing database without that evidence is refused: nothing is guessed, and
generation 1 is never silently re-seeded.

Reservations are one atomic ``commit_domain_change`` CAS (reserve and durable
confirmation are one write, not a two-state record). Each attempt uses an
explicit core-internal request identity whose request id carries the attempt
nonce, so a replay of the same request returns the original allocation while a
different attempt can never claim another attempt's generation. An unknown
reservation outcome is never published and never automatically resent; a
failed publication may consume a generation and the high-water never rolls
back.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable, Mapping
from uuid import uuid4

from ordessa_execution_api.environment import GuaranteeUnavailableError
from ordessa_infrastructure.database.records import (
    DomainRevisionConflict,
    DomainWrite,
)
from ordessa_infrastructure.identifiers import RequestKey

ACTIVATION_SEED_NAMESPACE = "core.environment"
ACTIVATION_SEED_RECORD = "activation-generation-basis"
ACTIVATION_SEED_SCHEMA = "activation-generation-basis/1"
ACTIVATION_GENERATION_NAMESPACE = "pacthold.activation-generation"
ACTIVATION_GENERATION_SCHEMA = "activation-generation/1"
JOURNAL_BINDING_RECORD = "native-journal-binding"
JOURNAL_BINDING_SCHEMA = "native-journal-binding/1"
# Reserved core-internal principal: these request keys must never collide with
# wire-visible caller request keys or be readable as ordinary activities.
INTERNAL_PRINCIPAL = "pacthold.internal"

_REQUEST_NONCE = re.compile(r"[a-z0-9]{8,32}$")


class ActivationGenerationRefused(GuaranteeUnavailableError):
    """Durable generation allocation is unavailable or its evidence damaged."""


class ActivationGenerationUnknown(ActivationGenerationRefused):
    """The reservation outcome is unknown: do not publish and do not resend."""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":"))


def _content_digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _require_mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ActivationGenerationRefused("stored generation evidence is not an object")
    return value


def seed_fresh_environment(connection: Any, environment_id: str) -> Mapping[str, str]:
    """Write the fresh-environment basis inside the deployment's birth transaction.

    ``connection`` is the open transaction of the sole Store that is creating
    the new persistent EnvironmentId; the basis row commits together with the
    deployment identity rows. Only a deployment that creates a brand-new
    persistent Environment on its own exclusive root may call this.
    """
    if not isinstance(environment_id, str) or not environment_id:
        raise ActivationGenerationRefused("fresh basis requires the new persistent environment id")
    value = {"createdBy": "agent-tools-deployment/1",
             "contractVersion": ACTIVATION_SEED_SCHEMA,
             "environmentId": environment_id,
             "seed": uuid4().hex}
    connection.execute(
        "INSERT INTO env_domain_records(environment, namespace, record_id, revision, payload) "
        "VALUES (?, ?, ?, 1, ?)",
        (environment_id, ACTIVATION_SEED_NAMESPACE, ACTIVATION_SEED_RECORD,
         json.dumps(value, sort_keys=True, allow_nan=False)),
    )
    return value


def read_fresh_basis(store: Any, environment_id: str) -> Mapping[str, Any] | None:
    """Read and strictly validate the fresh-environment basis; None when absent.

    Damaged evidence is refused rather than treated as absent: a corrupt basis
    must never fall through to a first allocation.
    """
    try:
        record = store.read_domain(environment_id, ACTIVATION_SEED_NAMESPACE, ACTIVATION_SEED_RECORD)
    except ActivationGenerationRefused:
        raise
    except Exception:
        raise ActivationGenerationRefused("fresh-environment basis is unreadable") from None
    if record is None:
        return None
    record = _require_mapping(record)
    if type(record.get("revision")) is not int or record["revision"] < 1:
        raise ActivationGenerationRefused("fresh-environment basis revision is damaged")
    return validate_fresh_basis(record.get("value"), environment_id)


def validate_fresh_basis(value: Any, environment_id: str) -> Mapping[str, Any]:
    """Strictly validate one decoded fresh-environment basis value."""
    value = _require_mapping(value)
    if (set(value) != {"createdBy", "contractVersion", "environmentId", "seed"}
            or value.get("contractVersion") != ACTIVATION_SEED_SCHEMA
            or value.get("environmentId") != environment_id
            or not isinstance(value.get("createdBy"), str) or not value["createdBy"]
            or not isinstance(value.get("seed"), str) or not value["seed"]):
        raise ActivationGenerationRefused("fresh-environment basis is damaged")
    return dict(value)


def _high_water(record: Any, environment_id: str, owner: str) -> tuple[int, int]:
    """Strictly validate one owner high-water record -> (highWater, revision)."""
    record = _require_mapping(record)
    revision = record.get("revision")
    if type(revision) is not int or revision < 1:
        raise ActivationGenerationRefused("activation generation revision is damaged")
    value = _require_mapping(record.get("value"))
    if (set(value) != {"environment", "owner", "schema", "highWater"}
            or value.get("schema") != ACTIVATION_GENERATION_SCHEMA
            or value.get("environment") != environment_id
            or value.get("owner") != owner
            or type(value.get("highWater")) is not int or value["highWater"] < 1):
        raise ActivationGenerationRefused("activation generation record is damaged")
    return value["highWater"], revision


def _internal_request(environment_id: str, owner: str, candidate: int, nonce: str) -> RequestKey:
    return RequestKey(environment_id, INTERNAL_PRINCIPAL,
                      f"activation.generation.{owner}.{candidate}.{nonce}")


def reserve_next_generation(store: Any, environment_id: str, owner: str, *,
                            fingerprint_port: Any) -> int:
    """Reserve and durably confirm the next activation generation for one owner.

    Single atomic CAS: the reservation IS the confirmation. A conflict never
    claims a generation another request obtained; an unknown outcome is never
    published or resent. The high-water never rolls back.
    """
    if not isinstance(owner, str) or not owner:
        raise ActivationGenerationRefused("activation owner id is required")
    if not callable(getattr(store, "read_domain", None)) or not callable(
            getattr(store, "commit_domain_change", None)):
        raise ActivationGenerationRefused(
            "durable generation allocation requires the store domain CAS face")
    if fingerprint_port is None or not callable(getattr(fingerprint_port, "fingerprint", None)):
        raise ActivationGenerationRefused(
            "durable generation allocation requires the protected fingerprint port")
    for _ in range(8):
        record = store.read_domain(environment_id, ACTIVATION_GENERATION_NAMESPACE, owner)
        if record is None:
            if read_fresh_basis(store, environment_id) is None:
                raise ActivationGenerationRefused(
                    "existing database lacks fresh-environment evidence for generation allocation")
            candidate, expected = 1, 0
        else:
            high_water, revision = _high_water(record, environment_id, owner)
            candidate, expected = high_water + 1, revision
        nonce = uuid4().hex[:16]
        value = {"environment": environment_id, "owner": owner,
                 "schema": ACTIVATION_GENERATION_SCHEMA, "highWater": candidate}
        request = _internal_request(environment_id, owner, candidate, nonce)
        digest = fingerprint_port.fingerprint(
            request, "pacthold.core.activation-generation.reserve",
            _content_digest({"action": "reserve", "nonce": nonce, "owner": owner,
                             "candidate": candidate, "expectedRevision": expected}))
        write = DomainWrite(ACTIVATION_GENERATION_NAMESPACE, owner, expected, value)
        try:
            result = store.commit_domain_change(request, digest, (write,), value)
        except DomainRevisionConflict:
            # Another request obtained this generation; never claim it back.
            continue
        except Exception:
            # Unknown outcome: do not publish, do not automatically resend.
            raise ActivationGenerationUnknown(
                "activation generation reservation outcome is unknown") from None
        if (not isinstance(result, Mapping) or result.get("highWater") != candidate
                or type(result.get("highWater")) is not int):
            raise ActivationGenerationUnknown(
                "activation generation reservation outcome is unknown")
        return candidate
    raise ActivationGenerationRefused(
        "activation generation allocation kept conflicting; no generation was claimed")


def bind_journal(store: Any, environment_id: str, journal_path: str) -> Mapping[str, Any]:
    """Record the trusted journal ownership evidence for this environment.

    The evidence is only written when the owner wiring first establishes its
    canonical journal. An existing journal file without matching evidence is
    refused later; the journal itself is never deleted or rewritten.
    """
    if not isinstance(journal_path, str) or not journal_path:
        raise ActivationGenerationRefused("canonical journal path is required")
    value = {"contractVersion": JOURNAL_BINDING_SCHEMA, "environmentId": environment_id,
             "journalPath": journal_path}
    record = store.read_domain(environment_id, ACTIVATION_SEED_NAMESPACE, JOURNAL_BINDING_RECORD)
    if record is not None:
        record = _require_mapping(record)
        existing = _require_mapping(record.get("value"))
        if (set(existing) != {"contractVersion", "environmentId", "journalPath"}
                or existing.get("contractVersion") != JOURNAL_BINDING_SCHEMA
                or existing.get("environmentId") != environment_id
                or existing.get("journalPath") != journal_path):
            raise ActivationGenerationRefused(
                "existing journal binding evidence differs from this deployment")
        return dict(existing)
    nonce = uuid4().hex[:16]
    request = RequestKey(environment_id, INTERNAL_PRINCIPAL, f"journal.binding.{nonce}")
    digest = _content_digest(
        {"action": "journal-binding", "nonce": nonce, "journalPath": journal_path,
         "environmentId": environment_id})
    write = DomainWrite(ACTIVATION_SEED_NAMESPACE, JOURNAL_BINDING_RECORD, 0, value)
    try:
        result = store.commit_domain_change(request, digest, (write,), value)
    except DomainRevisionConflict:
        raise ActivationGenerationRefused(
            "journal binding evidence was created concurrently") from None
    except Exception:
        raise ActivationGenerationUnknown(
            "journal binding evidence outcome is unknown") from None
    return dict(result)


def verify_journal_binding(store: Any, environment_id: str, journal_path: str) -> None:
    """Refuse an existing journal that lacks matching trusted ownership evidence."""
    record = store.read_domain(environment_id, ACTIVATION_SEED_NAMESPACE, JOURNAL_BINDING_RECORD)
    if record is None:
        raise ActivationGenerationRefused(
            "existing journal lacks trusted ownership evidence")
    record = _require_mapping(record)
    value = _require_mapping(record.get("value"))
    if (set(value) != {"contractVersion", "environmentId", "journalPath"}
            or value.get("contractVersion") != JOURNAL_BINDING_SCHEMA
            or value.get("environmentId") != environment_id
            or value.get("journalPath") != journal_path):
        raise ActivationGenerationRefused(
            "existing journal ownership evidence differs from this deployment")


__all__ = ["ACTIVATION_SEED_NAMESPACE", "ACTIVATION_SEED_RECORD", "ACTIVATION_SEED_SCHEMA",
           "ACTIVATION_GENERATION_NAMESPACE", "ACTIVATION_GENERATION_SCHEMA",
           "JOURNAL_BINDING_RECORD", "JOURNAL_BINDING_SCHEMA", "INTERNAL_PRINCIPAL",
           "ActivationGenerationRefused", "ActivationGenerationUnknown",
           "seed_fresh_environment", "validate_fresh_basis", "read_fresh_basis",
           "reserve_next_generation",
           "bind_journal", "verify_journal_binding"]
