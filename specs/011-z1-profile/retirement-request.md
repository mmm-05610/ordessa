# Retirement request — profile 旧声明面退役清单（S-08③ / 014 PA-7）

日期：2026-09-28。产出线：014 P-A（`codex/014-a-profile`）。性质：**只出裁定与
清单，不执行删除**（派单禁区；执行归集成波次，见 seams S-08）。格式沿用本目录
integration-request.md：逐项给出现状、消费者、测试、迁移归属与建议顺序，供用户
与 core 线逐条裁决。

---

## ① 仲裁裁定：`agent-box.profile@1` 唯一声明者 = profile-api

**裁定**：`agent-box.profile@1` 的唯一声明者选 **profile-api**
（`plugins/profile`，provider id `ordessa-profile`）；harness 侧
（`generic/profile_store.py` 的 `ProfileStore`，provider id `harness-profile`，
经 `harness-profile-store` entrypoint 与各品牌 façade）**全部退出声明**。

**依据与加载顺序证据**：

1. **双声明是已登记的活动冲突，不是潜在风险**。`plugins/profile/src/
   ordessa_profile/plugin.py:129-137`：`build()` 返回
   `contracts=(AgentBoxProfileV1,)+resource_providers`，同处注释明文记载
   "If another plugin declares the same id first, its load order wins — an
   integration arbitration point"。`specs/011-z1-profile/integration-request.md`
   契约声明仲裁行进一步记载 loader 规则：**先加载者赢、后者 FAIL**——两者并存
   不可用，必须裁掉一边，不存在"保留双轨灰度"选项。
2. **域所有权在 profile-api**：facet v2 descriptor/schema/compile/reset、
   会话选择/覆盖/清除、journal（planned/applying/confirmed/rejected/unknown）、
   mechanism policy、v1→v2 迁移全部在 `ordessa_profile`，且受 140 条测试门、
   边界门（只依赖 pacthold）与 12/12 反例门约束（011-z1 report 验证门表；
   014 P-A 复跑同数，见 P-A-report.md）。harness `ProfileStore` 是 v1 扁平
   `native_payload` 存储（`generic/profile_store.py`：digest/secret 扫描/
   revision CAS），无 facet/会话/策略语义，属于被替代面。
3. **消费面已按 profile-api 铺开**：桌面三包启用清单（seams S-01）是
   `ordessa.profile-api / ordessa.profile-frontend / ordessa.profile-chat`；
   `ProfilePluginServices`（17 操作域门面）是 contracts.md §3 指定的 wire
   面；TS 侧 `@ordessa/plugin-profile-api`（22 操作 client）与 B 线 PB-6
   glue（ProfileContributions 消费）都以 profile-api r2 SHA 为对接基准。
4. **harness 侧声明的实际持有点**（退役=同时摘除以下全部声明）：
   - `generic/factory.py` `build_registration(context, None)`：
     `PluginRegistration(resource_providers=(store,))`——裸
     `harness-profile-store` entrypoint 的声明点；
   - 品牌 façade 的 contract 级声明：`claude/profile.py`
     （`ClaudeProfileProvider.resolve` 校验 `AgentBoxProfileV1.contract_id`）、
     `hermes/profile.py`（`HermesProfileSelector` contract_id 声明）、
     `opencode/profiles.py`（`OpenCodeProfileAuthority`）、
     `pi/provider.py:35`（input_limits 把 `agent-box.profile@1` 记为必需输入
     (1,1)——**消费面**，随退役改为从 profile-api 的解析结果取得）。

**不裁给 harness 的理由（反证）**：若反向裁定，桌面三包、wire services 面、
B 线 glue、TS client 全部失去声明主体；v1 存储无 facet/会话语义，需把 v2 全域
反向移植进 harness——工作量与风险都更大，且违反 S-01 已确认的启用清单。

## ② 逐文件退役清单（执行=集成波次，非本包）

> "调用方/测试"列为 2026-09-28 本树 grep 实测；执行波次开工前须复核一遍。
> 每项标注退役后接续动作，避免"删了就断"。

### ②-1 harness 侧

| # | 文件 / 符号 | 调用方（生产） | 测试覆盖 | 迁移归属与接续 |
| --- | --- | --- | --- | --- |
| R1 | `generic/profile_store.py`（`ProfileStore`，`PROVIDER_ID="harness-profile"`） | `generic/factory.py`、`generic/__init__.py`、`generic/profile_provider.py`、`claude/profile.py`、`hermes/profile.py`、`opencode/profiles.py` | `tests/test_generic_profile_store.py`（revision CAS/secret 扫描）、`tests/test_core_identity.py:36`（import 断言） | 数据迁移：`<agent_box_home>/profiles` 文件树 → profile-api sqlite（迁移器归 profile 域，随执行波次实现并立迁移记录）；R3-R6 全部完成后本文件删除 |
| R2 | `generic/profile_manager.py`（`GenericProfileManager`） | `generic/factory.py`（被 `ProfileEnvelopeManager(manager,…)` 包裹）、`generic/__init__.py` | 随 factory 路径（`test_core_identity.py` 构造链） | 与 R1 同波删除；`ProfileEnvelopeManager` 的 profile 分支改指新所有者或退（装配归 core） |
| R3 | `generic/profile_selector.py`（`GenericProfileSelector`） | `generic/factory.py`（`resource_selectors=(…)`） | 同上 | 同波删除；选择 UI 消费 `ordessa.profile-frontend` |
| R4 | `generic/profile_provider.py`（`ProfileProvider = ProfileStore` 别名） | 仅 `tests/test_core_identity.py:39` | 同名测试断言 | 纯别名，随 R1 同波删除并更新 test_core_identity 的 import 断言 |
| R5 | `harness-profile-store` entrypoint（`pyproject.toml:19` → `entrypoints.py:create_profile_store`） | plugin discovery（`agent_box.plugins` 组）；`test_core_boundaries.py:15` 断言 entry 集合含本名 | `tests/test_core_boundaries.py:15-16` | 摘除 entrypoint 时**必须同波改** test_core_boundaries 的集合断言；codex/claude/opencode/hermes/pi 五个 entrypoint 不动（它们声明执行面，非 profile 声明） |
| R6 | `claude/profile.py`（`ClaudeProfileProvider`/`ClaudeProfileRef`/`ClaudeProjection`） | `claude/launch.py`、`claude/__init__.py`（`from .profile import ClaudeProfileProvider as _P`）；**014 P-A 的 `plugins/profile/tests/test_brand_matrix_pa5.py` 只读消费 `ClaudeProjection` 作品牌面** | `tests/test_claude_production_template.py`（模板面） | 品牌渲染面（`.claude/settings.json`/manifest 投影）语义由新 owner 承接或保留为纯渲染函数；**执行波次须同步改 PA-5 矩阵测试的 face import**（矩阵断言形状不变） |
| R7 | `hermes/profile.py`（`HermesProfileProvider`/Selector） | `hermes/launch.py`、`hermes/projection.py`、`hermes/__init__.py` | `tests/test_hermes_production_template.py`（模板面） | 同 R6 模式 |
| R8 | `opencode/profiles.py`（`OpenCodeProfileAuthority`/Ref） | `opencode/projection.py`、`opencode/provider.py`、`opencode/__init__.py` | opencode 系列驱动测试间接覆盖 | 同 R6 模式 |
| R9 | `pi/provider.py` 对 `agent-box.profile@1` 的 (1,1) 必需输入 | `PiProjection.command` 经 `request.resolved_inputs` 取 `PiProfile` | pi 系列测试间接覆盖 | 非声明点、是消费点：改为消费 profile-api 解析产物（DTO 形状 `PiProfile` 保留），随执行波次改 |

### ②-2 server-compat 侧（**退役执行归 B 侧波次统一做**，防 A/B 同文件互撞）

| # | 文件 / 符号 | 调用方（生产） | 测试覆盖 | 迁移归属与接续 |
| --- | --- | --- | --- | --- |
| R10 | `server_compat/profiles/repository.py`（`ProfileRecords`：`server_profiles` 表 writer：create/update_configuration/archive/clone_from/grant·revoke_subagent） | `server_compat/plugin.py`、`facade.py`、`composition.py`、`persistence.py`、`core_wire.py`、`profiles/service.py`、`execution/delegation.py`、`sessions/service.py`、`execution/inventory.py` | apps/server 多套件（`test_stage_a_server.py`、`test_posture_config_write.py`、`test_execution_inventory.py`、`test_delegation_*` 等，均为读/写该表的既有账） | **按 seams S-08 既有裁定归 B 侧波次**（`core_wire.py` 同文件 B 出 ① writer 退役清单，A 不碰）；迁移归属：server_profiles 存量行 → profile-api sqlite，迁移器+迁移记录随执行波次；`server_profiles` 表格式与 id 保持不变（AGENTS.md 规则 5） |

### ②-3 执行顺序建议（供集成波次排期）

1. 先落 profile-api 的存量数据迁移器（v1 文件树 + server_profiles 表 → sqlite，
   带迁移记录与回读核对）——迁移器就位前不删任何 writer。
2. 摘 R5 entrypoint + R4 别名 + 改 `test_core_boundaries.py` / 
   `test_core_identity.py`（同一提交，保持 harness 测试绿）。
3. 摘 R1-R3（factory 裸注册链）与 R6-R8 品牌 façade 的声明点；同波改 PA-5
   矩阵测试的 face import（R6 注记）。
4. R9（pi 消费点）与 R10（server-compat writer）分别随 pi 装配波次与 B 侧
   波次执行。
5. 全程与 S-01 装配联动：`ordessa.profile-api` 启用、`harness-profile-store`
   退出发现之后，再执行 2-3 步的删除。

## ③ 本包边界声明

本文件只产出裁定与清单；`plugins/harness/**`、`plugins/server-compat/**`、
`apps/server/**` 在 014 P-A 内零改动。PA-5 品牌矩阵对 `ClaudeProjection`/
`PiProjection`/`codex.production` 的消费是**只读**（测试 import，不改被测文件），
并在 R6 登记了退役执行时的同步改点。
