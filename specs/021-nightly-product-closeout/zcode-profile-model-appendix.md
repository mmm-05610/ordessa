# 附录：稀疏 Profile 合成与独立模型应用的冻结契约（T01）

日期：2026-10-02。从属：`zcode-profile-model-closeout.md`（本文是其 §3 B.5 要求的
接口/恢复事实附录）。主会话冻结；A/B 子代理与 T04 依此实现，不得自行换架构。
引用行为基线：HEAD e560f7a19b 未提交树（见
`.cleanup-evidence/zcode-profile-model/t00-baseline-full.diff`）。

## 1. 方案选择（B.5：新增 beginTurnApplication，不复用 Profile prompt 边界）

选择 **方案 (a)**：在 `ordessa.model-provider` 注册
`modelProvider.beginTurnApplication`。理由：

- 方案 (b) 的既有后端 prompt 边界是 `profile.*` wire（`selectForSession` +
  `beginTurnApplication`），复用它会使独立选择传递依赖 Profile 插件与会话记录，
  直接违反 FR-01/B.4（无 Profile 不得偷建记录）。
- 方案 (a) 允许 model-provider 只声明"消费冻结意图"的薄入口，实际应用由产品
  共享入口执行（§3），不形成第二条真实 apply 链。
- 只实现 (a)，不同时实现 (b) 式的第二实际 apply 入口。

## 2. `modelProvider.beginTurnApplication` wire 契约

注册：`ordessa.model-provider` 插件（plugin.py 既有 Z3 方法旁）。**只排队消费，
不自行 apply**：服务端实现把实际应用委托给组合注入的 `TurnApplicationPort`
（§3.3）；端口缺席时 typed refusal（fail closed），不得回退旧
`ConfigurationServiceHarnessPort` 伪 readback。

请求（全部必填，除非标注 opt；未知/缺失/类型不符 → 422 typed error，不静默）：

```
{
  "target": {"serverInstanceId": str, "harnessId": str, "acpSessionId": str},
  "operationKey": str,            # 客户端生成的稳定提交键（复用 chooseForSession 的键）
  "expectedSequence": int | null  # opt；客户端已知队列 sequence，不匹配则 typed refusal
}
```

响应：

```
{
  "outcome": "ready" | "refused" | "unknown" | "no-intent",
  "target": <echo>, "operationKey": <echo>, "sequence": int | null,
  "reason": str | null,
  "application": {                # 仅 ready；全部为真实证据引用，非合成值
    "operationId": str,           # 共享 C4/应用 journal 的 operation id
    "nativeTarget": {"owner": str, "canonicalUid": str, "generation": int},
    "appliedRevision": str|null,  # C4 readback 的 applied_revision
    "evidenceRef": str            # journal/readback 证据引用
  } | null
}
```

语义（对齐 FR-06）：

- `ready`：本次 operationKey+target+sequence 的应用已确认（真实原生 readback
  与目标/owner/generation/目录版本吻合），意图已消费；prompt 允许。
- `refused`：零 prompt，应用被类型化拒绝；意图保留，可显式重试。
- `unknown`：零 prompt，不安全状态与新旧意图身份保留；**后续发送同样零 prompt
  直到 reconcile 观察**；不得因队列已 pop 而变 no-intent。
- `no-intent`：该 exact target 无冻结意图；客户端继续普通发送（Profile guard
  或直接发送）。
- 幂等：同 operationKey+target 重复调用 → 重放已记录结果，零新副作用；
  同键不同内容 → typed conflict（对齐 P10）。

## 3. 单一实际应用与双模式意图权威

### 3.1 意图权威（bound / unbound 两模式，单一权威无镜像双写）

配置项身份一律 `(facet_id, item_id)`；模型选择是
`("assets.model-provider", "choice")` 一项（`NativeProfileConfigPort._resolve`
已只接受这一项，products/server/src/ordessa_server_product/profile_configuration.py:96）。

- **Profile 绑定会话（bound）**：模型选择意图的权威存储是 Profile 会话
  overlay 表（`profile_session_overlays`）。组合在 `chooseForSession` 时经
  `TurnIntentSink` 端口把选择写成该会话 overlay（source 标
  `model-provider`，带 §4 的 action_seq/revision）。model-provider 队列仅作
  UI 投影，不是第二权威。
- **未绑定会话（unbound）**：意图权威是 model-provider 的 NextTurnSelector
  队列（进程内，重启即失——诚实语义，非持久化承诺）。
- 判定 bound 的依据是后端 native 绑定事实（neutral authority 的 canonical
  UID/owner 绑定），**不是**客户端 UI sessionId。

### 3.2 同项先后（用户动作顺序，非 guard/网络顺序）

- bound 模式：同一 Profile 会话内，`selectForSession` 与 overlay 写入共用
  会话级单调 `action_seq`（§4 迁移新增）。合成规则（逐项）：
  用户 overlay 与 Profile 声明项同项冲突时，**action_seq 大者胜**；
  Profile 切换只消费"mask 内且 action_seq 早于本次切换"的 overlay
  （FR-03"旧临时项"），晚于切换的 overlay 保留（M03）。
- unbound 模式：队列自身 sequence（newest-wins）已足够，无跨消费者。
- 迟到/乱序：任何消费路径只按 admission 冻结的 seq/mask/revision 判定，
  不猜测、不按到达顺序覆盖（B.7 反例见 §6）。

### 3.3 产品共享入口与单一 apply

- 实际应用统一经 neutral authority（`native.configuration` 端口）的 C4
  owner-plan 入口（`apply_prepared` 路径），共用 journal/FenceObservation；
  不建第二份真实结果 authority（FR-05/C01）。
- **bound 发送**：Profile 既有管线（`SessionService.begin_turn` →
  `NativeProfileConfigPort`）执行唯一一次合成应用，输入已含模型 overlay 项；
  model guard 不再单独 apply。
- **unbound 发送**：`modelProvider.beginTurnApplication` → 注入的
  `TurnApplicationPort`（产品实现）：以当前原生有效配置为基底 + 单模型项
  合成完整目标，经同一 C4 owner-plan 入口一次应用 + fresh readback 验证。
- 客户端 dispatch（T04 前端）：会话 bound → 仅 Profile guard 触发提交应用，
  模型侧只经 `queryChoice`/`reconcileChoice`（只读）更新 UI；unbound →
  模型 guard 调 `beginTurnApplication`。服务端 C4
  `one_active_session_operation` 围栏为后置防线：同会话并发第二 apply →
  BUSY，不产生第二副作用（M06 以副作用计数验收）。
- 资源目录/凭据解析复用 model-provider 既有 `profile_resolution`
  （payload+revisions 分离、admission 边界再校验），生产端口必须做 fresh
  readback（`runtime.observe` 语义），禁止以请求值合成读回（B.2/M13）。

## 4. A 侧恢复事实与 schema v3（幂等向前迁移）

`ProfileDatabase._migrate` 机制上新增 SCHEMA_VERSION=3（storage.py，纯加列
+回填，旧库/旧标识不变，C04）：

- `profile_session_overlays` 加列：
  - `action_seq INTEGER NOT NULL DEFAULT 0`——该次用户动作的会话级序号；
  - `revision INTEGER NOT NULL DEFAULT 0`——该行写入版本，每次 upsert 自增；
    同值重写也自增（同值重写=新意图，A.4）。
- `profile_sessions` 加列：
  - `action_seq INTEGER NOT NULL DEFAULT 0`——会话动作计数器，
    select 与 overlay 写入都先取再自增（同一事务）；
  - `admission_facts_json TEXT`——本次 admission 冻结的非秘密事实：
    `{"source_profile_revision", "item_mask": [[facet,item],...],
    "overlay_revisions": {"facet\u0000item": revision},
    "pending_seq", "base_identity", "operation_id"}`。
    `detail_refs` 只放引用，不塞状态（A.5）。

消费围栏（CAS，全部在事务内重读当前行）：

- 确认/对账只删除/结算 mask 内且 `revision` 仍等于 admission 快照的 overlay；
  revision 已变（应用期间新写，含同值重写）→ 保留，留给下一轮（P09）。
- success/rejected/unknown/commitfail 重读 session 行后再写：
  `pending_seq`/pending 字段只在与 admission 一致时更新；应用期间的新
  select（pending_seq 更大）不被旧快照覆盖（P08）。
- `_mark_needs_recovery` 只写安全状态字段，不回灌旧 pending/overlay。
- 有效基底：会话记录"最后确认的有效原生配置"身份（base_identity，来源
  journal/readback）；省略项的有效值来自基底，而非从 overlay 或最新
  Profile revision 推断（P03/P07/M05）。
- required/conflict 验证基于"当前有效基底+本次 patch"，不得只看稀疏 target。
- 原生首发（complete_target）仍要求完整有效目标：相同 desired 也必须走
  真实应用确认，不得以"已保存相同值"跳过（P11，既有 Pi 修复保持）。

## 5. B 侧队列围栏语义（NextTurnSelector）

- `resolve_next_turn` 不得在管线前 pop：冻结 (session, sequence) 后进入
  管线；仅 `applied`（含真实 readback 验证）才消费该 sequence；
  `refused` 保留意图；`unknown` 进入持久 blocked 状态——后续 resolve 对
  同会话继续返回 unknown+零 prompt，直到 reconcile 观察清除（M08）。
- 迟到结果（`late_result`）必须 session+sequence 全等才生效；晚到结果
  不得覆盖更新的选择或改动 UI 状态（M12）。
- choose/query/reconcile 保持只排队/只读（B.5）；operation key 必须含
  目录 version/generation 因子，禁止复用旧 `mp-` 无版本键（M10）。

## 6. 必补反例（与验收门对齐，A/B/T04 各自落地）

| 反例 | 门 | 归属 |
| --- | --- | --- |
| 同值重写（应用期间重写相同 overlay 值）后旧 apply 不清除它 | P09 | A |
| v2→v3 旧库迁移保记录、重启可恢复/对账 | C04 | A |
| 晚 pick 在对账/重复恢复场景不被旧操作消费 | P07/P08/P10 | A |
| 无 Profile：选择→应用→prompt，Profile 记录零增量 | M01 | T04 |
| Profile 卸载后普通会话/模型仍工作 | M02 | T04 |
| bound 同项最后动作胜（双向）+ 异项保留 + 单次 apply 副作用计数 | M03–M06 | T04 |
| 同 ID 不同 channel/owner/generation 不串路 | M09 | B+T04 |
| 目录/凭据/适配变化后旧 plan 拒绝（含无版本键反例） | M10 | B |
| 输出中排队不中断、下一轮生效 | M11 | B+T04 |
| unknown 持久阻塞（pop 后不得变 no-intent 放行） | M08 | B |
| 乱序回包/切页不消费旧或其他状态 | M12 | B+T04 |
| beginTurnApplication 字段 fail-closed + 幂等重放 | §2 | B |

## 6b. 主会话裁定（2026-10-02，T02/T03 完成后）

1. **端口缺席表达**：`beginTurnApplication` 在 TurnApplicationPort 缺席时返回
   `outcome="refused", reason="ADAPTER_MISSING"`（不抛 422）。对齐 FR-06
   Refused 与 C03（明确拒绝、零 prompt、可显式重试）。T03-B 已按此实现。
2. **幂等键客户端义务**：同一 operationKey 重放已记录结果（含 unknown/
   no-intent）；显式重试必须换新 operationKey。前端契约照此。
3. **旧 `resolve_next_turn` 的 R1 语义**（解析目录最新版本）保留：它无生产
   消费者，生产提交路径只有 `beginTurnApplication`（按 admission 冻结版本）。
4. **T04 增补写权**：为完成 §3 接线，T04 允许两处最小插件侧改动——
   (a) `choose_for_session` 增加可选 `TurnIntentSink` 调用（组合注入，缺席
   不影响 unbound 语义）；(b) 若 Profile 缺少服务级 overlay 写入公开 API，
   允许在 `plugins/profile/src/ordessa_profile` 增加最小公开方法（复用
   T02-A 的 action_seq/revision 机制），逐项报告。

## 6c. Codex 复审修复契约（2026-10-02，F1/F2/F3）

来源：`codex-zcode-review.md`（REQUEST_CHANGES）。以下语义冻结，修复依此执行。

### F1 点击顺序 = 意图顺序（不是发送时登记顺序）

1. **Profile 显式选择在点击时登记**：glue `onSelect` → 立即 wire
   `selectForSession`（后端此时盖 action_seq）。`applyOnSubmit` 不再为当前
   选择补调 selectForSession——只对已登记 pending 做
   beginTurnApplication（或无 pending 时走既有普通轮路径）。连续多次选择
   由后端 pending newest-wins 吸收；"等待期间新选择保留""失败保留选择"
   语义不变。点击时登记失败必须在 UI 呈现（选择未登记，可重试），不得静默。
   选择动作仍不触发任何原生 apply/restart（FR-04 不变）。
2. **跨插件点击序列化**：同一 chat 会话内，两个 contribution 的点击登记
   wire 调用（selectForSession / chooseForSession）经共享 seam 按点击顺序
   串行发出（前一调用完成后才发下一个）→ 服务端到达顺序=点击顺序。
   seam 复用 bound-fact 同款只读投影模式（Profile glue 暴露 enqueue 钩子；
   对方缺席时直调，语义不变）。跨页/迟到边界由 admission 围栏兜底并诚实
   登记，不猜测。
3. **组合验收反例**（真实 glue + model guard 组合，产品层）：P(m1)→M(m2)
   =m2 胜；M(m2)→P(m1)=m1 胜；M(m2)→不含 model 的 P=m2 保留；两条请求
   乱序（点击序为准）；应用中后续选择留待下一轮；每 send 恰一次原生
   副作用；零全局回写。

### F2 绑定会话转交失败 ≠ 未绑定

1. **sink 三态**：`offer_turn_intent` 返回 True（已写入 overlay，转交成功）
   / False（确未绑定，独立路线）；**绑定但写入失败/未知必须抛类型化
   `TurnIntentHandoverError`（含原因）**，不得折叠成 False。
2. **chooseForSession 响应加 `intentRoute`**：`"profile-overlay" |
   "independent" | "handover-failed"`（fail-closed：sink 缺席=independent；
   转交失败=handover-failed 且意图保留在队列并打标记）。
3. **前端 bound 分支必须核对意图命运**：boundFact 不再是放行充分条件——
   最新意图 handover-failed/unknown → 阻止发送（零 prompt、保留草稿与
   意图、reason 可展示）；routed 成功 → 放行（Profile 管线的单次 apply
   覆盖该 overlay 项）；无意图 → 放行。绑定在点击与发送之间注册/卸载变化
   → 重新求值；routed 意图的绑定消失时不得无证据放行（fail-closed）。
   迟到转交结果按 exact sequence 围栏，不影响当前判定（M12 语义复用）。
4. **服务端后盾**：带 handover-failed 标记的意图，`beginTurnApplication`
   必须 typed 拒绝（HANDOVER_UNRESOLVED，意图保留），不得 no-intent 放行，
   也不得二次 apply。正常绑定发送仍恰一次 apply（M06 计数不变）。

### F3 三品牌真实进程检查

受控 double 层保留为证据，但 T05 证据等级改为 PARTIAL，除非补齐：用已
安装资产的真实适配器进程完成无模型 initialize / session/new / 配置查询 /
关闭 的证据（禁止 prompt、读测试 key、登录、安装）。某品牌资产不能支持
时：记录准确阻塞+最小安装请求，该品牌保持 PARTIAL，已通过项不回退。

### 修复分工与边界

- FIX-1（单写者）：F1+F2 —— Profile glue/selection、model-provider
  choices.py、产品 turn_application.py sink、chat-api-entry/next-turn-client
  及两侧测试 + 产品组合反例。
- FIX-3：F3 真实进程检查脚本/证据 + 三品牌测试标注；不触 FIX-1 文件。
- 其余边界不变：不改 host、不造第二账本、不降 trust、不修 Harness 内部。
  修完复跑既定全集+两前端+typecheck/build/root gate，逐条更新
  M03/M06/M08/M11/M12 与 T05 证据等级，一次性集中交付。

## 7. 写者分工（禁止跨界写）

- **A（T02）**：`plugins/profile/**`（core/sessions/repository/storage/
  application_journal/resolution + tests，含 v3 迁移与 §4/§6-A 反例）。
  不写产品接缝/model-provider/前端/契约/账本。
- **B（T03）**：`plugins/assets/model-provider/server/**`（choices/next_turn/
  harness_binding/plugin + tests，含 §2 wire 注册、§5 围栏、§6-B 反例；
  TurnApplicationPort 协议定义在插件内，测试用注入 double）。
  不写 Profile/产品组合/前端/契约/账本。旧 `ConfigurationServiceHarnessPort`
  保留为测试 double，生产注入禁止（注释标注）。
- **T04（主会话统筹）**：`products/server/**`（composition 注入 sink/真实
  TurnApplicationPort、bound/unbound dispatch）、
  `plugins/assets/model-provider/chat-contribution/**`、
  `plugins/profile/integrations/chat/**`（guard 语义、DTO、§6-T04 反例）。
- 共同契约即本文；同文件不得双写者。发现本文缺口 → 报主会话，不自行改契约。
