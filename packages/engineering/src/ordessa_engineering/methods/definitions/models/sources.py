"""Captured byte data and immutable derived views; no parsing or IO."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping
from hashlib import sha256
from .identity import MethodIdentity

def _freeze_view(value):
    if type(value) in (dict, MappingProxyType):
        if any(type(k) is not str for k in value): raise TypeError("parsed mapping keys must be strings")
        return MappingProxyType({k: _freeze_view(v) for k, v in value.items()})
    if type(value) in (list, tuple): return tuple(_freeze_view(v) for v in value)
    if value is None or type(value) in (str, bool, int): return value
    raise TypeError("immutable JSON-compatible parsed value required")


def _copy_view(value):
    if isinstance(value, Mapping): return {k: _copy_view(v) for k, v in value.items()}
    if type(value) is tuple: return [_copy_view(v) for v in value]
    return value


@dataclass(frozen=True)
class MethodSource:
    root: Path
    manifest_path: str = "method.yaml"

@dataclass(frozen=True)
class LoadLimits:
    manifest_bytes: int = 256 * 1024
    resource_bytes: int = 2 * 1024 * 1024
    total_resources: int = 128
    total_bytes: int = 16 * 1024 * 1024
    structure_depth: int = 64
    workflow_steps: int = 64
    question_count: int = 128

@dataclass(frozen=True)
class ResourceBytes:
    logical_path: str
    media_type: str
    data: bytes

    def __post_init__(self):
        if type(self.data) is not bytes:
            raise TypeError("capture requires immutable bytes")

    @property
    def digest(self):
        return sha256(self.data).hexdigest()

    @property
    def byte_length(self):
        return len(self.data)

    def __deepcopy__(self, memo): return self

@dataclass(frozen=True)
class CapturedResource:
    resource_id: str
    captured: ResourceBytes
    def __post_init__(self):
        if type(self.resource_id) is not str or type(self.captured) is not ResourceBytes:
            raise TypeError("typed captured resource required")

@dataclass(frozen=True)
class SourceBundle:
    manifest_capture: ResourceBytes
    resources: tuple[CapturedResource, ...]
    limits: LoadLimits = field(default_factory=LoadLimits)

    def __post_init__(self):
        if type(self.manifest_capture) is not ResourceBytes or type(self.limits) is not LoadLimits:
            raise TypeError("typed captured manifest and limits required")
        if type(self.resources) is not tuple or any(type(item) is not CapturedResource for item in self.resources):
            raise TypeError("source resources must be immutable captures")
        ids = [item.resource_id for item in self.resources]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate captured resource identity")

    @property
    def manifest_bytes(self): return self.manifest_capture.data
    @property
    def manifest_digest(self): return self.manifest_capture.digest
    def __deepcopy__(self, memo): return self

@dataclass(frozen=True)
class ParsedContent:
    """Immutable derived value bound to a capture; never proof of correct parsing."""
    captured: ResourceBytes
    value_tree: Any
    def __post_init__(self):
        if type(self.captured) is not ResourceBytes: raise TypeError("captured bytes required")
        object.__setattr__(self, "value_tree", _freeze_view(self.value_tree))
    @property
    def value(self): return _copy_view(self.value_tree)
    def __deepcopy__(self, memo): return self


@dataclass(frozen=True)
class ParsedResource:
    resource_id: str
    content: ParsedContent
    def __post_init__(self):
        if type(self.resource_id) is not str or type(self.content) is not ParsedContent:
            raise TypeError("typed parsed resource binding required")


@dataclass(frozen=True)
class ParsedSourceBundle:
    source_bundle: SourceBundle
    manifest_content: ParsedContent
    resources: tuple[ParsedResource, ...]
    def __post_init__(self):
        if type(self.source_bundle) is not SourceBundle or type(self.manifest_content) is not ParsedContent:
            raise TypeError("source and parsed manifest required")
        if self.manifest_content.captured != self.source_bundle.manifest_capture:
            raise ValueError("parsed manifest capture binding mismatch")
        if type(self.resources) is not tuple or any(type(r) is not ParsedResource for r in self.resources):
            raise TypeError("immutable parsed resources required")
        captured = {r.resource_id:r.captured for r in self.source_bundle.resources}
        if len(self.resources)!=len(captured) or {r.resource_id for r in self.resources}!=set(captured):
            raise ValueError("parsed resource set mismatch")
        if any(r.content.captured!=captured[r.resource_id] for r in self.resources):
            raise ValueError("parsed resource capture binding mismatch")
    @property
    def manifest(self): return self.manifest_content.value
    @property
    def identity(self):
        v = self.manifest_content.value_tree
        return MethodIdentity(v["method_id"],v["release_version"],v["schema_version"])
    @property
    def resource_views(self):
        return MappingProxyType({r.resource_id:SourceResourceView(self,r.resource_id) for r in self.resources})
    def __deepcopy__(self, memo): return self


@dataclass(frozen=True)
class SourceResourceView:
    bundle: ParsedSourceBundle
    resource_id: str
    @property
    def content(self): return next(r.content for r in self.bundle.resources if r.resource_id==self.resource_id)
    @property
    def captured(self): return self.content.captured
    @property
    def declaration(self):
        return _copy_view(next(v for v in self.bundle.manifest_content.value_tree["resources"] if v["id"]==self.resource_id))
    @property
    def value(self): return self.content.value

JsonObject = Mapping[str, Any]
JsonValue = Any
