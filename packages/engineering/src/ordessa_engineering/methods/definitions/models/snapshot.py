"""Stored source bindings and snapshot views; properties perform no IO."""
from dataclasses import dataclass
from .identity import MethodIdentity, MethodRef, BlobRef
from .compiled import CompiledProgram, HistoricalBoundProgram, StoredProgram

@dataclass(frozen=True)
class ResourceSnapshot:
    resource_id: str
    logical_path: str
    blob_ref: BlobRef
    @property
    def media_type(self): return self.blob_ref.media_type
    @property
    def byte_length(self): return self.blob_ref.byte_length
    @property
    def digest(self): return self.blob_ref.digest

@dataclass(frozen=True)
class StoredSourceBundle:
    identity: MethodIdentity
    manifest_ref: BlobRef
    resources: tuple[ResourceSnapshot, ...]
    def __post_init__(self):
        if type(self.resources) is not tuple or any(type(r) is not ResourceSnapshot for r in self.resources):
            raise TypeError("immutable stored source index required")

@dataclass(frozen=True)
class StoredSnapshot:
    """Pure codec result: source bindings still require explicit store validation."""
    source_bundle: StoredSourceBundle
    program: StoredProgram
    snapshot_digest: str
    def __post_init__(self):
        if type(self.source_bundle) is not StoredSourceBundle:
            raise TypeError("stored source bindings required")
    @property
    def identity(self): return self.source_bundle.identity
    @property
    def manifest_ref(self): return self.source_bundle.manifest_ref
    @property
    def resources(self): return self.source_bundle.resources
    @property
    def engine_contract_version(self): return self.program.engine_contract_version
    @property
    def compiler_version(self): return self.program.compiler_version

@dataclass(frozen=True)
class MethodSnapshot:
    source_bundle: StoredSourceBundle
    program: CompiledProgram | HistoricalBoundProgram
    snapshot_digest: str
    def __post_init__(self):
        if type(self.source_bundle) is not StoredSourceBundle or type(self.program) not in (CompiledProgram, HistoricalBoundProgram):
            raise TypeError("materialized snapshot requires stored source and typed program")
        refs = {item.resource_id: item.digest for item in self.resources}
        for _, ref in self.program.bindings.standards + self.program.bindings.decisions:
            if refs.get(ref.resource_id) != ref.sha256:
                raise ValueError("program binding does not match stored source index")
    @property
    def identity(self): return self.source_bundle.identity
    @property
    def manifest_ref(self): return self.source_bundle.manifest_ref
    @property
    def resources(self): return self.source_bundle.resources
    @property
    def engine_contract_version(self): return self.program.engine_contract_version
    @property
    def compiler_version(self): return self.program.compiler_version
    @property
    def ref(self):
        i = self.identity
        return MethodRef(i.method_id, i.release_version, i.schema_version, self.snapshot_digest)

@dataclass(frozen=True)
class FreezeResult:
    snapshot: MethodSnapshot
    @property
    def ref(self): return self.snapshot.ref
