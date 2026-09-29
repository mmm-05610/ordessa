# runtime-preferences — 八家运行级参数配置适配（facet `assets.runtime-preferences`）

P-A of specs/015-runtime-preferences-memory。四组运行级参数（compaction / memory /
shell / retry）做成纯配置域：一个 facet 四 item，八家品牌 adapter（assess/compile/
verify + `registration_manifest()`），注册进 main 已有的 C2 贡献点
`harness.configuration-adapters`（`ordessa_harness.contributions`），应用链走 C4
`ConfigurationApplicationService.apply`。形制仿 `model-provider` 的 adapter 骨架，
只仿形制、不 import 其代码。

Evidence level: **E-doc（文档级起步）**。每个编译键在 `src/ordessa_runtime_preferences/keys.py`
携带一手引用（`docs/design/harness-configuration/` 固定官方快照 2026-09-27 + 两条
2026-09-28 定点取证：opencode 官方 config 文档、qwen settings @ 固定提交）。逐键升级
靠固定源码/受控探针；未核实的生效方式一律 `unknown`，不写热更。

## 模块

| 文件 | 内容 |
| --- | --- |
| `types.py` | typed 判别面：AdapterContext / PreferenceRequest / Assessment / CompileIntent / IntentSet / Refusal / Verdict |
| `keys.py` | **单一事实源**：八家×四组 32 格三态结论 + 逐键 native path / canonical 映射 / applyMode / admin-only / 证据引用；AR-5 memory 契约键 |
| `common.py` | canonical 词表、字节稳定渲染（JSON/TOML）、版本门（文档级评估窗，不假装 pin）、reconfiguration 词表（含 `unverified`） |
| `engine.py` | 共享 assess/compile/verify：cell 结论→类型化行为；未映射参数/未知组/admin 键一律显式拒绝 |
| `{brand}.py` ×8 | pi / codex / claude / hermes / opencode / dsh / qwen / kilo：品牌绑定 + `registration_manifest()` |
| `bridge.py` | 本地类型→`ordessa_harness_api` C2 类型（descriptor / SetField / Match），payload schema `runtime-preferences.item.v1` |
| `plugin.py` | 插件声明面：八 adapter 进 `harness.configuration-adapters` contribution batch |
| `facet.py` | profile facet 四 item（原子整项覆盖）、注册 payload、`addEditor` 声明 manifest、AR-5 memory 契约面 |
| `session.py` | 会话整项覆盖/两会话隔离/切 profile 清覆盖语义 |

## 边界（静态门在 tests/）

适配器纯函数：不读 HOME、不触网、不 spawn、不写文件、secret 只携带 `ref://` 引用。
品牌模块不 import harness/server 契约包。请求级参数（reasoning effort、service tier、
请求 retry/stream timeout、provider 端点 options）归 model-provider 域——codex 的
`model_providers.<id>.*` 子树整族拒绝（spec §4 裁定 3）。admin 纠缠键（Codex
shell_environment_policy、Claude env 对象、Qwen executionSandbox 等）标 admin-only：
不进 claims、编译拒绝、编辑面禁用并说明。

## 已登记的事实冲突与限制

- **qwen/memory 与 spec F3 冲突**：固定提交官方文档记录 `memory.enableManagedAutoMemory`
  （后台记忆抽取，默认开）等真记忆键；spec F3"Qwen 记忆=静态指令陷阱"针对的是 QWEN.md
  的"memory"称谓。两键族并存，本包按官方证据判"可用"并登记待主会话复裁（影响 P-B 对
  qwen 的默认挂载决策）。
- **kilo.jsonc 为 JSONC**：结构化写不保留注释（已登记限制）。
- **dsh 无单一写入目标**：Cordis 按包装配，文档级无法钉出目标——catalog 格子记
  "可用（文档级）"，编译面诚实拒绝。

## 验证

`.venv`（main 工作树标准 venv）下：
`python -m pytest plugins/assets/runtime-preferences -q`
（tests/conftest.py 自插 `src` 路径，不需要 pip install 本包。）
