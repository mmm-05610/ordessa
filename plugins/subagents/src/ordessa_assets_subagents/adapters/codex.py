"""Codex configuration adapter triad (G12, G13), on the published contract.

Pins: ACP adapter `@agentclientprotocol/codex-acp@1.1.14`, Codex CLI
`0.147.0` — now carried as the descriptor's real `VersionRange` bounds. The
load-bearing measured fact (capability-matrix.md §Codex, L2-static over the
vendored version-matched tarball): the pinned adapter has **no `.codex/agents`
discovery at all** — the `.agents` root it touches is the *skills* root — so
native discovery is **unsupported** (proven absent), not `unknown`. What
stays `unknown` is separate and is spelled out per cell: whether the *CLI
itself* (not installed on this host, hence no L2-exec) honours
`.codex/agents/*.toml`.

Because discovery is proven absent, `compile` refuses the whole collection
with `NATIVE_DISCOVERY_UNCONTROLLED` before any intent exists — a generated
`.codex/agents/*.toml` could never be honestly report
`loaded` on this line (matrix: 「NATIVE_DISCOVERY_UNCONTROLLED is the
expected state for anything this line writes」). The registered descriptor
claims NOTHING (empty `claims`): with the discovery cell proven absent there
is no field or directory this adapter may claim; the empty claim tuple is the
contract-side spelling of the same fact the old `TargetSlot` enum carried.
The pure document builder stays exported as the L1 format evidence (tomlwriter
round-trip); `verify` refuses loader claims outright (ladder path) and the
contract-shaped `verify` answers such a readback with `Mismatch` — a
`Match` for Codex is unreachable at this pin (G12 counter-example made
structural).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ordessa_harness_api import (
    ConfigurationAdapterDescriptor, IntentSet, ValueSchema, VersionRange,
)

from .. import errors, limits
from . import base, intents, tomlwriter

CODEX_HARNESS_ID = "codex"
CODEX_ADAPTER_PIN = "@agentclientprotocol/codex-acp@1.1.14"
CODEX_CLI_PIN = "0.147.0"
CODEX_ADAPTER_SEMVER = (1, 1, 14)
CODEX_CLI_SEMVER = (0, 147, 0)

CODEX_RESERVED_NAMES: frozenset[str] = frozenset()
#: Registered as *none-known*: no built-in Codex agent name has been observed
#: at this pin, so the collision table is empty but the duplicate/native-name
#: conflict diagnostics still run (G13). An empty table is a recorded fact,
#: not a silence.

_EVIDENCE_ABSENT: tuple[str, ...] = (
    "capability-matrix.md §Codex (L2-static on package/dist/index.js of the "
    "vendored codex-acp-1.1.14.tgz): '.codex/agents', agent-directory scan and "
    "'subagent' have ZERO hits; the only .agents use is additionalRoots/"
    "'.agents'/'skills' — the skills root",
    "capability-matrix.md §Host and pin facts: `codex` executable ABSENT from "
    "PATH — no L2-exec probe of the CLI is possible on this host",
)

_EVIDENCE_UNMEASURED: tuple[str, ...] = (
    "capability-matrix.md §Codex conclusion: whether Codex CLI 0.147.0 itself "
    "honours .codex/agents/*.toml is unknown at L2-exec (CLI not installed; "
    "installing an unpinned binary is out of scope)",
)


@dataclass(frozen=True)
class CodexKey:
    """One registered Codex agent-document key at this pin (NativeKey shape)."""

    key: str
    classification: str          # supported | rejected
    reason: str
    evidence: str


#: The agent-TOML schema keys with a proven name at the pin. `developer_
#: instructions` occurs in the adapter artifact as a *field name* (static
#: presence only); the role body lands there and is never claimed `loaded`.
CODEX_SUPPORTED_KEYS: tuple[CodexKey, ...] = (
    CodexKey("name", "supported",
             "the agent-name field; filename==name entry grammar",
             "harness-adapters §格式映射; capability-matrix row 'stable name' (U→compile, "
             "conflict diagnostic only)"),
    CodexKey("description", "supported",
             "catalog line; aggregate-capped",
             "harness-adapters §格式映射"),
    CodexKey("developer_instructions", "supported",
             "role body; token present in the pinned artifact as a field name — "
             "STATIC presence, so no loaded claim",
             "capability-matrix.md §Codex token table row 'developer_instructions'"),
)

#: `sandbox_mode` is NEVER emitted as a grant: its accepted values are
#: unverified at this pin, and a definition field must not widen the outer
#: sandbox (matrix row 'sandbox_mode': R as a grant; may only ever narrow —
#: narrowing requires SR-6, which is absent).
CODEX_REJECTED_KEYS: tuple[CodexKey, ...] = (
    CodexKey("sandbox_mode", "rejected",
             "not a grant of Ordessa's outer sandbox; accepted values unverified "
             "at this pin — refuse rather than pass through",
             "capability-matrix row 'sandbox_mode' + harness-adapters §格式映射"),
)

_PROVEN_KEYS = {entry.key for entry in CODEX_SUPPORTED_KEYS}
_REJECTED_BY_NAME = {entry.key: entry for entry in CODEX_REJECTED_KEYS}

#: Provisional facet payload shape (same placeholder family as Claude's).
CODEX_PAYLOAD_SCHEMA = ValueSchema(
    "object",
    properties=(("definitions", ValueSchema("array", items=ValueSchema("string"))),),
    required=("definitions",),
)


def render_agent_document(item: intents.ManagedItem) -> str:
    """Pure L1 document build: revision -> verified TOML text.

    Every emitted document passes the `tomllib` round-trip validator, which
    is the format evidence G12's L1 column asks for.
    """
    document: Mapping[str, Any] = {
        "name": item.native_name,
        "description": item.definition.description,
        "developer_instructions": item.revision.role_body,
    }
    unknown = set(document) - _PROVEN_KEYS
    if unknown:
        raise errors.DomainError(
            errors.DEFINITION_INVALID, item_id=item.definition.definition_id,
            detail=f"codex document keys {sorted(unknown)} have no table entry at this pin",
        )
    return tomlwriter.render_document(document)


class CodexAdapter(base.ConfigurationAdapter):
    """Triad for the pinned Codex ACP adapter + CLI pin."""

    adapter_id = "ordessa.assets.native-subagents.codex"
    harness_id = CODEX_HARNESS_ID
    pinned_version = CODEX_ADAPTER_PIN
    mount_suffix = ".toml"

    descriptor = ConfigurationAdapterDescriptor(
        adapter_id, "v1", intents.FACET_ID, "v1", CODEX_HARNESS_ID,
        VersionRange(CODEX_CLI_SEMVER, CODEX_CLI_SEMVER),
        VersionRange(CODEX_ADAPTER_SEMVER, CODEX_ADAPTER_SEMVER),
        ("acp",),
        CODEX_PAYLOAD_SCHEMA,
        (),  # empty claims: nothing is provably claimable while discovery
             # is proven absent (contract-side spelling of the old slot fact)
    )

    # -- assess ---------------------------------------------------------------
    def assess_detail(self, context: Any, request: Any = None) -> base.Assessment:
        """Native discovery: `unsupported` (proven absent in the adapter).
        CLI-side honouring / invocation / reload: `unknown` (unmeasured, not
        disproved). The two are named separately so nothing reads the
        `unsupported` as a CLI verdict (G01/G03). `assess()` yields the real
        `Assessment` with `status="unsupported"` + reason + evidence_ref."""
        self._validate_context(context)
        unsupported = base.AssessmentState.UNSUPPORTED
        unknown = base.AssessmentState.UNKNOWN
        cells = (
            base.CellVerdict(
                cell="adapter-native-discovery", state=unsupported,
                reason=("the pinned codex-acp adapter has no .codex/agents "
                        "subagent-definition discovery; its .agents root is the "
                        "skills root — proven ABSENT (L2-static), not unmeasured"),
                evidence=_EVIDENCE_ABSENT),
            base.CellVerdict(
                cell="cli-honours-agents-toml", state=unknown,
                reason=("whether Codex CLI 0.147.0 reads .codex/agents/*.toml is "
                        "UNMEASURED on this host (CLI absent → no L2-exec); this "
                        "cell is not covered by the discovery verdict above"),
                evidence=_EVIDENCE_UNMEASURED),
            base.CellVerdict(
                cell="acp-path-invocation", state=unsupported,
                reason=("no subagent entry on the ACP path at this pin — the design "
                        "doc's '当前不能擅称' cell is confirmed by the pinned artifact"),
                evidence=_EVIDENCE_ABSENT),
            base.CellVerdict(
                cell="private-root-isolation", state=unsupported,
                reason=("no private-root discovery in the pinned adapter "
                        "(capability-matrix row 'isolation': X in adapter)"),
                evidence=_EVIDENCE_ABSENT),
            base.CellVerdict(
                cell="reload", state=unknown,
                reason=("reload semantics depend on the CLI behaviour cell above; "
                        "unmeasured, never assumed"),
                evidence=_EVIDENCE_UNMEASURED),
            base.CellVerdict(
                cell="invocation-outside-acp", state=unknown,
                reason=("CLI-side invocation is unmeasured (no L2-exec); no ACP-path "
                        "invocation may ever be claimed from this adapter"),
                evidence=_EVIDENCE_UNMEASURED),
        )
        return base.Assessment(
            state=unsupported,  # the load-bearing cell (discovery) is proven absent
            pinned_version=f"adapter {CODEX_ADAPTER_PIN} / cli {CODEX_CLI_PIN}",
            evidence=_EVIDENCE_ABSENT,
            reasons=(
                "assessment 'unsupported' refers to this line's controlled path "
                "(adapter discovery / ACP entry / private root), each proven absent "
                "in the L2-static matrix; CLI-side honouring stays 'unknown' per cell "
                "(proven-absent vs unmeasured are named apart)",
            ),
            cells=cells,
        )

    # -- compile ---------------------------------------------------------------
    def compile(self, context: Any, collection: Sequence[intents.ManagedItem],
                source: Any = None, *, native_names: frozenset[str] | None = None,
                stage_content: Any = None,
                secret_bindings: Sequence[tuple[str, str]] = ()) -> IntentSet:
        """Refuse the *whole collection* before any intent exists: with the
        adapter's discovery proven absent (and no controlled reset path), a
        generated private `.codex/agents/*.toml` set could only ever be
        reported NATIVE_DISCOVERY_UNCONTROLLED anyway (G12). Even the
        host-injected source cannot make an emissible set here."""
        self._validate_context(context)
        items = tuple(collection)
        first_id = items[0].definition.definition_id if items else None
        detail = (
            "the pinned codex-acp adapter has no subagent-definition discovery "
            "(its .agents root is the skills root) and the CLI pin is unprobed on "
            "this host, so this line's Codex output can never be loaded in a "
            "controlled way; compilation is refused as a complete set rather than "
            "emitting intents whose effect is disproved (capability-matrix §Codex, G12)"
        )
        # Item-level field refusals still run FIRST and win when present, so a
        # refusal always names the offending field, not just the brand.
        for item in items:
            self._check_fields(item)
        raise errors.DomainError(errors.NATIVE_DISCOVERY_UNCONTROLLED,
                                 item_id=first_id, detail=detail)

    def _check_fields(self, item: intents.ManagedItem) -> None:
        item_id = item.definition.definition_id
        revision = item.revision
        isolation = revision.isolation
        if "sandbox_mode" in isolation:
            rejected = _REJECTED_BY_NAME["sandbox_mode"]
            raise errors.DomainError(
                errors.PERMISSION_EXCEEDS_CEILING, item_id=item_id,
                detail=f"field isolation.sandbox_mode on {item_id}: {rejected.reason} "
                       f"({rejected.evidence})",
            )
        if revision.requested_permission is not None:
            raise errors.DomainError(
                errors.PERMISSION_EXCEEDS_CEILING, item_id=item_id,
                detail=(f"field requested_permission on {item_id}: the Codex agent "
                        "schema has no permission entry at this pin; a permission "
                        "declaration is refused, never silently dropped"),
            )
        if revision.mcp_refs:
            raise errors.DomainError(
                errors.PERMISSION_EXCEEDS_CEILING, item_id=item_id,
                detail=(f"mcp_refs on {item_id}: MCP injection through a definition "
                        "is refused (matrix: U/R; each owner authorisation needs the "
                        "absent SR-6)"),
            )
        undeclared = []
        if revision.declared_model_ref is not None:
            undeclared.append("declared_model_ref")
        if revision.tool_refs:
            undeclared.append(f"tool_refs x{len(revision.tool_refs)}")
        if revision.skill_refs:
            undeclared.append(f"skill_refs x{len(revision.skill_refs)}")
        if undeclared:
            raise errors.DomainError(
                errors.REFERENCE_UNRESOLVED, item_id=item_id,
                detail=(f"{', '.join(undeclared)} on {item_id}: the proven Codex "
                        "agent schema at this pin carries only name/description/"
                        "developer_instructions; these references have no entry and "
                        "are refused, not dropped"),
            )
        if isolation:
            raise errors.DomainError(
                errors.REFERENCE_UNRESOLVED, item_id=item_id,
                detail=f"isolation keys {sorted(isolation)} on {item_id} have no proven "
                       "entry at this pin; refused rather than approximated",
            )
        if revision.retained_native_fields:
            names = ", ".join(sorted(revision.retained_native_fields))
            raise errors.DomainError(
                errors.DEFINITION_INVALID, item_id=item_id,
                detail=(f"revision {item_id} retains unmapped native field(s) [{names}]: "
                        "not compilable at this pin and never silently dropped"),
            )
        if not intents.NATIVE_NAME_RE.fullmatch(item.native_name):
            raise errors.DomainError(
                errors.DEFINITION_INVALID, item_id=item_id,
                detail=f"agent name {item.native_name!r} must match "
                       f"{intents.NATIVE_NAME_PATTERN}",
            )
        if item.native_name in CODEX_RESERVED_NAMES:
            raise errors.DomainError(
                errors.NATIVE_NAME_CONFLICT, item_id=item.native_name,
                detail="reserved name at this pin (G13)",
            )
        if len(item.definition.description) > limits.MAX_DESCRIPTION_CHARS:
            raise errors.DomainError(
                errors.DEFINITION_INVALID, item_id=item_id,
                detail=f"description on {item_id} exceeds MAX_DESCRIPTION_CHARS",
            )

    # -- contract-shaped verify -----------------------------------------------
    def verify(self, context: Any, observed: Any) -> Any:
        """Loader/control/event readbacks cannot be attributed to this target
        (proven absent), so the base mapping answers `Mismatch` — and
        `Match`, the only path to `Confirmed`, is unreachable for Codex at
        this pin. A file-existence readback yields `VerificationUnknown`."""
        return super().verify(context, observed)

    # -- verify ----------------------------------------------------------------
    def _on_observation_kind(self, observation: base.Observation) -> None:
        """Loader/control/event facts cannot be attributed to this target at
        this pin: the pinned adapter has no loader to observe (proven absent),
        so any such claim is a refusal — `loaded` is unreachable for Codex
        today, and file existence never gets closer (G12)."""
        if observation.__class__ in (base.NativeLoaderObservation,
                                     base.ControlEntryObservation,
                                     base.InvocationEventObservation):
            raise errors.DomainError(
                errors.NATIVE_DISCOVERY_UNCONTROLLED,
                item_id=observation.native_name,
                detail=(f"a {type(observation).__name__} for {observation.native_name!r} "
                        "cannot be attributed: the pinned codex-acp adapter "
                        "demonstrably has no subagent loader/control entry/event "
                        "stream (capability-matrix §Codex, L2-static), so the claim "
                        "has no possible source — refused, not downgraded into a "
                        "state"),
            )
