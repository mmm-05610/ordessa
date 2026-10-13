"""Loaded stage: location, one source capture, optional verification evidence."""
from dataclasses import dataclass
from .sources import MethodSource, SourceBundle, ParsedSourceBundle
from .verification import VerificationInputs

@dataclass(frozen=True)
class LoadedMethod:
    source: MethodSource
    source_bundle: SourceBundle
    parsed_source: ParsedSourceBundle
    verification: VerificationInputs | None = None
    def __post_init__(self):
        if type(self.parsed_source) is not ParsedSourceBundle or self.parsed_source.source_bundle is not self.source_bundle:
            raise ValueError("loaded parsed view must bind the same source bundle")
    @property
    def identity(self): return self.parsed_source.identity
    @property
    def manifest(self): return self.parsed_source.manifest
    @property
    def manifest_bytes(self): return self.source_bundle.manifest_bytes
    @property
    def manifest_digest(self): return self.source_bundle.manifest_digest
    @property
    def resources(self): return self.parsed_source.resource_views
    @property
    def load_limits(self): return self.source_bundle.limits
    @property
    def bundle_lock(self): return self.verification.lock if self.verification else None
    @property
    def compiled_golden(self): return self.verification.golden if self.verification else None
    @property
    def bundle_lock_bytes(self):
        return self.verification.bundle_lock.captured.data if self.verification and self.verification.bundle_lock else None
    @property
    def compiled_golden_bytes(self):
        return self.verification.compiled_golden.captured.data if self.verification and self.verification.compiled_golden else None
