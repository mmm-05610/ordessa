"""NativeSandboxRepository — the Sandbox domain's own record store.

Data model (`data-model.md`): `NativeSandboxIntent` records are versioned by
``sandboxId + revision`` (a Profile may only ever reference that pair), and
`SandboxEvidence` is keyed by ``(targetHandle, runtimeGeneration)``. This is
the sandbox store — it holds no permissions data, and permissions data never
lives here.

Evidence invalidation: when the pin's version, the applied config digest or
the platform facts move, every receipt recorded against the old facts is
dropped; a query after invalidation cannot return a stale ``verified``.
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from ordessa_sandbox_api import (
    NativeSandboxIntent,
    PlatformFacts,
    SandboxApiError,
    SandboxErrorCode,
    SandboxEvidence,
    SessionSlot,
    ToolCategory,
)


@dataclass(frozen=True)
class TargetFacts:
    """The current pin facts a target handle is observed under."""

    native_version: str
    config_digest: str
    platform: PlatformFacts
    adapter_version: str = ""

    def drifted_from(self, other: "TargetFacts") -> tuple[str, ...]:
        moved: list[str] = []
        if self.native_version != other.native_version:
            moved.append("native_version")
        if self.config_digest != other.config_digest:
            moved.append("config_digest")
        if not self.platform.same_as(other.platform):
            moved.append("platform")
        if self.adapter_version != other.adapter_version:
            moved.append("adapter_version")
        return tuple(moved)


@dataclass(frozen=True)
class SandboxIntentReference:
    """What a Profile may store: the pair, nothing more."""

    sandbox_id: str
    revision: int


@dataclass(frozen=True)
class VerificationFacts:
    """The current pin/platform facts a verify is judged against (FR-06)."""

    target_handle: str
    server_instance_id: str
    session_id: str
    runtime_generation: str
    native_version: str
    config_digest: str
    platform_os: str
    platform_version: str = ""
    kernel_features: tuple[str, ...] = ()
    adapter_available: bool = True
    co_resident_sessions: tuple[SessionSlot, ...] = field(default_factory=tuple)

    def platform(self) -> PlatformFacts:
        return PlatformFacts(os_name=self.platform_os,
                             os_version=self.platform_version,
                             kernel_features=tuple(self.kernel_features))

    def target_facts(self) -> TargetFacts:
        return TargetFacts(native_version=self.native_version,
                           config_digest=self.config_digest,
                           platform=self.platform())


def _intent_to_mapping(intent: NativeSandboxIntent) -> dict:
    data = dataclasses.asdict(intent)
    data["network"] = str(intent.network)
    data["scope"] = str(intent.scope)
    data["covered_categories"] = sorted(str(c) for c in intent.covered_categories)
    data["required_coverage"] = sorted(str(c) for c in intent.required_coverage)
    data["read_scope"] = list(intent.read_scope)
    data["write_scope"] = list(intent.write_scope)
    data["declared_impact_set"] = list(intent.declared_impact_set)
    return data


def _evidence_to_mapping(ev: SandboxEvidence) -> dict:
    return {
        "server_instance_id": ev.server_instance_id,
        "session_id": ev.session_id,
        "runtime_generation": ev.runtime_generation,
        "harness_id": ev.harness_id,
        "native_version": ev.native_version,
        "adapter_version": ev.adapter_version,
        "config_digest": ev.config_digest,
        "platform": dataclasses.asdict(ev.platform),
        "observed_covered_categories": sorted(str(c) for c in ev.observed_covered_categories),
        "outcome": str(ev.outcome),
        "reason": ev.reason,
    }


def _evidence_from_mapping(data: Mapping) -> SandboxEvidence:
    from ordessa_sandbox_api import SandboxVerificationOutcome

    return SandboxEvidence(
        server_instance_id=data["server_instance_id"],
        session_id=data["session_id"],
        runtime_generation=data["runtime_generation"],
        harness_id=data["harness_id"],
        native_version=data["native_version"],
        adapter_version=data["adapter_version"],
        config_digest=data["config_digest"],
        platform=PlatformFacts(**data["platform"]),
        observed_covered_categories=frozenset(
            ToolCategory(c) for c in data["observed_covered_categories"]),
        outcome=SandboxVerificationOutcome(data["outcome"]),
        reason=data.get("reason", ""),
    )


class NativeSandboxRepository:
    """Persisted intent + evidence records with fact-change invalidation.

    Persistence is pluggable: the default is process-local; ``from_json_file``
    binds a single domain file (this sandbox store's own data — never a
    harness/permissions config file).
    """

    def __init__(self, *, path: Path | str | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._intents: dict[str, dict[int, NativeSandboxIntent]] = {}
        self._evidence: dict[tuple[str, str], SandboxEvidence] = {}
        self._facts: dict[str, TargetFacts] = {}
        if self._path is not None and self._path.exists():
            self._load(json.loads(self._path.read_text(encoding="utf-8")))

    @classmethod
    def from_json_file(cls, path: Path | str) -> "NativeSandboxRepository":
        return cls(path=path)

    # ---------------------------------------------------------- persistence

    def _snapshot(self) -> dict:
        return {
            "intents": [
                _intent_to_mapping(intent)
                for revisions in self._intents.values()
                for intent in revisions.values()],
            "evidence": [
                {"target_handle": handle, **_evidence_to_mapping(ev)}
                for (handle, _gen), ev in self._evidence.items()],
            "facts": {
                handle: dataclasses.asdict(facts)
                for handle, facts in self._facts.items()},
        }

    def _flush(self) -> None:
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._snapshot(), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8")

    def _load(self, data: Mapping) -> None:
        for raw in data.get("intents", ()):
            intent = NativeSandboxIntent.from_mapping(raw)
            self._intents.setdefault(intent.sandbox_id, {})[intent.revision] = intent
        for raw in data.get("evidence", ()):
            handle = str(raw.pop("target_handle"))
            evidence = _evidence_from_mapping(raw)
            self._evidence[(handle, evidence.runtime_generation)] = evidence
        for handle, raw in (data.get("facts") or {}).items():
            self._facts[handle] = TargetFacts(
                native_version=raw["native_version"],
                config_digest=raw["config_digest"],
                platform=PlatformFacts(**raw["platform"]),
                adapter_version=raw.get("adapter_version", ""))

    # --------------------------------------------------------------- intents

    def save_intent(self, intent: NativeSandboxIntent) -> None:
        revisions = self._intents.setdefault(intent.sandbox_id, {})
        current_max = max(revisions, default=0)
        if intent.revision <= current_max and revisions.get(intent.revision) is not None:
            if revisions[intent.revision] != intent:
                raise SandboxApiError(
                    SandboxErrorCode.SANDBOX_INTENT_INVALID,
                    f"revision {intent.revision} of {intent.sandbox_id!r} is "
                    "already stored with different content; history is not "
                    "rewritten",
                    suggestion="save the change as the next revision")
            return
        if intent.revision <= current_max:
            raise SandboxApiError(
                SandboxErrorCode.SANDBOX_INTENT_INVALID,
                f"refusing to store revision {intent.revision} while "
                f"revision {current_max} is the latest; intent records are "
                "append-only",
                suggestion="increment the revision")
        revisions[intent.revision] = intent
        self._flush()

    def get_intent(self, sandbox_id: str, revision: int) -> NativeSandboxIntent | None:
        return self._intents.get(sandbox_id, {}).get(revision)

    def latest(self, sandbox_id: str) -> NativeSandboxIntent | None:
        revisions = self._intents.get(sandbox_id)
        if not revisions:
            return None
        return revisions[max(revisions)]

    def reference(self, sandbox_id: str, revision: int) -> SandboxIntentReference:
        """The only handle a Profile may keep: id + revision, no config."""
        if self.get_intent(sandbox_id, revision) is None:
            raise SandboxApiError(
                SandboxErrorCode.SANDBOX_INTENT_INVALID,
                f"cannot reference ({sandbox_id!r}, revision {revision}): no "
                "such stored intent")
        return SandboxIntentReference(sandbox_id=sandbox_id, revision=revision)

    def resolve(self, ref: SandboxIntentReference) -> NativeSandboxIntent | None:
        return self.get_intent(ref.sandbox_id, ref.revision)

    # -------------------------------------------------------------- evidence

    def current_facts(self, target_handle: str) -> TargetFacts | None:
        return self._facts.get(target_handle)

    def record_evidence(self, target_handle: str, evidence: SandboxEvidence) -> None:
        facts = TargetFacts(
            native_version=evidence.native_version,
            config_digest=evidence.config_digest,
            platform=evidence.platform,
            adapter_version=evidence.adapter_version)
        standing = self._facts.get(target_handle)
        if standing is not None:
            moved = facts.drifted_from(standing)
            if moved:
                raise SandboxApiError(
                    SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN,
                    f"refusing to record evidence whose "
                    f"{list(moved)} differ from the current facts of target "
                    f"{target_handle!r}: it would misattribute a stale receipt",
                    suggestion="re-probe against the current facts")
        self._facts[target_handle] = facts
        self._evidence[(target_handle, evidence.runtime_generation)] = evidence
        self._flush()

    def update_facts(self, target_handle: str, facts: TargetFacts) -> tuple[str, ...]:
        """Record new pin facts; returns the moved fact names (empty = none).

        Any movement of version/config/platform (or adapter) invalidates —
        i.e. deletes — every evidence receipt recorded for the target.
        """
        old = self._facts.get(target_handle)
        moved = facts.drifted_from(old) if old is not None else ()
        self._facts[target_handle] = facts
        if moved:
            self.invalidate(target_handle, reason=f"facts moved: {list(moved)}")
        else:
            self._flush()
        return moved

    def get_evidence(self, target_handle: str,
                     runtime_generation: str) -> SandboxEvidence | None:
        return self._evidence.get((target_handle, runtime_generation))

    def invalidate(self, target_handle: str, *, reason: str = "") -> int:
        """Drop every receipt for a target (facts moved, adapter reloaded).

        Intents are separate records and always survive: invalidation is
        about *proof*, not about the user's declared intent.
        """
        keys = [key for key in self._evidence if key[0] == target_handle]
        for key in keys:
            del self._evidence[key]
        self._flush()
        return len(keys)
