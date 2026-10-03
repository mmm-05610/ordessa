# ordessa-sandbox-api

Native-sandbox asset API for Ordessa (task T04 of
`docs/design/safety-controls/tasks.md`): the `NativeSandboxIntent` /
`SandboxEvidence` schema, platform-limit and admin-ceiling checks, and the
coverage proof for `sandbox.native-configuration@1` / `sandbox.describe@1`
(contracts.md §C2, §C4). Pure domain layer — stdlib only, no storage, no
service, no subprocess, no host imports.

This package is **not** the Pacthold neutral execution resource: it never
imports, names, or stands in for the `runtime_composition` sandbox port, and
nothing here may be treated as native-isolation evidence (and vice versa).

## Public surface

`ordessa_sandbox_api` exports (see `__init__.py.__all__`):

- `NativeSandboxIntent` with closed per-brand schemas `CodexSandboxConfig`
  (`sandbox_mode` + writable roots + network), `ClaudeSandboxConfig`
  (Bash/PowerShell/Monitor toggles) and `PiSandboxConfig` (extension-backed —
  Pi has **no built-in brand config**; absent extension ⇒ `SANDBOX_NATIVE_UNSUPPORTED`).
  Unknown keys are refused at construction; wildcard `all`/`*` coverage or
  paths are refused.
- `SandboxEvidence` + `SandboxVerificationOutcome` (`verified` /
  `unsupported` / `unknown` — the last two never merge) with
  `require_bound_to(...)`: a version, config-digest, instance or platform
  change invalidates old evidence with `SANDBOX_EFFECT_UNKNOWN`.
- `assess_platform` / `check_platform_gate`, `SandboxCeiling` /
  `intersect_ceilings` / `check_within_ceiling` (an admin-enforced native
  sandbox can never be disabled or loosened by Profile/user intent; maxima
  intersect; a request stricter than the native schema can express refuses
  rather than approximating), `coverage_proves` (Bash-only evidence can never
  prove read/edit/MCP/network), `check_cross_session_impact` (process-level
  change sharing sessions ⇒ refuse without a declared impact set),
  `FieldClaimRegistry` (two owners of one native field ⇒
  `SANDBOX_CONFIG_CONFLICT`), and `describe_sandbox` (`sandbox.describe@1`
  shape; menus come from the matrix rows for the current pin, never guessed
  from the brand name).
- Stable codes (`SandboxErrorCode`): `SANDBOX_NATIVE_UNSUPPORTED`,
  `SANDBOX_COVERAGE_UNPROVEN`, `SANDBOX_PLATFORM_UNSUPPORTED`,
  `SANDBOX_CONFIG_CONFLICT`, `SANDBOX_EFFECT_UNKNOWN`, `PROVIDER_BUSY`
  (+ `SANDBOX_INTENT_INVALID` for schema-level refusals, kept distinct).

## Brand matrix: what is supported, unknown, and why

`matrix.py` carries the per-brand × per-category cells with the twelve
fill-in fields from `harness-adapters.md`; unproven fields literally read
`UNKNOWN`. A cell is `SUPPORTED` only on a first-hand measurement in this
repository (level S) or a controlled probe (L2/L3).

| cell | status | why |
| --- | --- | --- |
| codex × bash/read/edit | **supported (S)** | the mode vocabulary and writable set are pinned by `plugins/server-compat/.../profiles/posture_config.py` (`_SANDBOX_STRICTNESS`, `_WRITABLE_SANDBOX`, refusal path) and carried by the bridge `ProfileConfig.Sandbox` (`plugins/harness/adapters/acp-adapter/pkg/codexacp/runtime.go`) — config-surface proof only |
| codex × network | unknown | tied to native version/platform in official docs; not measured on the pinned set here |
| codex × mcp | unsupported | the closed codex sandbox vocabulary carries no MCP-coverage field |
| claude-code × bash | unknown | documented bubblewrap/Seatbelt mechanisms (D); no repo-side write/behaviour probe yet; native Windows is a documented negative (see `platform_note`) |
| claude-code × read/edit/mcp | unsupported | the documented sandbox covers Bash/PowerShell/Monitor subprocesses only — claiming MCP isolation from a Bash sandbox is the cross-cutting refusal case |
| claude-code × network | unknown | no repo-measured network knob on the pinned surface |
| pi × anything | unsupported | extension-backed only (official sandbox example replaces Bash via an external runtime); no built-in brand sandbox exists, so absence is an explicit unsupported, never `unknown` and never an allow |

The isolation-**effect** cells for every brand remain `UNKNOWN` until the
T05 probes run; nothing in this package may present them as green.

## Limits encoded

- Codex pinned modes `read-only` / `workspace-write` / `danger-full-access`
  (strictness 3/2/1 as measured); only the first two are writable-set values.
- Claude platform limits as documented: Linux/WSL2 bubblewrap, macOS
  Seatbelt, native Windows unsupported for the Bash sandbox.
- Codex per-platform variance is deliberately `unknown` (unmeasured), and so
  is any OS or brand outside the table — assessment never guesses.

## Test / run

```sh
cd <monorepo root>
PYTHONPATH=plugins/assets/sandbox/api/src python -m pytest plugins/assets/sandbox/api -q
```

Evidence ledgers: `specs/011-q5-safety/evidence/t04-red-sandbox-api.txt`
(red against the empty package) and `t04-green-sandbox-api.txt` (green).
