# T02 — Versioned capability matrix (probe evidence, level-labelled)

Frozen 2026-09-28. This page records **what was actually observed on this host at
this baseline**, and at which evidence level. Per
`docs/design/native-subagents/harness-adapters.md` §"证据分级" and
`verification.md`: with no reliable L2/L3 probe the cell stays `unknown` — an
`unknown` is never upgraded to `supported` by upstream documentation of the
*latest* version, and never downgraded to `false`.

Evidence levels: **L1** pure unit; **L2-static** inspection of the *pinned*
artifact; **L2-exec** running the pinned target under a controlled probe;
**L3** product Server→Harness→ACP chain; **L4** real model (not authorized).

## Host and pin facts (measured, not quoted from design)

| Item | Value | How measured |
| --- | --- | --- |
| `pi` executable | `/home/maoqh/.local/bin/pi`, version **0.86.1** | `pi --version` |
| Repo Pi pin | Pi runtime packages **0.84.2**, adapter `@automatalabs/pi-acp` **0.5.0** | `plugins/harness/packaging/builders/build-pi-runtime-artifact.mjs:69-71`, `pi/production.py:76-77` |
| `claude` executable | **ABSENT** from `PATH` | `command -v`; the repo's own diagnostic prints `TOOL_claude=ABSENT` |
| `codex` executable | **ABSENT** from `PATH` | `command -v` |
| Claude pinned adapter artifact | **not vendored**; declared in `plugins/harness/packaging/claude/package.json` (`0.81.2`), closure needs `npm install` | `find plugins/harness/packaging -name '*.tgz'` → only `pi` and `codex` tarballs exist |
| Codex pinned adapter artifact | **vendored**: `plugins/harness/packaging/codex/vendor/agentclientprotocol-codex-acp-1.1.14.tgz`, internal `package/package.json` `"version": "1.1.14"` | extracted to the仓外 evidence root and inspected |
| Pi pinned adapter artifact | **vendored**: `plugins/harness/packaging/pi/vendor/automatalabs-pi-acp-0.5.0.tgz` | extracted and inspected |
| Host user-native dirs | `~/.claude/agents` **exists**; `~/.pi/agents`, `~/.codex/agents` absent | `ls -d` — existence only; **contents deliberately not read** (`verification.md` G24: user HOME is never a fixture and must stay byte-identical) |

**Pin drift registered:** the host `pi` is 0.86.1 while the product pins 0.84.2.
Any Pi observation below is therefore *not* evidence about the pinned version
unless it comes from the pinned artifact itself.

## Codex — pinned adapter `@agentclientprotocol/codex-acp` 1.1.14 (L2-static)

Inspected `package/dist/index.js` from the vendored, version-matched tarball
(evidence copies live in the仓外 evidence root
`/home/maoqh/ordessa-evidence/q3/probe/package/dist/index.js`, not in git):

| Token found in the pinned artifact | Occurrence | Interpretation |
| --- | --- | --- |
| `.agents` | `additionalRoots.map((root) => path.join(root, ".agents", "skills"))` | The `.agents` root the adapter uses is the **skills** root, not a subagent definition root. |
| `agentsStates`, `item.agentsStates` | forwarded ACP session-update field | Protocol state plumbing; **not** subagent definition discovery. |
| `.codexHome` | present | The adapter does carry a Codex home notion. |
| `developer_instructions` | present as a field name | The Codex agent-config field name exists in the adapter's vocabulary. Static presence only. |
| `.codex/agents`, agent-directory scan, `subagent` | **zero hits** | No subagent definition discovery path in the pinned adapter. |

**Conclusion (honest):** the design doc's "当前不能擅称" cell for Codex is
*confirmed by the pinned artifact*: `harness-adapters.md:8` states the Go Codex
桥/app-server does not discover private roots or make native subagents callable
on the ACP path, and the pinned 1.1.14 adapter contains no such discovery code.
So for Codex at this pin:

- `NATIVE_DISCOVERY_UNCONTROLLED` is the expected state for anything this line
  writes — a generated `.codex/agents/*.toml` cannot be claimed `loaded`.
- Whether the **Codex CLI 0.147.0 itself** honours `.codex/agents/*.toml` is
  **unknown at L2-exec** on this host: the CLI is not installed, and installing a
  second real CLI binary is out of scope for this round (no binary in git; and a
  non-pinned download would violate G01's "官网最新版 ≠ 仓内 pin").

## Pi — `pi` 0.86.1 host CLI + pinned `@automatalabs/pi-acp` 0.5.0

- `pi --help` (L2-exec of the *host* version) shows an extension mechanism:
  `pi install/remove/uninstall/update/list <source>`, `pi config`,
  `--tools`, `--no-tools`, `--no-builtin-tools`, `--exclude-tools`, and
  session controls (`--resume`, `--session`, `--session-id`, `--fork`,
  `--session-dir`, `--no-session`).
- There is **no** built-in `agents` file/`--agents-dir` option in the help text,
  and `~/.pi/agents` does not exist. This is real, version-close evidence for the
  design claim (`harness-adapters.md:9`) that Pi's subagent capability is
  **extension-backed**, not a built-in definition format.
- Pinned adapter artifact `automatalabs-pi-acp-0.5.0` contains **no**
  `subagent` / `.pi/extensions` / agents-directory reference (grep over the
  extracted `dist/*.js`) → the ACP path as pinned exposes no subagent entry.
- Consequence for T08: the Pi adapter must compile **nothing** unless a
  Harness-registered, audited extension plus a real control port exist. Neither
  exists in this tree today, so the correct output is `unsupported` and the
  correct gate result for G14 is "explicitly absent", not green.
- **Measured on this host (L2-exec, read-only):** `pi list` exits 0 and prints
  `No packages installed.` — i.e. **no extension package of any kind is
  registered** in the host Pi install (`/home/maoqh/.pi/agent/bin/pi`, 0.86.1),
  and no `examples/extensions/subagent` tree was found under that install. So the
  precondition T08 requires ("Harness 已登记受审扩展且真实控制端口存在") is
  verifiably false today, on two independent sides: nothing registered in Pi, and
  no Harness extension audit exists in this repo. Q3 therefore implements the Pi
  adapter as an explicit `unsupported` decision with a diagnostic, and does **not**
  install the sample extension to buy a green.
- **Not proven:** whether the official `examples/extensions/subagent/` extension
  behaves with respect to permissions/cancellation/resume as Ordessa governance
  requires. That review belongs to C0's Harness extension audit; Q3 does not
  install it (FR: never install a sample extension to buy a green).

## Claude — `@agentclientprotocol/claude-agent-acp` 0.81.2 (L2-static, artifact obtained this round)

The pinned artifact was installed **outside the repository** into
`/home/maoqh/ordessa-evidence/q3/claude-pkg` (`npm install --no-save
@agentclientprotocol/claude-agent-acp@0.81.2`; resolved `package.json` reports
`"version": "0.81.2"`, matching the pin in
`plugins/harness/src/ordessa_harness/claude/production.py:66-67`). Findings, all
from that version-matched artifact (`dist/acp-agent.js`,
`dist/acp-subagents.js`, `dist/native-subagents.js`, `dist/managed-policy.js`):

| # | Observation (pinned 0.81.2) | Location | Consequence for Q3 |
| --- | --- | --- | --- |
| C-1 | The ACP `initialize` result advertises session capability `subagents: {}` alongside `additionalDirectories, close, delete, fork, list, resume` | `acp-agent.js:1086-1094` | Subagent sessions are a **negotiated** capability, so `supported/unknown` must be read from the handshake, never assumed (G01). |
| C-2 | Extension capability id `AIR_NATIVE_SUBAGENT_SESSIONS_CAPABILITY = "nativeSubagentSessions"`; events `"subagent_spawned"`, `"subagent_state_update"`, plus `subagent-transcript`, `subagent_type`, `subagentSessionId`, `subagentParentToolUseId`, `subagentDisplayName`, `subagentDescription`, `subagentIdentity` | `acp-subagents.js`, `native-subagents.js` | There is an observable **spawn/state** event stream → `used` is recordable only from these events, exactly as `data-model.md` §状态和迁移 demands. |
| C-3 | `clientSupportsSubagents(clientCapabilities)` gates a per-session `NativeSubagentRuntime` (`session.nativeSubagentRuntime ??= new NativeSubagentRuntime(..., params.sessionId, ...)`) with `subagents.route(notification, sendUpdate, eagerOwnerSessionId)` | `acp-agent.js:2055-2119` | Runtime state is **keyed by session id**, which is the shape US4/G13 needs for A/B isolation — proven at adapter level, still unproven through Ordessa's own chain. |
| C-4 | `isNativeSubagentControlTool(toolName)` / `claudeMeta?.toolName` — a **native subagent control tool** exists as a distinct, recognizable tool | `native-subagents.js`, `acp-agent.js` | This is the "既有受限调用动作" §C4 requires for a real Chat invoke action (G17). Q3 may only offer invoke once this control tool is reachable through Ordessa's own ACP path. |
| C-5 | Query options are built as `{ systemPrompt, settingSources: ["user","project","local"], ...userProvidedOptions, ... }` | `acp-agent.js:6376-6385` | The pinned adapter **does** load user/project settings sources by default — i.e. the `.claude/agents` discovery layer is live at this pin, and a caller-supplied option wins over the default because of the merge order. |
| C-6 | `OPTION_REBUILDS_SESSION` classifies every SDK `Options` key, with `agents: true` and `settingSources: true`; the comment states "A changed `_meta.claudeCode.options` key on session/load or session/resume must rebuild the Query process." | `acp-agent.js:286-300` | Two candidate injection entries are visible: **native settings files** (C-5) and the **programmatic `agents` option** via `_meta.claudeCode.options`. Both are **rebuild-class** options ⇒ no hot reload: FR04/US4 "effective at next submission" must be implemented as a *session rebuild or proved reload*, never as in-place mutation. |
| C-7 | `managed-policy.js:21` resolves managed policy with `{ settingSources: [] }` | `managed-policy.js` | Managed policy is computed with **no** settings sources, so a definition arriving through user/project files cannot influence the managed policy ceiling. This is the structural backing for FR06/G09 — and Q3 must still re-adjudicate at apply time, not assume it. |

**Ordessa-side gap (this is the blocking fact, measured in this repo):** plain
`grep` over `plugins/harness/src/ordessa_harness/claude/*.py` and
`plugins/harness/adapters/acp-adapter/internal/` finds **no** `_meta` option
pass-through, no `claudeCode.options`, no `settingSources`, no `agents` key. So
today Ordessa neither sends the programmatic `agents` option nor declares the
`nativeSubagentSessions` capability client-side, even though the pinned adapter
supports both. Recorded as SR-1/SR-3 with these exact symbols.

**Not proven:** that `permissionMode`, `mcpServers`, `skills` or `hooks` inside a
Claude agent definition are honoured — the strings `permissionMode` (7) and
`mcpServers` (20) occur in the artifact, but occurrence is not field-level
honouring, and upstream states plugin-scope subagents ignore them
(`harness-adapters.md:15`). Those cells stay `U`, and Q3 **refuses** them (R)
rather than passing them through. Also `claude` CLI is absent on this host, so no
L2-exec and no L3 exists for Claude.

## Field matrix (per G03: support / reject / unknown + evidence, per brand)

`S` supported-with-proof · `A` present in the pinned **adapter artifact** only
(L2-static; the Ordessa-side channel is absent, so no runtime claim) · `R`
rejected by Q3 policy (refuse before side effects) · `U` unknown at this pin ·
`X` unsupported (proven absent)

| Declaration field | Claude 0.81.2 | Codex 1.1.14 / CLI 0.147.0 | Pi 0.5.0 adapter / host 0.86.1 | Q3 policy today |
| --- | --- | --- | --- | --- |
| stable name / slug | U | U | U | compile; `NATIVE_NAME_CONFLICT` refusal path implemented, target behaviour unknown |
| short description (→ catalog/model context) | `A` (`subagentDisplayName`/`subagentDescription` in the spawn event, C-2) | U | U | compile with aggregate cap |
| role body / instructions | `A` (SDK `agents` option is a classified option, C-6) | `developer_instructions` token present in pinned artifact (static only) | `--system-prompt` / `--append-system-prompt` exist on host CLI (wrong version) | compile; never claimed `loaded` |
| model reference | U | U | U | declaration only, `REFERENCE_UNRESOLVED` unless resolved |
| tool allowlist | U | U | host CLI has `--tools/--exclude-tools` (not the pinned version) | declaration only; ceiling authority required (SR-6) |
| `permissionMode` | `U` (string occurs, honouring unproven; upstream: ignored for plugin-scope) | n/a | n/a | **R** — refused, not silently narrowed (FR06) |
| `mcpServers` injection | `U` (string occurs, honouring unproven; upstream: ignored for plugin-scope) | U | U | **R** |
| `hooks` | U (upstream: ignored for plugin-scope) | n/a | n/a | **R** |
| `sandbox_mode` | n/a | U (accepted values unverified at pin, `docs/design/safety-controls/harness-adapters.md:8`) | n/a | **R** as a grant; may only ever narrow |
| isolation / instance-private root | `A` per-session `NativeSubagentRuntime` keyed by `sessionId` (C-3); Ordessa-side unproven | **X** in adapter (no private-root discovery) | **X** in pinned adapter | Q3 emits a private-generation intent; application blocked on SR-2 |
| native discovery of user/project definitions | `A` `settingSources: ["user","project","local"]` at C-5 | **X** in pinned adapter (`.agents` = skills root only) | **X** (`~/.pi/agents` absent, no built-in) | `inspectNative` returns `Unknown`, never an empty list |
| reload / hot update | **X/`R`** — `agents` and `settingSources` are rebuild-class options (C-6): no in-place update at this pin | U | U | Q3 treats "next submission" as rebuild-or-proved-reload; no hot-reload claim |
| explicit invocation action | `A` native subagent **control tool** + `nativeSubagentSessions` capability (C-1/C-4) | U | U | `invokable` stays `unknown` until reachable through Ordessa's own ACP path; Chat offers detail-only (SR-5) |
| restart + same-native-session resume | `A` session capability `resume: {}` advertised (C-1) | U | host CLI exposes `--resume/--session` (wrong version) | claimed only via SR-2 evidence |
| permission ceiling independent of definition files | `A` managed policy resolves with `settingSources: []` (C-7) | U | U | still re-adjudicated at apply time; C-7 is structure, not a substitute |

## What this page deliberately does NOT claim

- No L3 claim for any brand: `foundation` and `harness-api` checkpoints do not
  exist yet (`implementation-baseline.md`).
- No `loaded` / `invokable` / `used` state for any definition, because there is
  no observed native loader. `projected` is the ceiling reachable by unit tests
  alone, and Q3 does not report it as more.
- No Pi "built-in subagents" and no three-brand green (`spec.md` §成功条件,
  G02/G14/G22).
- No upgrade of an upstream-doc statement into a repo-pin fact (G01's negative
  column).
