"""Immutable artifact revisions; append never adopts a head or attests support."""
from dataclasses import asdict, dataclass, field

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_engineering.domain.artifacts.refs import (ArtifactRevisionRef)
from ordessa_engineering.domain.common.models.refs import (BlobRef)
from ordessa_engineering.domain.artifacts.method_binding import (MethodRef)
from ..common.models.values import (Digest, validate_id)
from ..common.models.identity import (Scope)
from ..common.outcomes.diagnostics import (ReferenceError)
from ..common.mechanisms.hashing import (record_digest)
from ..common.models.identity import (ActorRef)
from ..common.models.values import (utc_instant)
from ..common.mechanisms.codec import (canonical_value)
from ordessa_engineering.domain.artifacts.provenance import (Claim, EvidenceLink, GenerationOrigin, SourceRef)
from ordessa_engineering.domain.artifacts.method_binding import (ExactMethodResourceRef)
from ..common.mechanisms.selection import (SelectorChecks, verify_selection)
from ..common.mechanisms.codec import (projection)

ARTIFACT_KINDS = frozenset({"design", "specification", "plan", "task_list", "review_body",
                          "implementation_package", "evidence", "other"})
MAX_RECORD_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class InlinePayload:
    media_type: str
    schema_id: str
    value_bytes: bytes

    def __post_init__(self):
        validate_id(self.media_type)
        validate_id(self.schema_id)
        canonical_value(self.value_bytes, maximum=MAX_RECORD_BYTES)

    @classmethod
    def from_value(cls, media_type: str, schema_id: str, value):
        return cls(media_type, schema_id, canonical_bytes(value))

    @property
    def value(self):
        return canonical_value(self.value_bytes)

    def projection(self):
        return {"media_type": self.media_type, "schema_id": self.schema_id, "inline_value": self.value}

    def content_bytes(self):
        return self.value_bytes


@dataclass(frozen=True)
class BlobPayload:
    media_type: str
    schema_id: str
    blob_ref: BlobRef

    def __post_init__(self):
        validate_id(self.media_type)
        validate_id(self.schema_id)
        if type(self.blob_ref) is not BlobRef or self.blob_ref.media_type != self.media_type:
            raise ReferenceError('INVALID_PAYLOAD')

    def projection(self):
        return {'media_type':self.media_type,'schema_id':self.schema_id,'blob_ref':asdict(self.blob_ref)}


@dataclass(frozen=True)
class MethodContent:
    schema_ref: ExactMethodResourceRef
    value_bytes: bytes
    rendered_body_ref: BlobRef | None = None

    def __post_init__(self):
        if (type(self.schema_ref) is not ExactMethodResourceRef
                or self.rendered_body_ref is not None and type(self.rendered_body_ref) is not BlobRef):
            raise ReferenceError('INVALID_METHOD_CONTENT')
        canonical_value(self.value_bytes)

    @classmethod
    def from_value(cls, schema_ref, value, rendered_body_ref=None):
        return cls(schema_ref, canonical_bytes(value), rendered_body_ref)

    @property
    def value(self):
        return canonical_value(self.value_bytes)

    def projection(self, *, identity=False):
        return {'schema_ref':projection(self.schema_ref,identity=identity),'value':self.value,
                'rendered_body_ref':projection(self.rendered_body_ref,identity=identity)}


@dataclass(frozen=True)
class MethodPayload:
    media_type: str
    schema_id: str
    content: MethodContent

    def __post_init__(self):
        validate_id(self.media_type)
        validate_id(self.schema_id)
        if type(self.content) is not MethodContent:
            raise ReferenceError('INVALID_METHOD_CONTENT')

    def projection(self):
        return {'media_type':self.media_type,'schema_id':self.schema_id,
                'content_kind':'method_content','inline_value':self.content.projection()}

    def content_bytes(self):
        return self.content.value_bytes


def _payload_identity(payload):
    if type(payload) is BlobPayload:
        return {'media_type':payload.media_type,'schema_id':payload.schema_id,
                'blob_ref':payload.blob_ref.identity_projection()}
    if type(payload) is MethodPayload:
        return {'media_type':payload.media_type,'schema_id':payload.schema_id,
                'content_kind':'method_content','inline_value':payload.content.projection(identity=True)}
    return payload.projection()


@dataclass(frozen=True)
class Artifact:
    scope: Scope
    artifact_id: str
    kind: str
    created_at: str
    head_revision_id: str | None = None
    version: int = 0

    def __post_init__(self):
        if type(self.scope) is not Scope:
            raise ReferenceError("INVALID_ARTIFACT")
        # Unknown stored kinds remain observable; repositories reject writes
        # unless the current application has a registered supported kind.
        validate_id(self.kind)
        validate_id(self.artifact_id)
        utc_instant(self.created_at)
        if self.head_revision_id is not None:
            validate_id(self.head_revision_id)
        if type(self.version) is not int or not 0 <= self.version <= (1 << 63) - 1:
            raise ReferenceError("INVALID_VERSION")


@dataclass(frozen=True)
class ArtifactRevision:
    scope: Scope
    artifact_id: str
    revision_id: str
    created_at: str
    created_by: ActorRef
    payload: InlinePayload | BlobPayload | MethodPayload
    parent_revision_refs: tuple[ArtifactRevisionRef, ...] = ()
    schema_version: int = 1
    sources: tuple[SourceRef, ...] = ()
    claims: tuple[Claim, ...] = ()
    evidence_links: tuple[EvidenceLink, ...] = ()
    method_refs: tuple[MethodRef, ...] = ()
    generation_origin: GenerationOrigin | None = None
    body_digest: Digest = field(init=False)
    digest: Digest = field(init=False)

    def __post_init__(self):
        if (type(self.scope) is not Scope or type(self.created_by) is not ActorRef
                or type(self.payload) not in {InlinePayload,BlobPayload,MethodPayload} or type(self.schema_version) is not int
                or self.schema_version not in {1,2} or type(self.parent_revision_refs) is not tuple):
            raise ReferenceError("INVALID_REVISION")
        if self.schema_version == 1 and (type(self.payload) is not InlinePayload or self.sources or self.claims
                or self.evidence_links or self.method_refs or self.generation_origin is not None):
            raise ReferenceError('INVALID_REVISION')
        for name,kind,key in [('sources',SourceRef,lambda x:x.source_id),
                              ('claims',Claim,lambda x:x.claim_id),
                              ('evidence_links',EvidenceLink,lambda x:canonical_bytes(projection(x,identity=True))),
                              ('method_refs',MethodRef,lambda x:canonical_bytes(asdict(x)))]:
            values=getattr(self,name)
            if type(values) is not tuple or len(values)>4096 or any(type(v) is not kind for v in values):
                raise ReferenceError('INVALID_REVISION')
            keys=[key(v) for v in values]
            if len(set(keys))!=len(keys):
                raise ReferenceError('DUPLICATE_PROVENANCE')
            object.__setattr__(self,name,tuple(v for _,v in sorted(zip(keys,values),key=lambda pair:pair[0])))
        if self.generation_origin is not None and type(self.generation_origin) is not GenerationOrigin:
            raise ReferenceError('INVALID_GENERATION_ORIGIN')
        sources={s.source_id:s for s in self.sources}
        claims={c.claim_id:c for c in self.claims}
        if any(link.claim_id not in claims or sources.get(link.source_ref.source_id)!=link.source_ref
               for link in self.evidence_links):
            raise ReferenceError('UNRESOLVED_EVIDENCE_LINK')
        if type(self.payload) is MethodPayload and self.payload.content.schema_ref.method_ref not in self.method_refs:
            raise ReferenceError('UNRESOLVED_METHOD_CONTENT')
        if type(self.payload) is not BlobPayload:
            checks = SelectorChecks()
            for claim in self.claims:
                checks.check(self.payload.content_bytes(), claim.selector, claim.statement_digest)
        validate_id(self.artifact_id)
        validate_id(self.revision_id)
        utc_instant(self.created_at)
        parents = self.parent_revision_refs
        if self.schema_version == 2 and len(parents) > 4096:
            raise ReferenceError("INVALID_PARENT")
        if any(type(p) is not ArtifactRevisionRef or (p.realm_id, p.project_id, p.artifact_id) !=
               (self.scope.realm_id, self.scope.project_id, self.artifact_id) or p.revision_id == self.revision_id
               for p in parents):
            raise ReferenceError("INVALID_PARENT")
        if len({p.revision_id for p in parents}) != len(parents):
            raise ReferenceError("DUPLICATE_PARENT")
        object.__setattr__(self, "parent_revision_refs", tuple(sorted(parents, key=lambda p: (p.revision_id, p.digest.hex))))
        object.__setattr__(self, "body_digest", record_digest("artifact-body", _payload_identity(self.payload)))
        object.__setattr__(self, "digest", record_digest("artifact-revision", self.hash_payload()))
        if len(canonical_bytes(self.projection())) > MAX_RECORD_BYTES:
            raise ReferenceError("REVISION_TOO_LARGE")

    def hash_payload(self):
        result = {"schema_version": self.schema_version, "realm_id": self.scope.realm_id,
                "project_id": self.scope.project_id, "artifact_id": self.artifact_id,
                "revision_id": self.revision_id, "created_at": self.created_at,
                "created_by": asdict(self.created_by), "payload": _payload_identity(self.payload),
                "body_digest": asdict(self.body_digest),
                "parent_revision_refs": [asdict(p) for p in self.parent_revision_refs]}
        if self.schema_version == 2:
            result.update({name:projection(getattr(self,name),identity=True)
                           for name in ('sources','claims','evidence_links','method_refs','generation_origin')})
        return result

    def projection(self):
        result = {**self.hash_payload(), "digest": asdict(self.digest), 'payload':self.payload.projection()}
        if self.schema_version == 2:
            result.update({name:projection(getattr(self,name))
                           for name in ('sources','claims','evidence_links','method_refs','generation_origin')})
        return result

    @property
    def ref(self):
        return ArtifactRevisionRef(self.scope.realm_id, self.scope.project_id,
                                   self.artifact_id, self.revision_id, self.digest)
