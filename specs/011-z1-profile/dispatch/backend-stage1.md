# Z1 后端阶段 1 派单简报（单包：plugins/profile Python）

执行者：单包实施子代理。**只允许修改 `plugins/profile/**`（本阶段仅 Python 部分）与
`specs/011-z1-profile/evidence-backend-stage1.md`。** 其他任何包/树/文档不得改动。
主代理负责审阅、验证与 git；你负责实现与测试。

## 工作目录与环境

- cwd：`/home/maoqh/projects/ordessa/worktrees/011-z1-profile`（分支 codex/011-z1-profile，勿切分支、勿 commit——主代理负责 git）。
- venv：`.venv`（已装 pacthold 2.0.0a1 editable + pytest）。一切测试用 `.venv/bin/python -m pytest`。
- 旧实现只读副本：`/tmp/old-profile-baseline/plugins/profile`（源 `b77f9f23cb`）；
  也可 `git show b77f9f23cb:plugins/profile/<path>` 读取。
- 设计输入（必读，产品语义以此为准，不得自行更改）：
  - `docs/design/profile-v2/spec.md`（US1–US4、不变式）
  - `docs/design/profile-v2/data-model.md`（实体/解析算法/合并例/秘密/迁移）
  - `docs/design/profile-v2/contracts.md`（facet descriptor、前端贡献、服务操作表）
  - `docs/design/profile-v2/application.md`（链路、Harness 端口语义、不假装跨进程事务、reset、恢复）
  - `docs/design/profile-v2/checklist.md`（G01–G20 反例矩阵）
  - `docs/design/profile-v2/test-scenarios.md`（反例场景表）
- 平台 SDK 事实：`packages/pacthold/src/pacthold/extensions/api.py`
  （PluginDescriptor/PluginContext/PluginRegistration）、`work_core/registry.py`
  （ResourceProvider/ProviderDescriptor）。入口组名保持 `agent_box.plugins`。

## 硬边界（违反即返工）

1. 不 import `ordessa_server*`/`ordessa_harness`/兄弟插件；只依赖 pacthold。保留
   `tests/boundary_check.sh` 门禁并让它继续通过。
2. 不修改 `packages/pacthold`、`apps/server`、`plugins/harness` 或其他任何包；裸宿主不改（PV-05）。
3. 不伪造运行证据：没有真实 Harness 端口确认时，任何 API 都不得返回“已应用成功”。
   DB 读回、退出码、请求已发送均不算应用证明（application.md §2）。
4. 不删旧测试断言换绿；v1 语义被 v2 设计明确改变的（如 read-back 证明），按“拆分存储证据
   与运行证据”改造并在证据文件里逐 ID 说明，不得静默跳过。
5. 测试数据根用临时目录；不读真实用户配置/凭据。

## 任务

### A. 移植 v1（保真）
把 `/tmp/old-profile-baseline/plugins/profile` 的 Python 源码与测试迁入本树
`plugins/profile/`（`pyproject.toml`、`src/ordessa_profile/*`、`tests/*`）。
先让 `.venv/bin/python -m pytest plugins/profile/tests -q` 全绿（70 个基线）。
迁移后 tests 目录留在 `plugins/profile/tests/`。

### B. v2 公共契约模块（`ordessa_profile/contracts.py`，可导入公共面 — profile-api 的 Python 部分）
按 contracts.md §1 与 data-model.md §1 冻结实际类型（dataclass，带校验）：

- `FacetDescriptor`：facet_id（`^[a-z0-9][a-z0-9._-]*$`）、api_major(int)、schema_version(str)、
  label、description、category、order、item_descriptors(tuple)。
- `ItemDescriptor`：item_id、value_schema（受控 JSON-schema 子集声明，见下）、optional(bool)、
  override_supported(bool)、sensitivity(`non-secret`|`opaque-reference`)、
  effect(`configuration`|`capability-selection`|`permission`|`instruction`)。
- value_schema 受控子集：`{"type":"string|integer|boolean|array<object>",
  "enum":[...], "items":{...}, "minItems","maxItems","minimum","maximum","default","title","description"}`
  ——实现一个纯函数校验器；**未知字段拒绝**（正反例）。
- 值状态四分（PF04）：显式 UNSET 哨兵类型（`Unset`，序列化为不存在）、显式值
  （null/[]/false 是合法显式值）、disabled（`{"disabled": true}` 形态或等效类型）、
  provider absent（注册表缺席，非存储态）。提供可辨来源的投影。
- `Applicability`：`supported|unsupported|unknown`（三值，unknown 不得当 supported）。
- `FacetProviderV2` Protocol（v2 面；保留 v1 FacetProvider 兼容适配器，见 D）：
  - `descriptor() -> FacetDescriptor`
  - `applicability(capability_facts: Mapping) -> Applicability`（只消费真实能力事实）
  - `validate(items: Mapping[item_id, value], reference_facts) -> tuple[Violation,...]`
    （纯函数，不 spawn/不写文件/不发请求）
  - `migrate(old_schema_version, stored_items) -> Migrated(old_items) | Unsupported(reason)`
    （纯函数）
  - `compile(resolved_items, target_facts) -> CompileResult`
    （产物 = tuple[ConfigIntent]，只声明本 facet 拥有的 native configuration intent）
- `ConfigIntent`：`intent_id`、`facet_id`、`item_id`、`op('set'|'reset')`、`value`(set 时)、
  `native_key`、`source`（`profile@rev`|`session-overlay@rev`）、`request_hash`。
- `AppliedReceipt`：operation_id、session_ref、runtime_generation、config_digest、
  profile_revision、overlay_revision、policy_revision、provider_generations、
  evidence_kind、confirmed_at、execution_id?。
- `ApplicationJournalEntry`：operation_id、session_ref、state
  (`planned|applying|confirmed|rejected|unknown`)、failure来源、已完成步骤的非秘密引用、
  时间戳。状态迁移只能走类型化方法。
- `SessionRef`：frozen dataclass，字段 `realm`（服务域所有者标识）、`harness_id`、
  `native_session_key`、`session_uid`（稳定主键）。提供 `from_parts(...)` 与
  `routing_key()`；文档明确 channelId 只是短期路由，不能当持久会话 ID（正反例：
  跨 realm 同 native key 的两个 SessionRef 不相等、不串写）。
- `MechanismPolicy`：realm、revision(int, CAS)、facet_enabled: Mapping[str,bool]、
  allow_user_override_writes_global: bool、allow_user_override_writes: Mapping[str,bool]、
  含输入校验（未知 facet 键在注册语境校验；policy 本身不含秘密/执行权限）。
- `HarnessConfigPort` Protocol（消费接缝，**本阶段只定义类型 + 缺席语义**，
  真实实现由 C0 harness-api 发布后消费）：
  - `inspect(target) -> InspectResult`（generation/capabilities/evidence）
  - `plan(target, desired_intents, reset_intents, operation_key) -> PlanResult`
    （`live-update|restart-resume|blocked(per-item reason)`）
  - `apply(plan, fence) -> ApplyOutcome`（`confirmed receipt | rejected-unchanged | unknown`）
  - `reconcile(operation_key, target) -> ReconcileResult`
  fence 由服务端事实构造；客户端不能提供可信 fence（类型上体现：fence 来自 port.inspect）。
- `ProfileServiceError`/复用 `ProfileError`：新增稳定错误码
  （`POLICY_REVISION_CONFLICT`、`OVERRIDE_WRITES_FORBIDDEN`、`APPLICATION_PORT_ABSENT`、
  `OPERATION_KEY_REUSED`、`NAME_CONFLICT`、`SESSION_REF_AMBIGUOUS`、`LEGACY_RECEIPT_UNVERIFIED` 等）。
- 所有公共类型放进 `ordessa_profile.contracts` 并从包 `__init__` 导出；写
  `tests/test_contracts.py`：未知字段拒绝、重复 key 拒绝、越权 context 拒绝、
  Applicability unknown 阻止应用、Unset≠null≠[] 的正反例。

### C. MechanismPolicy 服务（`ordessa_profile/policy.py` 新建）
- 存储：新表 `profile_mechanism_policy`（realm、revision、facet_enabled_json、
  allow_global、allow_per_facet_json、updated_at），增量迁移加入 schema 账本（v2）。
- `get(realm)`、`update(realm, patch, expected_revision, caller)`：
  CAS 冲突 → `POLICY_REVISION_CONFLICT`；impact preview（受影响 Profile/会话计数）
  在 update 响应中返回（PS05）。
- 语义（G03/G04）：禁用 facet 不删数据，隐藏编辑面 + 下轮需要该 facet 时给 blocker；
  `allow_user_override_writes=false` 时新/改 overlay 写被拒（`OVERRIDE_WRITES_FORBIDDEN`），
  但既有 overlay 可查看、可清除；策略不赋予任何运行权限。
- policy 修订进入 ConfigIntent 快照校验字段（写入 journal/receipt）。

### D. 解析 v2 与 facet 兼容适配（`resolution.py`、`facets.py` 升级）
- 值来源投影三元：`profile@revision` / `session-overlay@revision` /
  `target-default@fingerprint`（默认值指纹来自 provider descriptor 的 default 声明）。
- 差异计算 `plan_switch(current_resolution, target_resolution) -> tuple[ConfigIntent]`：
  A 有 B 无 → reset intent（不能靠“过滤字段”让差异消失，G08 正反例）；
  B 有 A 无 → set；同 item 值不同 → set。数组不深合并（item 粒度由 provider 声明）。
- v1 `FacetProvider` → v2 适配器：`session_apply` 字符串语义映射为 v2
  applicability/compile；v1 provider 的 validate_value 继续生效；适配层属于本包，
  不要求旧 provider 改代码。v2 provider 直接支持。
- FacetRegistry v2：注册时记录 owner（由注册调用方注入 plugin id，不信 provider 自报）；
  重复 facetId 拒绝不变；**provider generation 门禁**：注册表维护 generation 计数，
  每次 register/unregister 递增；持有旧 generation 的晚到回调/编译结果必须被拒
  （`FACET_GENERATION_STALE`，正反例）。

### E. 会话 v2 + 应用 journal（`sessions.py` 升级、`application_journal.py` 新建）
- 存储迁移（v2，可重跑、不重建库）：
  - `profile_sessions` 增列 `session_uid`（新主键语义）、`realm`、`native_session_key`；
    旧行迁移时生成 uid=`legacy:<session_id>`，realm 默认 `'local'`，native_session_key=旧 id。
  - 新表 `profile_application_journal`（operation_id、session_uid、state、plan_json
    （非秘密）、failure、evidence_refs_json、created_at、updated_at）。
  - 新表 `profile_applied_receipts`（operation_id、session_uid、receipt_json、confirmed_at；
    receipt 不含秘密）。
  - 迁移规则：旧 `switch_state='settled'` 的历史不改写，但在读取投影中标记
    `evidence='legacy-unverified'`（data-model.md §5）；**不得升级为 confirmed**。
  - 副本迁移跑两次幂等；碰撞（同 uid 不同数据）→ 类型化拒绝，不自动合并（G17）。
- `SessionService` v2：
  - open/select 用 SessionRef；跨 realm 同 native key 两个会话互不串写（G02 反例）。
  - select（登记 pending）：seq 递增；B→C 替换 B，旧预检失效；再次选择当前 Profile
    不清 overlay；pending 状态本轮不变（PA01）。
  - `begin_turn_application(session_uid, operation_key)` —— 下一轮准入边界的入口：
    1. 解析有效 selection（pending 优先，归档绑定取归档时固定 revision）；
    2. 构造完整差异 intents（含 reset）；provider 缺席/unknown → 整体 blocked（零原生写入）；
    3. 写 journal `planned`；
    4. `HarnessConfigPort` 缺席 → journal 保持 planned、返回 typed
       `APPLICATION_PORT_ABSENT` blocked（不假绿，不发送放行）；
    5. 端口存在：plan → 任一 unsupported → `rejected`，零写入；否则 apply。
    apply `confirmed`：先 commit receipt + 绑定/overlay 清理（成功切换才清 overlay，
    G07），journal `confirmed`；`rejected-unchanged`：保留一切，返回原因；
    `unknown`：journal unknown，阻发送，等 reconcile。
    同 operation_key 不同 payload → `OPERATION_KEY_REUSED`。
  - `reconcile(operation_id)`：经端口查证 → confirmed（补 receipt）/仍 unknown；
    不重放消息、不自动重发。
  - 外部成功+本地 commit 失败注入点：持久化接缝注入（tests/injections.py 已有先例）
    → journal unknown、send 计数 0（G10/G11 反例）。
  - overlay 写前检查 policy（C 语义）+ provider schema 校验 + sensitivity。
  - 保留 v1 全部 idempotency 语义，键升级为 (scope, key, request_hash) 同 key 异 payload 拒绝。
- journal 状态机类型化：非法迁移抛错；崩溃恢复只能从 journal 事实出发，不猜（G11）。

### F. 名称唯一与归档（profiles.py 升级）
- create/rename 时同 (realm, harness) 活动名称 NFC+trim+casefold 唯一 → `NAME_CONFLICT`；
  旧重名数据不强制改名（迁移不改写）；归档恢复遇活动名冲突 → 要求先改名（PM05）。
- 归档语义维持 v1（首版无硬删）；归档绑定的会话固定归档时 revision，仍走正常应用校验。

### G. plugin.py 真实注册（PV-05）
- `build(context)` 返回带实际组件的 `PluginRegistration`：
  - resource provider（ProviderDescriptor(id="ordessa.profile", ...)）承载 Profile
    领域资源解析（profile/ref 只读投影，不含秘密）；
  - 服务门面 `ProfilePluginServices`（profiles/policy/sessions/facets/resolve_preview）
    以 contracts 中冻结的类型对外；用 transport_operations 或 contracts 注册均可，
    以 SDK 实际接受为准（读 catalog.py 校验逻辑）。
- 零 facet 注册时全部管理操作可用（G01）；`describe_facets` 返回脱敏可编辑目录。
- `resolve_preview(profile_id, revision, overlay set?)` 零副作用返回各项来源/冲突/待运行验证。
- 数据库路径用 `context.plugin_data_dir`；discovery 阶段不写盘（PluginContext 语义）。

### H. 测试与证据
- 全部旧测试保真迁移并通过；对 v1 read-back 证明类断言按“存储事务成功”与
  “运行证明”拆分，逐 ID 在证据文件登记说明。
- 新增 counterexample 覆盖（对 checklist）：G01、G02（双 realm）、G03、G04、G05、G06、
  G07、G08、G13（卸载隐藏保留值、过滤不消灭差异）、G15（sensitivity/digest 无秘密）、
  G17（迁移幂等/碰撞门禁）；G09/G10/G11/G12 的 Profile 侧部分（journal/fence/unknown/
  跨进程隔离语义），Harness 端口用**受控测试适配器**（显式标注 controlled fixture，
  不得冒充真实 Harness 验证）。test-scenarios 表中“输出中多次切换”“逐项覆盖”
  “应用拒绝”“外部成功本地失败”“会话身份重名”“迁移”六行的服务断言。
- 敏感断言：digest 不含秘密值；错误/日志只出现字段 ID。
- 受控第三方 facet proof（PV-03/PV-06 的扩展性证明）：tests 内定义一个测试域 facet
  provider（v2 协议），注册→describe→保存值→resolve→compile 全链可用，且
  **Profile 核心零改动**（测试断言核心模块源代码不含该 facet 业务名，或以注册路径证明）。
- 写证据文件 `specs/011-z1-profile/evidence-backend-stage1.md`：
  每组命令、退出码、通过/失败数、旧→新测试 ID 对照表、v1 语义改动清单、
  受控 fixture 与真实验证的边界声明。

## 完成定义（本阶段）
1. `.venv/bin/python -m pytest plugins/profile/tests -q` 全绿，数量 ≥ 旧 70 + 新增反例。
2. `bash plugins/profile/tests/boundary_check.sh` 通过（若旧脚本路径变化需保留等效门禁）。
3. 上述 B–G 每项都有对应测试 ID；无跳过（skip）、无删断言。
4. 证据文件完整。
完成后：输出变更文件清单、测试统计、证据文件路径、遗留缺口清单（如有）。
不要 git commit；不要动其他目录。
