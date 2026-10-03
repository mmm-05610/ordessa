"""Typed surfaces for the runtime-preferences brand configuration adapters.

Authored in this line against the C2/C3 target shapes (facet
``assets.runtime-preferences``: the four run-level parameter groups
compaction / memory / shell / retry). The harness registry (C2) is the only
component that calls these through ``bridge``; the adapter modules are pure —
no HOME, no network, no spawn, no file writes, no secret content (boundary
gates in ``tests/``).

Evidence level of this package: **document-level** (E-doc), per dispatch
P-A: every compiled native key carries a citation into
``docs/design/harness-configuration/`` (fixed official snapshots,
2026-09-27) plus the two 2026-09-28 point upgrades (opencode config page,
qwen settings @ fixed commit). Per-key upgrades to pinned-source /
controlled-probe evidence are follow-up work; nothing here guesses.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class TargetHandle:
    """The authorized configuration target; ``scope`` distinguishes the
    instance-private configuration root from any project-local file (a
    project scope is never writable for run-level preferences: the harnesses
    inventories show project tiers are trust- or admin-gated per brand)."""

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
class PreferenceRequest:
    """One facet item value to assess/compile (payload
    ``runtime-preferences.item.v1``): the canonical parameter object for
    exactly one group. Values carry parameter data plus model/backend
    *references* (``summaryModelRef`` / ``extractionModelRef`` /
    ``proxyRef`` / ``envRefs``) — reference strings only, never secret
    content, never a memory-service provisioning request (AR-5 boundary)."""

    group: str  # 'compaction' | 'memory' | 'shell' | 'retry'
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Assessment:
    """``supported`` requires per-key document (or better) evidence in the
    catalog; ``unknown`` is the honest answer for an unrecognized version or
    an unpinned native surface; ``unsupported`` carries the refusal reason
    (including the model-provider boundary for request-level keys)."""

    verdict: str  # 'supported' | 'unsupported' | 'unknown'
    reason: str | None = None
    harness_id: str | None = None
    native_version: str | None = None


@dataclass(frozen=True)
class CompileIntent:
    """A typed field write (C3 ``SetField``): structured path segments,
    never a joined string; ``source_item`` carries the facet item that asked."""

    target_handle: TargetHandle
    field_path: tuple[str, ...]
    typed_value: Any
    source_item: str = "preferences"


@dataclass(frozen=True)
class IntentSet:
    """The single-owner compiled output for one item plus the reconfiguration
    declaration: how the change reaches the running harness, at the evidence
    level recorded in the catalog. ``unverified`` means the catalog's
    per-key apply mode is unknown at this evidence level — the package never
    claims hot-reload (R3 of sources-and-gaps); the consuming runtime must
    treat ``unverified`` as "plan a controlled restart", never as
    session-local."""

    facet_id: str
    contributor_version: str
    intents: tuple[Any, ...]
    reconfiguration: str  # 'session-local' | 'reload' | 'restart-resume' | 'unverified'
    apply_modes: tuple[tuple[str, str], ...] = ()  # (native path, apply mode) per compiled key
    resume_expectation: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class Refusal:
    """A typed compile refusal; codes come from the harness C6 vocabulary."""

    code: str  # 'capability-unsupported' | 'target-conflict' | 'invalid-request' | 'admin-only-key'
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Verdict:
    """``verify`` explains harness samples only; a projected file digest alone
    is never ``match`` — the read-back layer decides ``applied``."""

    verdict: str  # 'match' | 'mismatch' | 'unknown'
    reason: str | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)
