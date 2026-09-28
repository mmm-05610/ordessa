"""Typed surfaces for the model-provider brand configuration adapters.

Authored in this line against the C2/C3 target shapes
(``docs/design/harness-v2/contracts.md``). The harness registry (C0) is the
only component that calls these; the adapter modules are pure - no HOME, no
network, no spawn, no file writes, no secret content (dispatch t02, boundary
gates in ``tests/``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class TargetHandle:
    """The authorized configuration target; ``scope`` distinguishes the
    instance-private configuration root from any project-local file (a project
    scope is never writable for provider keys)."""

    harness_id: str
    scope: str  # 'instance' | 'project'
    identity: str


@dataclass(frozen=True)
class AdapterContext:
    """What the harness hands the adapter: authorized handle, non-secret
    capability facts and versions. Nothing here is read from the user HOME."""

    target_handle: TargetHandle
    harness_version: str | None
    capabilities: Mapping[str, Any] = field(default_factory=dict)
    generation: str | None = None


@dataclass(frozen=True)
class ChoiceRequest:
    """One Provider/Model selection to assess/compile (facet
    ``assets.model-provider`` payload schema v1). ``credential_ref`` is a
    secret *reference*; content never travels here."""

    provider_config_id: str
    model_id: str
    endpoint: str | None
    protocol: str
    credential_ref: str | None
    provider_name: str
    brand_fields: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Assessment:
    """``supported`` requires pin-level evidence; ``unknown`` is the honest
    answer for an unrecognized version or undeclared capability."""

    verdict: str  # 'supported' | 'unsupported' | 'unknown'
    reason: str | None = None
    harness_id: str | None = None
    native_version: str | None = None


@dataclass(frozen=True)
class CompileIntent:
    """A typed field write (C3 ``SetField``): structured path segments, never
    a joined string; ``source_item`` carries the facet item that asked."""

    target_handle: TargetHandle
    field_path: tuple[str, ...]
    typed_value: Any
    source_item: str = "choice"


@dataclass(frozen=True)
class BindSecret:
    """C3 ``BindSecret``: the slot is bound to a reference; the backend
    resolves content only at apply time. A value here is a boundary violation
    (scanned by tests)."""

    target_handle: TargetHandle
    slot: str
    secret_ref: str


@dataclass(frozen=True)
class MountContent:
    """C3 ``MountContent``: named content inside the instance root with a
    digest - never an arbitrary absolute path."""

    target_handle: TargetHandle
    relative_name: str
    content_ref: str
    digest: str
    mode: str = "replace-owned"


@dataclass(frozen=True)
class IntentSet:
    """The single-owner compiled output for one facet item plus the C2
    reconfiguration declaration: how the change reaches the session."""

    facet_id: str
    contributor_version: str
    intents: tuple[Any, ...]
    reconfiguration: str  # 'session-local' | 'reload' | 'restart-resume'
    #: what continuity must be proven after a controlled restart
    resume_expectation: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class Refusal:
    """A typed compile refusal; codes come from the harness C6 vocabulary."""

    code: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Verdict:
    """``verify`` explains harness samples only; a projected file digest alone
    is never ``match`` - the read-back layer decides ``applied``."""

    verdict: str  # 'match' | 'mismatch' | 'unknown'
    reason: str | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)
