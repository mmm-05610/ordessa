# T02 — Pi extension-backed dependency and review checklist

Required by `specs/011-q3-subagents/tasks.md` T02 ("Pi 标明 extension-backed 依赖
与审查清单") and gated by G02/G14. This is a **blocking list owned by C0**, not a
Q3 to-do: Q3's Pi adapter (`T08`) compiles nothing until items A1–A7 are answered
with evidence, and the correct output before that is a typed `unsupported`.

## Measured starting state (this round, this host, read-only)

| Fact | Value | Evidence |
| --- | --- | --- |
| Host Pi CLI | `/home/maoqh/.pi/agent/bin/pi`, `pi --version` → `0.86.1` | executed |
| Repo Pi pin | Pi packages `0.84.2`; adapter `@automatalabs/pi-acp` `0.5.0` | `plugins/harness/packaging/builders/build-pi-runtime-artifact.mjs:69-71`, `pi/production.py:76-77` |
| Registered Pi extension packages | **none** — `pi list` → `No packages installed.` (exit 0) | executed |
| Official `examples/extensions/subagent` present locally | **not found** under the host Pi install | `find` over the install tree |
| Built-in agents file mechanism in Pi | none in `pi --help` (extension commands + tool flags only); `~/.pi/agents` absent | executed / `ls -d` |
| Pinned adapter artifact surface | `automatalabs-pi-acp-0.5.0` dist has **no** `subagent` / `.pi/extensions` / agents-directory reference | extracted to仓外 evidence root and grepped |
| Pi `attach` capability in this repo | declared but **not observed** — every gate round had `message.attachments == []` | `plugins/harness/src/ordessa_harness/harnesses.toml:376-388` |

## Audit items — owner C0 (Harness), one line each: what must be proven

| # | Item | Why it blocks Q3 | Gate |
| --- | --- | --- | --- |
| A1 | **Provenance and license of the extension** actually used: source repo, full commit SHA of `examples/extensions/subagent/{index.ts,agents.ts}`, SPDX licence, NOTICE entry, dependency closure | `research-and-reuse.md` §"Pi 示例扩展": vendoring requires a fixed commit + licence + dependency closure; borrowing a design is not borrowing code | G21, G15 |
| A2 | **Registration as a Harness execution dependency**: the extension must be a dependency the Harness declares, installs/updates under its own pin, and logs — not something the definitions plugin ships | `contracts.md` §C3: "Pi 额外需要经 Harness runtime 注册且明确 owner 的 executable extension；定义插件不能自带一个隐藏执行宿主" | G14 |
| A3 | **Trust boundary**: Pi extensions run with the main Pi process's OS privileges and upstream says only trusted sources may be loaded | A user-imported "definition" must never become executable extension code (FR14: no import-then-execute) | G05, G09 |
| A4 | **Process model and isolation**: the example spawns a separate `pi` process per subagent — pin the process tree, per-instance HOME/cwd, and prove A/B sessions cannot read each other's definitions | US4/G13 require the user HOME and project native files to stay byte-identical across two live sessions | G13 |
| A5 | **Cancellation and resource accounting**: prove a spawned subagent process is cancelled when the parent turn is stopped, and that its usage is attributed | `docs/known-issues.md:33` already registers that stop does not interrupt an in-flight tool turn — Q3 cannot assume subagent processes are safer than the parent | G18–G20 |
| A6 | **Control port / invocation observability**: a real control entry that yields a *distinct* `invokable` fact and an independent event that yields a `used` fact | `data-model.md` §状态和迁移: `projected / loaded / invokable / used` are separate facts; `harness-adapters.md` §证据分级 requires `extension-backed` labelling before L3 | G14, G17 |
| A7 | **Version match**: re-run A1–A6 against the **pinned** Pi version the product ships (0.84.2), not the host's 0.86.1 | G01's negative column: an upstream "latest" fact must not be recorded as supported at the repo pin | G01, G03 |

## Q3 behaviour while any item is unanswered (already implemented policy, not a placeholder)

1. `adapters/pi.assess(target)` → `unsupported` with reason `ADAPTER_MISSING` /
   `NATIVE_ENTRY_UNAVAILABLE` and an `extension-backed: absent` diagnostic. No
   silent `unknown` when absence is *proven* (A1–A7 unproven = `unknown`; the
   extension not being registered at all = `unsupported`).
2. `adapters/pi.compile(...)` raises a typed refusal **before** producing any
   intent, so nothing can reach a Pi target.
3. Q3 never runs `pi install`, never vendors the example, and never edits the
   host `~/.pi` settings. Verified by a test asserting no subprocess call and no
   filesystem write outside the injected store root.
4. `report.md` keeps the Pi row of G22–G24 as **not complete**, and this line does
   not report three brands green (`spec.md` §成功条件, `tasks.md` T14).

## Cross-references

- `capability-matrix.md` §Pi — the L2-exec / L2-static evidence behind A1–A7.
- `api-requests.md` SR-1/SR-2/SR-3 — the Harness seams that A2/A6 depend on.
