"""Artifact commands on one Engineering UoW; no legacy workflow fallback.

Current commands use material record v2/schema6. Bytes and source selectors
are resolved by the original repository; unavailable upstream/execution owners
refuse explicitly. Authentication still belongs to trusted composition.
"""
from dataclasses import asdict
import hashlib
from uuid import uuid4

from jsonschema import Draft202012Validator
from ordessa_infrastructure.encoding import canonical_bytes

from ...domain.artifacts.models import ARTIFACT_KINDS, Artifact, ArtifactRevision, InlinePayload
from ...domain.artifacts.codec import decode_payload, decode_provenance_fields
from ordessa_engineering.domain.artifacts.refs import (ArtifactRevisionRef)
from ...domain.common.models.values import (Digest)
from ...domain.common.outcomes.diagnostics import (ReferenceError)
from ...domain.common.mechanisms.codec import (canonical_value)
from ordessa_engineering.application.contracts.commands import CommandContext, CommandResult, ReadSet, request_digest, artifact_read_set_projection
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.repositories import CommandAccessPort
from ordessa_engineering.application.contracts.transactions import UoWFactory
from .material_closure import verify_material

_VERSION = "2"
_ID = {"type": "string", "minLength": 1, "maxLength": 512}
_DIGEST = {"type": "object", "properties": {"algorithm": {"const": "sha256"},
    "hex": {"type": "string", "pattern": "^[a-f0-9]{64}$"}},
    "required": ["algorithm", "hex"], "additionalProperties": False}
# The pure closed codec validates each discriminated payload/provenance shape.
_PAYLOAD = {"type": "object"}
_PROVENANCE = {"sources": {"type":"array","maxItems":4096},
    "claims": {"type":"array","maxItems":4096},
    "evidence_links": {"type":"array","maxItems":4096},
    "method_refs": {"type":"array","maxItems":4096},
    "generation_origin": {"type":["object","null"]}}


def _provenance(value):
    return decode_provenance_fields({name:value.get(name, None if name=='generation_origin' else [])
                                    for name in _PROVENANCE})

_PARENT = {"type": "object", "properties": {"kind": {"const": "artifact_revision"},
    "realm_id": _ID, "project_id": _ID, "artifact_id": _ID, "revision_id": _ID,
    "digest": _DIGEST}, "required": ["kind", "realm_id", "project_id", "artifact_id", "revision_id", "digest"],
    "additionalProperties": False}


def _schema(operation, properties, required):
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"urn:ordessa:engineering:operations:{operation}:input:2", "type": "object",
        "properties": properties, "required": required, "additionalProperties": False}


# Captured bytes are the source of validators and digest pins. No mutable schema
# object is exposed; these two actual handlers do not register other operations.
_SCHEMA_BYTES = {
    "engineering.artifacts.create": canonical_bytes(_schema("engineering.artifacts.create",
        {"kind": {"enum": sorted(ARTIFACT_KINDS)}, "initial": _PAYLOAD, **_PROVENANCE}, ["kind"])),
    "engineering.artifacts.append_revision": canonical_bytes(_schema("engineering.artifacts.append_revision",
        {"artifact_id": _ID, "expected_version": {"type": "integer", "minimum": 0,
         "maximum": 9007199254740991}, "parents": {"type": "array", "maxItems": 4096, "items": _PARENT},
         "payload": _PAYLOAD, **_PROVENANCE}, ["artifact_id", "expected_version", "parents", "payload"])),
}
BUSINESS_REFUSALS = frozenset({"NOT_FOUND", "VERSION_CONFLICT", "READ_SET_CHANGED",
    "SCOPE_MISMATCH", "REVIEW_REQUEST_CHANGED", "REVIEW_SET_CHANGED", "REVIEW_CONTROL_CHANGED", "REVIEW_SCHEMA_REQUIRED", "UNSUPPORTED_ARTIFACT_KIND", "UNSUPPORTED_READ_KIND", "VERSION_EXHAUSTED", "ANCESTRY_LIMIT",
    "MATERIAL_LIMIT", "MATERIAL_BLOB_INVALID", "MATERIAL_BLOB_NOT_FOUND", "MATERIAL_BLOB_CORRUPT",
    "MATERIAL_CONTENT_INVALID", "METHOD_RESOURCE_MISMATCH", "METHOD_SCHEMA_INVALID",
    "METHOD_SCHEMA_ID_MISMATCH", "METHOD_CONTENT_INVALID",
    "SOURCE_VERSION_UNAVAILABLE", "SOURCE_OWNER_UNAVAILABLE", "GENERATION_ORIGIN_UNAVAILABLE",
    "MATERIAL_METHOD_SNAPSHOT_NOT_FOUND", "MATERIAL_METHOD_SNAPSHOT_CONTENT_CORRUPT",
    "MATERIAL_METHOD_SNAPSHOT_SOURCE_MISMATCH", "MATERIAL_METHOD_SNAPSHOT_BLOB_NOT_FOUND",
    "MATERIAL_METHOD_SNAPSHOT_BLOB_CORRUPT", "MATERIAL_METHOD_SNAPSHOT_BLOB_INVALID"})


def input_schema(operation):
    """A detached copy for an eventual actual owner binding, not a catalog."""
    try:
        return canonical_value(_SCHEMA_BYTES[operation])
    except KeyError:
        raise ApplicationError("OPERATION_UNAVAILABLE") from None


class ArtifactUseCases:
    def __init__(self, factory: UoWFactory, access: CommandAccessPort | None):
        self.factory = factory
        self.access = access

    def _authorize(self, context, operation):
        if type(context) is not CommandContext:
            raise ApplicationError("INVALID_CONTEXT")
        if self.access is None:
            raise ApplicationError("ACCESS_AUTHORITY_UNAVAILABLE")
        # A client-provided actor kind, issuer or principal never grants access.
        self.access.require(context, operation)

    def create(self, parameters: dict, context: CommandContext, *, read_set: ReadSet | None = None):
        return self._command("engineering.artifacts.create", parameters, context, read_set)

    def append_revision(self, parameters: dict, context: CommandContext, *, read_set: ReadSet | None = None):
        return self._command("engineering.artifacts.append_revision", parameters, context, read_set)

    def _command(self, operation, parameters, context, read_set):
        self._authorize(context, operation)
        try:
            value = canonical_value(canonical_bytes(parameters))
            schema = input_schema(operation)
            if not Draft202012Validator(schema).is_valid(value):
                raise ApplicationError("INVALID_INPUT")
            provenance = _provenance(value)
            payload_key = 'initial' if operation == 'engineering.artifacts.create' else 'payload'
            if payload_key in value:
                decode_payload(value[payload_key])
            elif any(provenance.values()):
                raise ApplicationError('INVALID_INPUT')
            reads = ReadSet(context.scope, ()) if read_set is None else read_set
            if type(reads) is not ReadSet or reads.scope != context.scope:
                raise ApplicationError("SCOPE_MISMATCH")
            preconditions = artifact_read_set_projection(reads)
            digest = request_digest(operation, context, value, preconditions,
                input_schema_id=schema["$id"], interface_version=_VERSION,
                input_schema_digest=Digest("sha256", hashlib.sha256(_SCHEMA_BYTES[operation]).hexdigest()))
        except (ReferenceError, TypeError, ValueError, RecursionError, OverflowError):
            raise ApplicationError("INVALID_INPUT") from None

        with self.factory.begin(context.scope) as uow:
            uow.engineering.require_material_schema()
            reservation = uow.commands.reserve(context.key, project_id=context.scope.project_id,
                operation=operation, operation_id=str(uuid4()), request_digest=digest)
            entry = reservation.entry
            if not reservation.created:
                # Pending means reconcile the original command, never execute again.
                return CommandResult(uow.authority_id, entry.operation_id, entry.state, entry.result_bytes)
            state = "completed"
            try:
                with uow.isolate():
                    uow.engineering.require_material_schema()
                    uow.engineering.check_read_set(reads)
                    result = self._mutate(uow, operation, value, context)
            except ReferenceError:
                state, result = "rejected", {"code": "INVALID_INPUT"}
            except ApplicationError as exc:
                if exc.code not in BUSINESS_REFUSALS:
                    raise
                state, result = "rejected", {"code": exc.code}
            final = uow.commands.complete(context.key, expected_version=entry.version,
                result_bytes=canonical_bytes(result), state=state)
            answer = CommandResult(uow.authority_id, final.operation_id, final.state, final.result_bytes)
            uow.commit()
            return answer

    @staticmethod
    def _mutate(uow, operation, value, context):
        if operation == "engineering.artifacts.create":
            artifact = Artifact(context.scope, str(uuid4()), value["kind"], context.received_at)
            uow.engineering.create(artifact)
            ref = None
            if "initial" in value:
                revision = ArtifactRevision(context.scope, artifact.artifact_id, str(uuid4()),
                    context.received_at, context.authenticated_actor,
                    decode_payload(value["initial"]), schema_version=2, **_provenance(value))
                verify_material(revision, uow.engineering.validated_budget())
                ref = uow.engineering.append_revision(revision, expected_version=0)
            return {"artifact": _artifact(uow.engineering.get_artifact(artifact.artifact_id)),
                    "revision_ref": asdict(ref) if ref is not None else None}
        parents = tuple(ArtifactRevisionRef(p["realm_id"], p["project_id"], p["artifact_id"],
            p["revision_id"], Digest(**p["digest"])) for p in value["parents"])
        revision = ArtifactRevision(context.scope, value["artifact_id"], str(uuid4()),
            context.received_at, context.authenticated_actor,
            decode_payload(value["payload"]), parents, schema_version=2, **_provenance(value))
        verify_material(revision, uow.engineering.validated_budget())
        ref = uow.engineering.append_revision(revision, expected_version=value["expected_version"])
        return {"revision_ref": asdict(ref)}

    def get_artifact(self, artifact_id: str, context: CommandContext):
        self._authorize(context, "engineering.artifacts.get")
        with self.factory.begin(context.scope, mode="read") as uow:
            return uow.engineering.get_artifact(artifact_id)

    def get_command(self, context: CommandContext):
        self._authorize(context, "engineering.commands.get")
        with self.factory.begin(context.scope, mode="read") as uow:
            entry = uow.commands.get(context.key)
            if entry is None:
                raise ApplicationError("COMMAND_NOT_FOUND")
            return CommandResult(uow.authority_id, entry.operation_id, entry.state, entry.result_bytes)


def _artifact(value):
    return {"realm_id": value.scope.realm_id, "project_id": value.scope.project_id,
        "artifact_id": value.artifact_id, "kind": value.kind, "created_at": value.created_at,
        "head_revision_id": value.head_revision_id, "version": value.version}
