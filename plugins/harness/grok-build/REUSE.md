# grok-build channel reuse decision (xAI Grok Build Provider)

Repository checkpoint: baseline `c47696b74b11863a9ee2fd1542033e72ce9b513b`
plus the Grok Build registration draft
(`docs/implementation/agent-tools/grok-build-registration-draft.md`,
2026-10-07, three-source verified) and the dsh package freeze precedent
(`docs/implementation/agent-tools/dsh-package-freeze-v1.md`).

| Candidate | Fixed source evidence | Decision |
| --- | --- | --- |
| Official Grok Build ACP stdio face | Three-source check 2026-10-07: repo `github.com/xai-org/grok-build` (Apache-2.0 double-sourced: repo badge + LICENSE header "Copyright 2023-2026 SpaceXAI"); CLI changelog x.ai/changelog/build latest **v1.0.46** (entry 2026-09-30); official ACP stdio launch `grok agent stdio` documented at docs.x.ai/build/cli/headless-scripting (initialize/authenticate/session/new/session/prompt/session/update) | **Selected**: native ACP stdio subprocess channel, frozen pin `1.0.46`; ACP JSON-RPC 2.0 frames; every capability behind explicit deployment ports |
| npm / PyPI SDK track | No npm package and no PyPI SDK exists for Grok Build (install-script/source route only; registration draft §1/§7.7) | **No SDK track exists** — nothing to pin, nothing to dual-track. If an SDK ever appears, it must copy the claude-code extras pattern (lazy optional import, separately pinned), be independently re-verified, and never be inferred together with the CLI track (see 禁双轨推断 below) |
| Go ACP bridge (`plugins/harness/pi/vendor/acp-adapter`) | `harnesses.toml` draft continuation block: `kind = "native_session"`, `contract_id = "agent-box.grok-continuation@1"`, `target_provider = "grok-build-continuation"`; ACP reopen (`session/load`\|`session/resume`) has NO documentary evidence on the grok-build face; headless `-r`/`-c` are NOT ACP paths | **Wire/reference source only, not this brand's Go backend**: Go cmd supports Codex/Pi only. Own Python GrokBuildAcpChannelFactory/client consume grok agent stdio; reopen remains absent and provider.recover permanently typed-refused. The historical agent-box.grok-continuation@1/grok-build-continuation identifiers do not prove an active Go continuation implementation. |
| Legacy Harness paths / old direct-native wrappers | `docs/reference/index.md` history: retired `agent_box` code and old Harness provider internals import retired compat chains; the bridge's old paths reinterpret upstream natively | **Do not revive** legacy dependencies or route grok-build through them; reuse identity knowledge only. No placeholder implementations in `main` |

## Explicit injected ports (documented in provider.py)

Projection must bind the original UnitRecords instance, not copy its
database. `channel_factory.open` must perform its installation/root checks
and managed stdin cut before the first native write, and must never read
`grok` login / `XAI_API_KEY`. Termination evidence must be the SAME port
instance UnitRecords consumes. Configuration changes lack a production
CAS/evidence adapter for grok-build and are honestly unavailable (all four
configuration methods absent, typed-refused). There is no new state ledger to
guess completion from actual values. The descriptor digest has no default and
is never generated in-package; the deployment fingerprint gate injects it,
and until that gate is backfilled the grok-build provider must not appear in
any production assembly.

## 升级重验六件套 (frozen text, adapted per package spec)

CLI bump 必须原子六事，缺一不可：

1. **版本 pin 复核**：本包无 npm/PyPI 锁（无包可锁，install-script/源码路线
   未编写）；pin `1.0.46` 的出处是 x.ai/changelog/build 条目（2026-09-30，
   2026-10-07 核实）。升级时同原子更新本包全部 pin 登记位（provider
   docstring、README、runtime-process-evidence.md、测试 fixture 中的
   nativeVersion）。`harnesses.toml`/`capability_declarations` 的静态注释位
   属登记另轮，不由本包写入。
2. **假端点全链门重跑**：受控假 grok 端点跑完整链门，且必须包含三条不变量
   重验 —— `authenticate` 扩展仍 gated（typed-refused，零写入，标准 ACP
   鉴权链仍不得推断）；`kill_task`/`get_task_output` 仍缺席（无方法/无常量、
   describe 报 absentMethods）；ACP 重开（`session/load`|`session/resume`）
   仍缺席（客户端无方法/无常量、describe_definition 报 recovery
   unsupported、provider.recover 仍 typed-refused 并点名
   `agent-box.grok-continuation@1`）。
3. **toml 按门证据更新**：`harnesses.toml` 只按门证据更新（observed 只许门
   证据回填；静态声明保持如实注释）——登记另轮执行。
4. **capability_declarations 同步**：能力声明与门证据逐项同步（未观测项不得
   声明；observed 留空直到门回填）——登记另轮执行。
5. **settings/profile 重验**：profile_extensions/settings 模板按新 pin 重验
   （`models:false`、`permissionMode:"deny"`、capabilities 未观测位保持
   false）——登记另轮执行。
6. **证据登记**：升级证据在本包 `tests/runtime-process-evidence.md` 与
   implementation evidence 目录登记。

observed 只许门证据回填 —— 任何版本/能力的 observed 结论都不得由文档推断、
不得由相邻家族（codex/pi/claude-code/dsh/kilo）类比得出。

## SDK 独立轨 (independent track)

当前**不存在**任何 Grok Build SDK 轨（npm/PyPI 均无）。若日后出现 SDK：
必须走 claude-code extras 模式（独立 extra、lazy import、独立钉死版本）、
独立重验其 ACP 面（不得复用 CLI 假端点门的结论作为 SDK 证据）、独立登记证据。

## 禁双轨推断 (no dual-track inference)

CLI 轨与任何未来 SDK 轨的版本号、能力面、observed 结论 **一律不得互相推断**：
一轨的观测不构成另一轨的证据；版本号相近不构成兼容声明。任何把两轨混用的
装配（同 provider 同时依赖两轨、或用一轨 digest 充当另一轨）都是被禁止的
伪造路径。当前只钉 CLI `1.0.46` 一轨，SDK 轨完全缺席。

## Additional pinned disciplines

- **descriptor digest 零伪造**：必需、无默认、包内不生成不猜测；测试 fixture
  （`sha256:` + `aaa…`/`a…`）明确注明非真实。
- **版本钉死不追新**：`1.0.46` 是 changelog 静态 pin；升级只能走上面的六件套，
  且 changelog 证据须重新核实（本轮核实时点 2026-10-07）。
- **recover 永久缺席**：ACP 重开无文档证据——这不是暂时缺口，而是本包的
  合同；resume 永远是桥的 continuation（`agent-box.grok-continuation@1` /
  `grok-build-continuation`），不是 provider 的恢复面。headless `-r`/`-c`
  永远不得推断为 ACP continuation。
- **authenticate 扩展门**：客户端发起的 xAI 扩展（methodId=xai.api_key|
  cached_token，_meta.headless）未实现前 typed-refused；标准 ACP
  server→client 鉴权链永远不得推断；凭据（grok login / XAI_API_KEY）零接触。
- **kill_task/get_task_output 缺席登记**：第一手页面未记载，不声明不推断；
  待本仓假端点全链门实测后回填。
- **真实进程边界**：本包测试不启动真实 grok 进程（规则 6/9）；受控假进程/
  假端点即可。真实进程验证、生产装配、门回填均为 NOT_RUN，登记于
  `tests/runtime-process-evidence.md`。
