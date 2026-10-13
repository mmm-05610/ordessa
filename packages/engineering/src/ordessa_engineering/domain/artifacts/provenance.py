"""Captured artifact provenance; local values do not attest semantic support."""
from dataclasses import dataclass, field, fields
import re
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.selection import ContentSelector, MAX_CONTENT_BYTES
from ordessa_engineering.domain.common.models.values import Digest, UtcInstant, validate_id, utc_instant, normalized_path
from ordessa_engineering.domain.common.models.identity import ActorRef
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from .refs import ArtifactRevisionRef

@dataclass(frozen=True)
class SourceLocator:
    kind: str
    provider: str | None = None
    conversation_id: str | None = None
    message_id: str | None = None
    repository_id: str | None = None
    path: str | None = None
    document_id: str | None = None
    artifact_ref: ArtifactRevisionRef | None = None
    observation_id: str | None = None

    def __post_init__(self):
        allowed = {'chat_message': {'provider','conversation_id','message_id'},
            'agents_file': {'repository_id','path'}, 'code': {'repository_id','path'},
            'document': {'provider','document_id'}, 'artifact': {'artifact_ref'},
            'tool_observation': {'provider','observation_id'}}
        if type(self.kind) is not str or self.kind not in allowed:
            raise ReferenceError('INVALID_SOURCE_LOCATOR')
        present = {f.name for f in fields(self) if f.name != 'kind' and getattr(self,f.name) is not None}
        if present != allowed[self.kind]:
            raise ReferenceError('INVALID_SOURCE_LOCATOR')
        for name in present:
            if name == 'artifact_ref':
                if type(self.artifact_ref) is not ArtifactRevisionRef:
                    raise ReferenceError('INVALID_SOURCE_LOCATOR')
            elif name == 'path':
                normalized_path(self.path)
            else:
                validate_id(getattr(self,name))


@dataclass(frozen=True)
class VersionCapture:
    upstream_version: str
    content_digest: Digest
    kind: str = field(default='immutable_version', init=False)

    def __post_init__(self):
        validate_id(self.upstream_version)
        if type(self.content_digest) is not Digest:
            raise ReferenceError('INVALID_SOURCE_CAPTURE')


@dataclass(frozen=True)
class ExcerptCapture:
    blob_ref: BlobRef
    excerpt_digest: Digest
    selector: ContentSelector
    upstream_version: str | None = None
    kind: str = field(default='immutable_excerpt', init=False)

    def __post_init__(self):
        if (type(self.blob_ref) is not BlobRef or type(self.excerpt_digest) is not Digest
                or type(self.selector) is not ContentSelector):
            raise ReferenceError('INVALID_SOURCE_CAPTURE')
        if self.upstream_version is not None:
            validate_id(self.upstream_version)


@dataclass(frozen=True)
class SourceRef:
    source_id: str
    kind: str
    locator: SourceLocator
    capture: VersionCapture | ExcerptCapture
    captured_at: UtcInstant
    captured_by: ActorRef
    media_type: str
    byte_length: int
    original_url: str | None = None

    def __post_init__(self):
        validate_id(self.source_id)
        validate_id(self.media_type)
        if len(self.media_type) > 256:
            raise ReferenceError("INVALID_SOURCE")
        utc_instant(self.captured_at)
        if (type(self.locator) is not SourceLocator or self.kind != self.locator.kind
                or type(self.capture) not in {VersionCapture,ExcerptCapture}
                or type(self.captured_by) is not ActorRef or type(self.byte_length) is not int
                or not 0 <= self.byte_length <= MAX_CONTENT_BYTES):
            raise ReferenceError('INVALID_SOURCE')
        if type(self.capture) is ExcerptCapture and (self.byte_length != self.capture.blob_ref.byte_length
                or self.media_type != self.capture.blob_ref.media_type):
            raise ReferenceError('INVALID_SOURCE')
        if self.original_url is not None:
            validate_id(self.original_url)
            if not re.fullmatch(r'https?://[^/@\s?#]+(?:[/?#][^\s]*)?', self.original_url):
                raise ReferenceError('INVALID_SOURCE_URL')


@dataclass(frozen=True)
class Claim:
    claim_id: str
    selector: ContentSelector
    statement_digest: Digest

    def __post_init__(self):
        validate_id(self.claim_id)
        if type(self.selector) is not ContentSelector or type(self.statement_digest) is not Digest:
            raise ReferenceError('INVALID_CLAIM')


@dataclass(frozen=True)
class ClaimRef:
    owner_revision_ref: ArtifactRevisionRef
    claim_id: str
    statement_digest: Digest

    def __post_init__(self):
        validate_id(self.claim_id)
        if type(self.owner_revision_ref) is not ArtifactRevisionRef or type(self.statement_digest) is not Digest:
            raise ReferenceError('INVALID_CLAIM')


@dataclass(frozen=True)
class EvidenceLink:
    claim_id: str
    source_ref: SourceRef
    source_selector: ContentSelector
    relation: str
    rationale: str

    def __post_init__(self):
        validate_id(self.claim_id)
        if (type(self.source_ref) is not SourceRef or type(self.source_selector) is not ContentSelector
                or type(self.relation) is not str or self.relation not in {'supports','contradicts','context'}
                or type(self.rationale) is not str or not self.rationale or len(self.rationale)>16384
                or '\x00' in self.rationale):
            raise ReferenceError('INVALID_EVIDENCE_LINK')


@dataclass(frozen=True)
class GenerationOrigin:
    provider: str
    trace_id: str | None
    execution_id: str | None
    generator_version: str

    def __post_init__(self):
        validate_id(self.provider)
        validate_id(self.generator_version)
        if self.trace_id is None and self.execution_id is None:
            raise ReferenceError('INVALID_GENERATION_ORIGIN')
        for value in (self.trace_id,self.execution_id):
            if value is not None:
                validate_id(value)
