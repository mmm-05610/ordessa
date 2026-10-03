"""Claude Code configuration adapter triad (G11, G13), on the published contract.

Pin: `@agentclientprotocol/claude-agent-acp@0.81.2` — the key tables and the
assessment below are *versioned per that pin* (capability-matrix.md §Claude,
rows C-1…C-7), now expressed with the contract's own `VersionRange` /
`FieldClaim` / `Assessment` shapes. The pinned artifact exposes a subagent
surface (rebuild-class `agents`/`settingSources` options, a control tool,
spawn events), but Ordessa's own channel passes none of it (api-requests.md
SR-3b), so every runtime cell at this pin is assessed **unknown** — never
`supported`.

`compile` emits only real `MountContent` intents into the host-issued
private-generation directory target, under a host-injected `IntentSource`;
user/project `.claude` paths are not expressible targets at all (the target
is a server `TargetHandle`, and Q3's token grammar additionally refuses
`~`/path/shell shapes). The old `SetRebuildClassOption` intent has NO
counterpart in the published vocabulary — `agents`/`settingSources` are
rebuild-class at this pin (C-6), so an in-place option intent is not
emissible and :func:`rebuild_class_option` stays a typed refusal naming
SR-3b-2 (per the seam rule: refuse, test, report; no private side channel).
Fields the plugin-scope entry may silently ignore (`permissionMode`,
`mcpServers`, `hooks`, …) are **refused**, never recorded as protected
capabilities (§C3) and never dropped silently.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

from ordessa_harness_api import (
    ConfigurationAdapterDescriptor, FieldClaim, IntentSet, ValueSchema,
    VersionRange,
)

from .. import errors, limits
from . import base, frontmatter, intents

CLAUDE_HARNESS_ID = "claude"
CLAUDE_ADAPTER_PIN = "@agentclientprotocol/claude-agent-acp@0.81.2"
#: The contract's version-typed view of the same pin (registration shape).
CLAUDE_ADAPTER_SEMVER = (0, 81, 2)
#: Canonical target-handle id this facet's descriptor claims. The host must
#: issue this handle id in the AdapterContext for the directory claim to match
#: (`configuration_service._has_claim` compares claim.target_id to
#: intent.target.handle_id); Q3 never derives it from a path. Deliberately
#: separator-free and without the `.` brand spellings: a handle id is a
#: logical token, never anything that could read as a native location (G13).
CLAUDE_GENERATION_HANDLE = "assets-native-subagents-claude-generation"

#: Filename == agent name (harness-adapters.md §格式映射 / C pin rules):
#: lowercase-first slug, at most 64 chars — the same grammar `limits.MAX_SLUG_CHARS`
#: bounds on the definition side.
CLAUDE_AGENT_NAME_RE = re.compile(r"\A" + intents.NATIVE_NAME_PATTERN + r"\Z")

#: Built-in names a managed generation must not shadow (G13). The table is
#: intentionally minimal: only what the pin's behaviour registers; the
#: collision check runs regardless.
CLAUDE_RESERVED_NAMES = frozenset({"general-purpose"})

#: The option keys classified rebuild-class at this pin (C-6). An option that
#: is not on this list could never be emitted even if the gap were closed.
CLAUDE_REBUILD_CLASS_OPTIONS = frozenset({"agents", "setting_sources"})

_EVIDENCE_ARTIFACT = (
    "capability-matrix.md §Claude C-1…C-7 (L2-static over the version-matched "
    "0.81.2 artifact, evidence root /home/maoqh/ordessa-evidence/q3/claude-pkg)",
    "api-requests.md SR-3b items 1–4: the Ordessa-side pass-through is "
    "grep-verified absent in plugins/harness/src/ordessa_harness/claude/*.py and "
    "plugins/harness/adapters/acp-adapter/internal/",
)


@dataclass(frozen=True)
class ClaudeKey:
    """One registered frontmatter/config key at this pin (NativeKey shape)."""

    key: str
    classification: str          # supported | rejected
    declaration_only: bool
    reason: str                  # why, citing the pin evidence
    evidence: str


#: What this adapter will write into a managed Claude document.
CLAUDE_SUPPORTED_KEYS: tuple[ClaudeKey, ...] = (
    ClaudeKey("name", "supported", False,
              "filename == agent name; the entry the loader discovers (C-5 settingSources live)",
              "capability-matrix C-5, harness-adapters §格式映射"),
    ClaudeKey("description", "supported", False,
              "catalog line; aggregate-capped (C-2 subagentDisplayName/Description plumbing)",
              "capability-matrix C-2 + row 'short description'"),
    ClaudeKey("model", "supported", True,
              "a REFERENCE declaration only; honouring unproven at the pin (U) — never "
              "reported as applied",
              "capability-matrix row 'model reference': U, declaration only"),
    ClaudeKey("tools", "supported", True,
              "a REFERENCE declaration only; ceiling authority is SR-6, so no runtime claim",
              "capability-matrix row 'tool allowlist': U, declaration only"),
)

#: Fields Q3 refuses outright at this pin — the plugin-scope entry may ignore
#: them, so they may not be carried as protected capabilities (§C3), and they
#: are refused rather than silently dropped.
CLAUDE_REJECTED_KEYS: tuple[ClaudeKey, ...] = (
    ClaudeKey("permissionMode", "rejected", False,
              "approval behaviour a definition must not self-grant; upstream ignores it "
              "for plugin-scope agents (matrix: R — refused, not silently narrowed, FR06)",
              "capability-matrix row 'permissionMode' + harness-adapters §格式映射"),
    ClaudeKey("mcpServers", "rejected", False,
              "a definition may not inject its own MCP servers (matrix: R)",
              "capability-matrix row 'mcpServers injection'"),
    ClaudeKey("hooks", "rejected", False,
              "executing definition-supplied hooks is an execution host the definitions "
              "plugin must not ship (matrix: R; §C3)",
              "capability-matrix row 'hooks'"),
)

#: Policy for any key that is in neither table (and for `skills`/`isolation`,
#: whose entry at this pin is unproven): refuse at compile and name the key —
#: never approximate, never drop, never claim.
CLAUDE_UNKNOWN_BEHAVIOUR = (
    "unknown-behaviour keys are refused before any intent exists: a field whose "
    "effect at this pin is unknown may not be compiled and may not be silently "
    "dropped (contracts.md §C3, §C5)"
)

_SUPPORTED_BY_NAME = {entry.key: entry for entry in CLAUDE_SUPPORTED_KEYS}
_REJECTED_BY_NAME = {entry.key: entry for entry in CLAUDE_REJECTED_KEYS}

#: Provisional facet payload shape (T12 wiring will confirm it with C0): the
#: per-item fragment names the definition ids whose revisions are supplied
#: to `compile` as the managed collection.
CLAUDE_PAYLOAD_SCHEMA = ValueSchema(
    "object",
    properties=(("definitions", ValueSchema("array", items=ValueSchema("string"))),),
    required=("definitions",),
)


def validate_agent_name(name: Any, *, item_id: str | None = None) -> str:
    """Filename == agent name: `[a-z0-9][a-z0-9._-]{0,63}`, not reserved."""
    if not isinstance(name, str) or CLAUDE_AGENT_NAME_RE.fullmatch(name) is None:
        raise errors.DomainError(
            errors.DEFINITION_INVALID, item_id=item_id,
            detail=(f"agent name {name!r} must match {intents.NATIVE_NAME_PATTERN} "
                    "(filename == agent name at this pin)"),
        )
    if name in CLAUDE_RESERVED_NAMES:
        raise errors.DomainError(
            errors.NATIVE_NAME_CONFLICT, item_id=name,
            detail=f"{name!r} is a reserved built-in agent name at this pin (G13)",
        )
    return name


class ClaudeAdapter(base.ConfigurationAdapter):
    """Pure triad for the pinned Claude ACP adapter."""

    adapter_id = "ordessa.assets.native-subagents.claude"
    harness_id = CLAUDE_HARNESS_ID
    pinned_version = CLAUDE_ADAPTER_PIN
    mount_suffix = ".md"

    descriptor = ConfigurationAdapterDescriptor(
        adapter_id, "v1", intents.FACET_ID, "v1", CLAUDE_HARNESS_ID,
        # Claude's native CLI is not pinned on this host (matrix: CLI ABSENT),
        # so the native range gates nothing; the ADAPTER version is pinned
        # exactly and is what `_validate_context` enforces (G01).
        VersionRange((0, 0, 0)),
        VersionRange(CLAUDE_ADAPTER_SEMVER, CLAUDE_ADAPTER_SEMVER),
        ("acp",),
        CLAUDE_PAYLOAD_SCHEMA,
        (
            # The complete managed set mounts under this one directory claim;
            # `("agents",)` is the leading segment of every emitted
            # relative_name (SR-1b(a): one MountContent per item + the
            # shared claim prefix).
            FieldClaim("directory", CLAUDE_GENERATION_HANDLE, ("agents",)),
        ),
    )

    # -- assess --------------------------------------------------------------
    def assess_detail(self, context: Any, request: Any = None) -> base.Assessment:
        """Every runtime cell is `unknown` at this pin — the adapter-side
        surface exists (C-1…C-7) but the Ordessa-side channel is absent
        (SR-3b), so nothing may be claimed `supported` (G01/G11). `assess()`
        maps this record onto the real `Assessment` DTO."""
        self._validate_context(context)

        def cell(name: str, reason: str) -> base.CellVerdict:
            return base.CellVerdict(cell=name, state=base.AssessmentState.UNKNOWN,
                                    reason=f"{reason} [pin {CLAUDE_ADAPTER_PIN}]",
                                    evidence=_EVIDENCE_ARTIFACT)

        cells = (
            cell("format",
                 "frontmatter-over-markdown is the documented entry and the "
                 "settingSources layer is live in the artifact (C-5), but no L2-exec "
                 "loader probe exists (claude CLI ABSENT), so honouring is unmeasured"),
            cell("private_generation_discovery",
                 "whether a Harness-owned private root is equivalent to user/project "
                 "scope is unmeasured at this pin (harness-adapters §格式映射)"),
            cell("reload",
                 "C-6: agents/settingSources are rebuild-class options — no in-place "
                 "hot update exists at this pin; 'next submission' means rebuild or "
                 "proved reload, and neither channel is wired Ordessa-side"),
            cell("invocation",
                 "C-1/C-4 show a control tool and nativeSubagentSessions capability in "
                 "the artifact, but Ordessa declares/negotiates neither (SR-3b-1), so "
                 "invokable stays unknown"),
            cell("resume",
                 "C-1 advertises session resume in the artifact; the same-native-session "
                 "resume path is unproven through Ordessa (SR-2)"),
            cell("isolation",
                 "C-3: per-session NativeSubagentRuntime keyed by sessionId exists in "
                 "the artifact; A/B isolation through Ordessa is unproven"),
            cell("ceiling_independence",
                 "C-7: managed policy resolves with settingSources=[] — structural "
                 "backing only; apply-time re-adjudication needs SR-6 (absent)"),
        )
        return base.Assessment(
            state=base.AssessmentState.UNKNOWN,
            pinned_version=CLAUDE_ADAPTER_PIN,
            evidence=_EVIDENCE_ARTIFACT,
            reasons=(
                "adapter-side surface exists at the pin (C-1…C-7) while the "
                "Ordessa-side channel is absent (SR-3/SR-3b): assessment is "
                "unknown, never supported (G01 negative column)",
                CLAUDE_UNKNOWN_BEHAVIOUR,
            ),
            cells=cells,
        )

    # -- compile -------------------------------------------------------------
    def compile(self, context: Any, collection: Sequence[intents.ManagedItem],
                source: Any, *, native_names: frozenset[str] | None = None,
                stage_content: Any = None,
                secret_bindings: Sequence[tuple[str, str]] = ()) -> IntentSet:
        """Compile the *complete* managed collection into real `MountContent`
        intents aimed at the host-issued private-generation directory target,
        under the host-injected `IntentSource`. Refusals come first: no
        intent object exists when anything in the collection is refused."""
        checked = self._validate_context(context)
        intents.validate_source(source)
        items = tuple(collection)
        for item in items:
            self._check_fields(item)
        return intents.compile_all(
            items, checked, source, render=self._render_document,
            suffix=self.mount_suffix, native_names=native_names,
            stage_content=stage_content, secret_bindings=secret_bindings,
        )

    def _check_fields(self, item: intents.ManagedItem) -> None:
        """Refuse every field whose effect the pin may silently ignore, and
        every reference kind without a proven entry — item-level, before any
        intent (FR06/§C3: never silently narrowed, never silently dropped)."""
        item_id = item.definition.definition_id
        revision = item.revision
        if revision.requested_permission is not None:
            rejected = _REJECTED_BY_NAME["permissionMode"]
            raise errors.DomainError(
                errors.PERMISSION_EXCEEDS_CEILING, item_id=item_id,
                detail=f"field permissionMode/requested_permission on {item_id}: {rejected.reason}",
            )
        if revision.mcp_refs:
            rejected = _REJECTED_BY_NAME["mcpServers"]
            raise errors.DomainError(
                errors.PERMISSION_EXCEEDS_CEILING, item_id=item_id,
                detail=f"field mcp_refs (mcpServers injection) on {item_id}: {rejected.reason}",
            )
        if revision.skill_refs:
            raise errors.DomainError(
                errors.REFERENCE_UNRESOLVED, item_id=item_id,
                detail=(f"{len(revision.skill_refs)} skill_refs on {item_id}: the skills "
                        "entry is unproven at this pin (capability-matrix §Claude "
                        "'not proven'); refused, not dropped"),
            )
        if revision.isolation:
            raise errors.DomainError(
                errors.REFERENCE_UNRESOLVED, item_id=item_id,
                detail=(f"isolation declaration {sorted(revision.isolation)!r} on {item_id}: "
                        "private-generation equivalence for this field is unmeasured at "
                        "the pin; compiled as nothing means refused here"),
            )
        if revision.retained_native_fields:
            names = ", ".join(sorted(revision.retained_native_fields))
            raise errors.DomainError(
                errors.DEFINITION_INVALID, item_id=item_id,
                detail=(f"revision {item_id} retains unmapped native field(s) [{names}]: "
                        "not compilable at this pin and never silently dropped"),
            )
        validate_agent_name(item.native_name, item_id=item_id)
        if len(item.definition.description) > limits.MAX_DESCRIPTION_CHARS:
            raise errors.DomainError(
                errors.DEFINITION_INVALID, item_id=item_id,
                detail=f"description on {item_id} exceeds MAX_DESCRIPTION_CHARS",
            )

    def _render_document(self, item: intents.ManagedItem) -> str:
        """Pure: one managed revision -> one strict-subset frontmatter document."""
        revision = item.revision
        fields: dict[str, Any] = {
            "name": item.native_name,
            "description": item.definition.description,
        }
        if revision.declared_model_ref is not None:
            # declaration only (matrix row 'model reference' = U): writing the
            # owner id is the declaration; no runtime effect is ever claimed.
            fields["model"] = revision.declared_model_ref.owner_id
        if revision.tool_refs:
            fields["tools"] = tuple(ref.owner_id for ref in revision.tool_refs)
        for key in fields:
            if key not in _SUPPORTED_BY_NAME:
                raise errors.DomainError(
                    errors.DEFINITION_INVALID, item_id=item.definition.definition_id,
                    detail=f"frontmatter key {key!r} has no table entry at this pin: "
                           f"{CLAUDE_UNKNOWN_BEHAVIOUR}",
                )
        return frontmatter.emit_frontmatter(fields, revision.role_body)

    # -- rebuild-class options: named refusal, not a side channel -------------
    def rebuild_class_option(self, option_key: Any, value: Any = True) -> Any:
        """ALWAYS refuses (C-6 / SR-3b-2): the published contract has no
        rebuild-class option intent, so the `agents`/`setting_sources`
        semantics cannot be claimed in-place — see
        :func:`ordessa_assets_subagents.adapters.intents.build_rebuild_class_option`."""
        return intents.build_rebuild_class_option(option_key, value)

    # -- invoke (representable in the contract, not emittable today) ----------
    def invoke(self, native_name: str) -> Any:
        """At this pin the native subagent control tool (C-4) is not reachable
        through Ordessa's own ACP path (SR-3b-1: the client capability is
        never negotiated), so no invokable fact exists and no `InvokeAction`
        may be emitted (G17). The contract-side builder
        `intents.build_invoke_action` is the only spelling and demands
        evidence this pin cannot provide."""
        raise errors.DomainError(
            errors.NATIVE_ENTRY_UNAVAILABLE,
            item_id=native_name,
            detail=("no invokable-fact evidence exists at this pin (SR-3b-1), "
                    "so the evidence-gated InvokeAction builder is never reached"),
        )
