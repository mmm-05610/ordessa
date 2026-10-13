# dsh channel reuse decision (DeepSeek Harness Provider)

Repository checkpoint: baseline `c47696b74b11863a9ee2fd1542033e72ce9b513b`
plus the frozen dsh package specification
(`docs/implementation/agent-tools/dsh-package-freeze-v1.md`, 2026-10-07).

| Candidate | Fixed source evidence | Decision |
| --- | --- | --- |
| Official dsh ACP stdio face | DeepSeek real-interface check 2026-10-07: official `dsh` (developer preview) exposes an ACP stdio surface; npm `@deepseek-ai/dsh` locked at `0.1.5-rc.1` (`tooling/npm/package-lock.json` resolved URL + integrity `sha512-rmNmzQCg3oIc1z8xH7izRSOuy1TNzq+/NILyfM+7e8DKOyV+yBtg47WEsqR2SiIe1ATec3L/rUa1YhIcfQ2XEg==`); `harnesses.toml` static registration documents the ACP surface (`new/list/resume/close/prompt/cancel/set_config_option/request_permission`) and `dsh --profile acp`; npm latest `0.2.0-rc.2` has zero in-repo ACP evidence | **Selected**: native ACP stdio subprocess channel, frozen pin `0.1.5-rc.1`; ACP JSON-RPC 2.0 frames; every capability behind explicit deployment ports |
| PyPI SDK `deepseek-harness-sdk==0.1.5rc1` | Freeze §1: independent version track, not part of the initial dependency set; no in-repo artifact audit establishes a compatible SDK surface for this tree | **Not in initial dependencies** (no `sdk` extra). Future adoption must copy the claude-code extras pattern (lazy optional import, separately pinned) and re-verify independently; it must never be inferred together with the npm CLI track (see 禁双轨推断 below) |
| Go ACP bridge (`plugins/harness/pi/vendor/acp-adapter`) | `harnesses.toml` dsh continuation block: `kind = "native_session"`, `contract_id = "agent-box.dsh-continuation@1"`, `target_provider = "dsh-continuation"`; dsh explicitly rejects `session/load`; resume does not replay history | **Wire/reference source only, not this brand's Go backend**: Go cmd supports Codex/Pi only. Own Python DshAcpClient emits session/resume under the historical agent-box.dsh-continuation@1 declaration; current provider.recover remains permanently typed-refused. No in-repo Go Dsh implementation or verified durable continuation provider is inferred. |
| Legacy Harness paths / old direct-native wrappers | `docs/reference/index.md` history: retired `agent_box` code and old Harness provider internals import retired compat chains; the bridge's old paths reinterpret upstream natively | **Do not revive** legacy dependencies or route dsh through them; reuse identity knowledge only. No placeholder implementations in `main` |

## Explicit injected ports (documented in provider.py)

Projection must bind the original UnitRecords instance, not copy its
database. `channel_factory.open` must perform its installation/root checks
and managed stdin cut before the first native write. Termination evidence
must be the SAME port instance UnitRecords consumes. Configuration changes
lack a production CAS/evidence adapter for dsh and are honestly unavailable
(all four configuration methods absent, typed-refused). There is no new state
ledger to guess completion from actual values. The descriptor digest has no
default and is never generated in-package; the deployment fingerprint gate
injects it, and until that gate is backfilled the dsh provider must not appear
in any production assembly.

## 升级重验六件套 (frozen text, freeze §6)

CLI bump 必须原子六事，缺一不可：

1. **lock hash**：`tooling/npm/package-lock.json` 的 resolved/integrity 与
   npm pin 同步更新（当前锁值 `0.1.5-rc.1` /
   `sha512-rmNmzQCg3oIc1z8xH7izRSOuy1TNzq+/NILyfM+7e8DKOyV+yBtg47WEsqR2SiIe1ATec3L/rUa1YhIcfQ2XEg==`）。
2. **假端点全链门重跑**：受控假 dsh 端点跑完整链门，且必须包含两条不变量
   重验 —— `session/load` 仍被拒绝（客户端无 load 方法/常量、describe 报
   recovery unsupported、测试断言无 load 能力），`session/resume` 仍不重放
   历史（resume 归桥 continuation 合同，不进 provider supported_methods）。
3. **toml 按门证据更新**：`harnesses.toml` 只按门证据更新（observed 只许门
   证据回填；静态声明保持如实注释）。
4. **capability_declarations 同步**：能力声明与门证据逐项同步（未观测项不得
   声明）。
5. **settings 重验**：settings/profile 模板按新 pin 重验。
6. **证据登记**：升级证据在本包 `tests/runtime-process-evidence.md` 与
   implementation evidence 目录登记。

observed 只许门证据回填 —— 任何版本/能力的 observed 结论都不得由文档推断、
不得由相邻家族（codex/pi/claude-code）类比得出。

## SDK 独立轨 (independent track)

`deepseek-harness-sdk==0.1.5rc1` 是与 npm CLI `0.1.5-rc.1` **相互独立**的
版本轨。SDK 的引入必须：

- 走 claude-code extras 模式（`[project.optional-dependencies]` 独立 extra、
  lazy import、独立钉死版本）；
- 独立重验其 ACP 面（不得复用 CLI 假端点门的结论作为 SDK 证据）；
- 独立登记证据。

## 禁双轨推断 (no dual-track inference)

npm CLI 轨与 PyPI SDK 轨的版本号、能力面、observed 结论 **一律不得互相推断**：
一轨的观测不构成另一轨的证据；版本号相近不构成兼容声明。任何把两轨混用的
装配（同 provider 同时依赖两轨、或用一轨 digest 充当另一轨）都是被禁止的
伪造路径。当前初版只钉 npm CLI `0.1.5-rc.1` 一轨，SDK 轨完全缺席。

## Additional pinned disciplines

- **descriptor digest 零伪造**：必需、无默认、包内不生成不猜测；测试 fixture
  （`sha256:` + `aaa…`/`a…`）明确注明非真实。
- **版本钉死不追新**：`0.1.5-rc.1` 不追 npm latest `0.2.0-rc.2`（其 ACP 面本仓
  零证据）；升级只能走上面的六件套。
- **recover 永久缺席**：dsh 拒绝 `session/load`；这不是暂时缺口，而是本包的
  永久合同；resume 永远是桥的 continuation，不是 provider 的恢复面。
- **真实进程边界**：本包测试不启动真实 dsh 进程（规则 6/9）；受控假进程/假端点
  即可。真实进程验证、生产装配、门回填均为 NOT_RUN，登记于
  `tests/runtime-process-evidence.md`。
