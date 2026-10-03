"""Factories for T04 adapter tests: injected revisions/snapshots/provenance.

Everything is built in memory from data — no store, no files. Digests are the
real domain digests (``definition_digest``) so snapshot/compile bindings are
exercised for real.
"""
from dataclasses import dataclass, field, replace
from typing import Mapping, Optional

from backend.definition import (
    Literal,
    SecretRef,
    definition_digest,
    revision_model,
)
from backend.native_intents import (
    CredentialAttestation,
    InstanceConfigTarget,
    NativeObservation,
    ObservedServer,
    PROVENANCE_MODE,
    SessionOverrideTarget,
)
from backend.resolve import McpEffectiveSnapshot

CANARY = "PLAINTEXT-SECRET-CANARY-8f31b0"


@dataclass(frozen=True)
class FakeProfileSpec:
    """Duck-typed stand-in for the host ``ProfileSpec`` fields the adapters
    read (plugins/harness/src/ordessa_harness/registry/schema.py:31): we do
    not import host internals; the thin C2 adapter maps the real type."""

    mcp_target: Optional[str]
    mcp_key: Optional[str]
    slots: tuple = ("provider", "mcp", "skill")


@dataclass(frozen=True)
class FakeHarnessDecl:
    profile: object  # HarnessDefinition duck: adapters read .profile


def codex_spec(**over) -> FakeProfileSpec:
    base = dict(
        mcp_target="/runtime/home/.codex/config.toml",
        mcp_key="mcp_servers",
        slots=("provider", "permission", "instruction", "mcp", "skill", "hooks"),
    )
    base.update(over)
    return FakeProfileSpec(**base)


def claude_spec(**over) -> FakeProfileSpec:
    base = dict(
        mcp_target="/runtime/home/.claude/.claude.json",
        mcp_key="mcpServers",
        slots=("provider", "instruction", "mcp", "skill", "hooks"),
    )
    base.update(over)
    return FakeProfileSpec(**base)


def pi_like_spec(**over) -> FakeProfileSpec:
    base = dict(mcp_target=None, mcp_key=None, slots=("instruction", "mcp", "skill"))
    base.update(over)
    return FakeProfileSpec(**base)


def stdio_revision(definition_id, revision, name, command, args=(), env=()):
    canonical = {
        "name": name,
        "transport": {"stdio": {
            "command": command,
            "args": list(args),
            "env": {k: _wire(v) for k, v in dict(env).items()},
        }},
    }
    return revision_model(
        definition_id=definition_id, revision=revision, canonical=canonical,
        canonical_digest=definition_digest(canonical), shape="v2",
        source=None, created_at="2026-09-28T00:00:00Z", approval=None)


def remote_revision(definition_id, revision, name, url, headers=()):
    canonical = {
        "name": name,
        "transport": {"remote": {
            "url": url,
            "headers": {k: _wire(v) for k, v in dict(headers).items()},
        }},
    }
    return revision_model(
        definition_id=definition_id, revision=revision, canonical=canonical,
        canonical_digest=definition_digest(canonical), shape="v2",
        source=None, created_at="2026-09-28T00:00:00Z", approval=None)


def _wire(value):
    if isinstance(value, SecretRef):
        return {"secretRef": value.credential_id}
    if isinstance(value, Literal):
        return {"literal": value.value}
    raise AssertionError(f"test values must be typed: {value!r}")


def revision_provider(revisions):
    """Injected reader over an in-memory {(id, rev): McpRevision} map."""
    table = dict(revisions)

    def provide(definition_id, revision):
        return table[(definition_id, revision)]

    return provide


def build_snapshot(revisions, lanes, allowed=(), session_ref="session-a",
                   generation=3, project_id="proj-1"):
    """Same construction path ``backend/resolve.py`` guarantees: entries carry
    the real canonical digest and the snapshot digest covers the content."""
    definition_entries = tuple({
        "definition_id": rev.definition_id, "revision": rev.revision,
        "canonical_digest": rev.canonical_digest, "canonical_shape": "v2",
    } for rev in sorted(revisions, key=lambda r: r.definition_id))
    snapshot = McpEffectiveSnapshot(
        target_session=session_ref, runtime_generation=generation,
        project_id=project_id, profile_revision=None,
        definition_revisions=definition_entries, assignment_revisions=(),
        credential_ref_revisions=(), allowed_tool_names=tuple(sorted(allowed)),
        lane_by_definition=dict(lanes), needs_revalidation=(), snapshot_digest="")
    digest = definition_digest(snapshot.content_for_digest())
    return replace(snapshot, snapshot_digest=digest)


class DictProvenance:
    """credential id -> attestation map (the valid shape)."""

    def __init__(self, attestations: Mapping[str, CredentialAttestation]):
        self._attestations = dict(attestations)

    def attest(self, credential_id: str) -> Optional[CredentialAttestation]:
        return self._attestations.get(credential_id)


class FakeHostSecretService:
    """Adversarial stand-in for the credential layer: it *can* produce the
    plaintext at the authorised instant (backend/secret.py CredentialPort
    semantics). The provenance adapter over it keeps only the revision —
    tests assert the canary can never reach an intent."""

    plaintext = CANARY

    def read(self, credential_id: str):
        return (self.plaintext, f"rev-{credential_id}")


def provenance_over_host_service(service: FakeHostSecretService, credential_ids):
    return DictProvenance({
        cid: CredentialAttestation(
            mode=PROVENANCE_MODE, resolver="harness",
            # revision identity only; the plaintext is read for the launch
            # instant and deliberately discarded before planning
            credential_revision=service.read(cid)[1])
        for cid in credential_ids
    })


def attestation(cid, resolver="harness", mode=PROVENANCE_MODE):
    return CredentialAttestation(mode=mode, resolver=resolver,
                                 credential_revision=f"rev-{cid}")


def observation(session_ref="session-a", generation=3, servers=(),
                observer="fake-harness-c3"):
    return NativeObservation(observer=observer, session_ref=session_ref,
                             runtime_generation=generation, servers=tuple(servers))


def observed(name, transport="stdio", load_state="runtime-loaded",
             catalog_digest=None, tool_names=()):
    return ObservedServer(server_name=name, transport=transport,
                          load_state=load_state, catalog_digest=catalog_digest,
                          tool_names=tuple(tool_names))


def instance_target(brand="claude"):
    if brand == "claude":
        return InstanceConfigTarget(target_path="/runtime/home/.claude/.claude.json",
                                    config_key="mcpServers", config_format="json")
    return InstanceConfigTarget(target_path="/runtime/home/.codex/config.toml",
                                config_key="mcp_servers", config_format="toml")


def session_target(brand="codex"):
    if brand == "claude":
        return SessionOverrideTarget(config_key="mcpServers", config_format="json")
    return SessionOverrideTarget(config_key="mcp_servers", config_format="toml")
