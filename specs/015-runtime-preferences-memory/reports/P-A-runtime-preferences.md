# P-A report · runtime-preferences（`plugins/assets/runtime-preferences`）

- 分支：`codex/plugin-runtime-preferences`（基于 main `526be71b21` 直接拉，未 merge
  任何插件分支）。
- 写入面遵守：本包目录 + 本报告；其余只读。无越界改动。
- 测试留痕：`python -m pytest plugins/assets/runtime-preferences -q` →
  **151 passed**（conformance 94 / brand semantics 36 / facet+isolation 15 /
  C4 端到端 6）。tests/conftest.py 自插 `src` 路径，本包未 pip-install（不触碰共享
  venv）。测试解析 `ordessa_harness_api`/`ordessa_harness`/`ordessa_server` 来自标准
  venv（main 检出，与本分支基线同一提交）。

## 任务勾选对照（tasks.md，不删行）

| 任务 | 状态 | 证据 |
| --- | --- | --- |
| RA-1 域骨架 + facet 注册进 C2 + 重叠注册拒 | ✅ | `plugin.py`（八 adapter 进 `harness.configuration-adapters` batch）；`tests/test_adapters_conformance.py`：`test_eight_brands_register_into_the_real_c2_registry`、`test_identical_registration_overlap_is_refused_by_real_registry`、`test_facet_does_not_collide_with_the_existing_facet_vocabulary` |
| RA-2 八家品牌骨架（三方法+manifest+common 字节稳定渲染） | ✅ | `{brand}.py`×8 + `engine.py` + `common.py`；门形照 model-provider `test_adapters_conformance.py:80-103`（真 C2 注册表驱动，只仿形制不 import）：重叠注册拒/同 facet 版本区间重叠拒/不相交区间接受 三用例全绿 |
| RA-3 逐家逐组编译表（三态+证据） | ✅（文档级） | `keys.py`（单一事实源，逐键引用）+ 本报告 §逐格结论表 |
| RA-4 管理员约束排除 | ✅ | `keys.py` admin_only 标记；`test_descriptor_claims_cover_compiled_keys_only`（admin 键不可 claim）、`test_admin_only_keys_never_compile`、`test_admin_entangled_values_refuse_with_admin_reason`、`editor_registration_manifest()` disabledItems（编辑面禁用+理由） |
| RA-5 profile facet 四 item + 编辑组件 | ✅（声明面） | `facet.py`：四原子 item、默认值、整项覆盖校验、`facet_registration_manifest()`、`editor_registration_manifest()`（= `ProfileContributions.forScope().addEditor(...)` 消费的声明）；**编辑组件的实际注册是 Profile 侧动作**（profile-api v2 不在 main 基线，见未决项 U-1） |
| RA-6 C4 应用链 + 逐键 applyMode + 失败反例 | ✅ | `tests/test_c4_end_to_end.py`：真 host（`ordessa_server.bootstrap.build_runtime`）+ 受控 runtime，opencode 压缩参数 plan→permit→物化→回读→Confirmed；失败反例：codex retry→`CAPABILITY_UNSUPPORTED` 显式拒绝（非静默）、未声明键→`INVALID_FRAGMENT`、dsh 无目标→拒绝、陈旧 revision→`STALE_PLAN`。applyMode 逐键在 `keys.py`（kilo restart 官方明文；其余如实 unknown，`test_unverified_dominates_and_never_claims_hot_reload` 防伪） |
| RA-7 隔离与反例 + golden | ✅ | `tests/test_facet_and_isolation.py`：两会话四组参数互不影响反例、整项覆盖不合并、切 profile 清覆盖、golden 转录字节稳定；`test_brand_semantics.py` golden 渲染钉死 |
| RA-8 report | ✅ | 本文件 |

## 逐格三态结论表（八家 × 四组）

状态词：**可用**=官方文档有明确入口（含键名证据）；**不支持**=有证据的负向结论；
**未知**=本轮证据不足以双向断言。编译=本证据级实际编译的 canonical 参数。
生效方式：无官方声明一律 `unknown`，不写热更。

| 品牌 | compaction | memory | shell | retry |
| --- | --- | --- | --- | --- |
| **pi** | 可用。编译 enabled→`compaction.enabled`、reserveTokens→`compaction.reserveTokens`、keepRecentTokens→`compaction.keepRecentTokens`。生效 unknown。证据：pi settings.md @ `2b0a123d`（source-index.json:pi，68 键） | 不支持。settings 索引无记忆族；Pi 无原生长期记忆（INV §2/§3） | 可用（受限）。编译 shellPath→`shellPath`、commandPrefix→`shellCommandPrefix`。生效 unknown | 可用。编译 enabled/maxRetries/baseDelayMs→`retry.*`；`httpProxy`/`transport`/`httpIdleTimeoutMs` 等记录不编译（形状未定）。生效 unknown |
| **codex** | 可用。编译 thresholdTokens→`model_auto_compact_token_limit`。`compact_prompt`（提示词内容）不预设；`features.context_management.experimental_mode` 实验键记录不编译。生效 unknown | 可用。编译 enabled→`memories.generate_memories`、extractionModelRef→`memories.extract_model`；`memories.use_memories`/consolidation/预算族记录（预算为条目/天数，token 预算不忠实→不映射）。生效 unknown | 可用（含 admin 排除）。编译 enabled→`features.shell_tool`、timeoutMs→`background_terminal_max_timeout`；**admin-only**：`shell_environment_policy.*`（F8 权限行纠缠）、`sandbox_*`（隔离=权限域）。生效 unknown | **不支持（边界）**：唯一重试/流超时键 `model_providers.<id>.request_max_retries`/`stream_max_retries`/`stream_idle_timeout_ms` 在供应商子树=请求级，按 spec §4 裁定 3 归 model-provider（claims 不含该子树，测试钉死） |
| **claude-code** | 可用。编译 enabled→`autoCompactEnabled`；`autoCompactWindow` 语义未定→记录不编译；env 侧 `DISABLE_AUTO_COMPACT` 等 admin-only。生效 unknown | 可用。编译 enabled→`autoMemoryEnabled`；`autoMemoryDirectory` 是路径键不预设。生效 unknown | 可用（含 admin 排除）。编译 shellPath→`defaultShell`；**admin-only**：`env` 对象整体（F8 环境/运维管理员项；且 model-provider 在同文件持 env claim——双重理由不碰）。生效 unknown | 未知。settings 索引（234 键）无 retry 族；env 仅 `CLAUDE_CODE_RETRY_WATCHDOG`（语义未核）；API 超时/重试 env=请求级归 model-provider |
| **hermes** | 可用（文档级）。`auxiliary.compression.provider` 锚点 + INV §4 compression 策略/context engine；YAML 键路径本轮未自动提取→**编译面诚实拒绝**（测试钉死），逐键升级 | 可用（文档级）。INV §4 persistent memory + memory provider 启用/预算；键路径未提取→编译面拒绝 | 可用（文档级）。TERMINAL_* 族（SSH/容器/持久 shell，source-index.json:hermes）+ INV §4；键路径未提取→编译面拒绝；部署凭据不混入 | 未知。索引（54 键）与语义表均无 retry 族（fallback=模型选择非重试）；R9 覆盖有限不下负向断言 |
| **opencode** | 可用。编译 enabled→`compaction.auto`、reserveTokens→`compaction.reserved`、keepRecentTokens→`compaction.preserve_recent_tokens`；`prune`/`tail_turns` 记录。生效 unknown。证据：schema 索引（84 键）+ 官方 config 文档（2026-09-28 定点取证） | 未知。spec F3 列 OpenCode 有原生 memory loader，但 schema 索引与官方 config 文档均无 memory 配置键——需固定源码核 loader 入口；不下支持/不支持断言 | 可用（受限）。编译 shellPath→`shell`（官方 config 文档 2026-09-28：交互终端与 agent 工具调用所用 shell）。生效 unknown | 未知。schema 与官方文档均无重试族；provider options timeout/chunkTimeout=请求级归 model-provider；/etc/opencode 管理层不碰 |
| **dsh** | 可用（文档级）。`compaction-basic`/`tool-result-pruner`/`spill`（INV §6，config-catalog @ `477b4f42`）。Cordis 按包装配、无单一文档化写入目标→**编译面诚实拒绝**（C4 反例测试钉死） | 不支持。config 目录（728 标识符）与 INV §6 均无记忆族 | 可用（文档级）。`shell-env`/persistent bash/SSH/terminal（INV §6）。同左：无单一目标→编译面拒绝 | 可用（文档级）。`llm-pi-ai` retry（INV §6）；升级时先核 provider 级 vs 请求级边界；编译面拒绝 |
| **qwen** | 可用。编译 thresholdPercent→`context.autoCompactThreshold`（/100 转换，官方文档明文）；`compactionModel` 需模型引用解析→暂不编译；`model.chatCompression.*` 记录。生效 unknown | **可用（与 spec F3 裁定冲突→登记复裁）**。编译 enabled→`memory.enableManagedAutoMemory`（固定提交官方文档：后台记忆抽取，默认开）；`memory.enableManagedAutoDream`/team memory 记录。QWEN.md 的"memory"称谓=静态指令陷阱（F3 依据）与该键族**并存且不是同一机制**。详见 §事实冲突 | 可用（含 admin 排除）。编译 timeoutMs→`tools.shell.defaultTimeoutMs`；**admin-only**：`tools.executionSandbox`（操作员级，官方明文需重启——八家少数有明文生效方式的键）、QWEN_SANDBOX* 环境变量。生效：executionSandbox=restart（admin 不预设），其余 unknown | 未知。无 settings 重试键；`QWEN_CODE_UNATTENDED_RETRY` 是 env 开关（canonical 词表不覆盖 env 注入）；generationConfig 内 timeout/maxRetries=请求级归 model-provider |
| **kilo** | 可用。编译 enabled→`compaction.auto`、reserveTokens→`compaction.reserved`、keepRecentTokens→`compaction.preserve_recent_tokens`（schema 与 opencode 同形）。**生效=restart**（INV §8：官方 CLI 文档要求修改配置后重启）——测试钉死不回退 | 不支持。schema 索引（106 键）无记忆族；snapshot=历史非记忆（INV §8） | 可用（受限）。编译 shellPath→`shell`。生效=restart（INV §8） | 未知。schema 索引无重试族 |

证据源缩写：INV = `docs/design/harness-configuration/harnesses.md`（2026-09-27 固定
官方快照盘点）；source-index.json 各条目含官方 URL/抓取时间/SHA-256。两条 2026-09-28
定点取证：opencode `opencode.ai/docs/config/`（compaction.auto/reserved/prune、shell
键语义、无 memory 族、managed 层）；qwen `settings.md @
302e7d88ef366991295e41dd9b158a13ab29cd74`（context.autoCompactThreshold 默认 0.85、
memory.enableManagedAutoMemory 默认开、tools.executionSandbox 需重启、QWEN.md
"memory"称谓）。

## 事实冲突与限制（如实登记）

1. **qwen/memory 与 spec F3 冲突（需主会话复裁）**：F3 裁定"Qwen 的 memory=静态指令
   陷阱"；固定提交官方文档同时记录了 `memory.enableManagedAutoMemory`（后台记忆抽取，
   默认开）、`enableManagedAutoDream`、team memory 等真记忆键。本轮按官方证据将格子判
   "可用"，并把 F3 的原始依据（QWEN.md"memory"称谓）作为并存事实保留。**影响 P-B**：
   若复裁确认 Qwen 有原生自动记忆，P-B 对 qwen 的"无原生记忆默认挂载"应改为默认不挂
   （配置可改）。
2. **kilo.jsonc 为 JSONC**：结构化写（json codec）不保留注释。已作为限制登记；若
   上游注释承载语义，升级时需换 content 型通道。
3. **dsh 无单一文档化写入目标**：Cordis 按包装配（bundle patches→profile patch→home
   patch→CLI patches）。catalog 格子记"可用（文档级）"，编译面拒绝直到固定源码钉出
   写入路径。
4. **hermes YAML 键路径未自动提取**（54 个表格标识符不冒充完整配置集合，sources-and-gaps
   R9）：三个可用格的编译面全部诚实拒绝，靠固定源码升级。
5. **版本门槛未 pin（sources-and-gaps R1 未决）**：C2 descriptor 的 `native_versions`
   是**评估窗** (0.1.0–2.0.0)，不是支持声明（docstring 与 report 双处声明）；真实门在
   catalog 三态。同 facet 后续注册可用不相交区间并存（conformance 用例证明）。

## 未决项

- **U-1 profile 编辑组件的实际注册**：`editor_registration_manifest()` 已按 profile-v2
  契约 §2 声明（facetId/componentKey/category/order/disabledItems），但
  `ProfileContributions.forScope(scope).addEditor(...)` 的实际调用属 Profile 侧
  （profile-api v2 在 `codex/014-a-profile`，不在本包 main 基线）。属 integration
  （IR-4 并合后接），不越界代写。
- **U-2 AR-3/AR-4 不涉及本包**（P-B 的消费台账项）；本包对 AR-5 的契约面已定死：
  `facet.memory_facet_contract()`（enabled/budgetTokens/extractionModelRef，纯参数，
  结构上无置备键；P-A 缺席时 P-B 回落自身默认值的反例语义见 api-requests.md）。
- **U-3 逐键证据升级**：所有"记录不编译"键（pi transport/httpProxy、codex
  autoCompactWindow、qwen compactionModel 等）需固定源码/受控探针升级后重判。

## known-issues 登记清单（请主会话记入 docs/known-issues.md）

1. runtime-preferences：文档级证据起步——32 格中 4 格"不支持"、9 格"未知"、19 格
   "可用"；可用格中仅 kilo 族与 qwen executionSandbox 有官方明文生效方式
   （restart），其余生效方式 unknown，产品侧必须按"需计划重启"处理，不得宣称热更。
2. runtime-preferences：qwen memory 键族与 spec 015 F3 裁定冲突（见上），复裁前
   P-B 对 qwen 的默认挂载决策应视为未定。
3. runtime-preferences：hermes/dsh 编译面在文档级全部拒绝（无钉出键路径/写入目标），
   属诚实边界而非缺陷；升级靠固定源码。
4. runtime-preferences：kilo 结构化写不保留 kilo.jsonc 注释。

## 边界与红线自检

- 写入面：仅 `plugins/assets/runtime-preferences/**` 与本报告。✅
- 不 import model-provider/harness 内部；只 import main 已有的公开契约包
  （`ordessa_harness_api`、`server_plugin_api`）。✅（静态门测试钉死）
- 无 secret 内容：引用串 `ref://` 纪律，封闭 schema 拒绝 secret 形键（`validate_json`
  looks_secret_name + 引擎校验 + 测试）。✅
- 不 fake green：失败反例（codex retry/dsh 无目标/陈旧 revision/未声明键/未识别版本）
  全部显式断言拒绝码与理由；无断言删除、无 skip 掩盖。✅
- 请求级参数边界（spec §4 裁定 3）：codex `model_providers.<id>.*` 子树不进 claims、
  编译拒绝（测试钉死）。✅
