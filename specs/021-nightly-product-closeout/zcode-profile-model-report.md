# ZCode Profile 稀疏配置与独立模型应用——收口报告（T00–T06）

日期：2026-10-02。执行权威：`zcode-profile-model-closeout.md`；冻结契约：
`zcode-profile-model-appendix.md`（含 §6b 主会话裁定）。
工作树：`nightly/021-harness-rollout-opencode-hermes-dsh-kilo` @
`e560f7a19b9e1b1d0e876bdfde5fe43bb4b14873`（HEAD 未动，全部改动未提交）。
执行方式：主会话（契约/集成协调/账本/复跑）+ 2 只读 Scout + 3 实现子代理
（T02-A Profile、T03-B model-provider、T04 Integrator）+ T05 执行代理。

**终态：IMPLEMENTATION_REVIEW_READY（修复轮后，2026-10-02 晚）**。首轮
交付经 Codex 复审（`codex-zcode-review.md`，REQUEST_CHANGES）后完成修复轮
F1/F2/F3，见 §8；实现与受控门全满足；实际用户验收单列，见 §5/§6。

## 1. 本批净修改面（与接手初始改动的区分）

接手基线 = T00 时刻的未提交树（快照：
`.cleanup-evidence/zcode-profile-model/t00-baseline-full.diff`，97 个脏/未跟踪
路径）。本批新增改动 **37 个文件**（diff-of-diffs 精确比对，他属初始脏文件
零触碰）：

- **T01 契约**：`specs/021-nightly-product-closeout/zcode-profile-model-appendix.md`（新）。
- **T02-A Profile 稀疏语义**（plugins/profile）：生产 `src/ordessa_profile/`
  的 storage.py（schema v3 迁移）、repository.py（action_seq/revision/
  CAS 消费）、resolution.py、core.py、sessions.py（admission 事实/CAS 围栏/
  稀疏合成）；测试 injections.py、test_brand_matrix_pa5.py、test_migration_v2.py、
  test_native_turn_application.py、test_native_session_wire.py、test_sessions_v2.py、
  test_storage.py、test_us5_projection.py 改强，新 test_sparse_admission_facts.py
  （13 例）。
- **T03-B model-provider 后端**（plugins/assets/model-provider/server）：新
  `turn_application.py`（TurnApplicationPort 协议+证据校验）；next_turn.py
  （围栏重写）、choices.py（beginTurnApplication）、plugin.py（注册+sink 钩子）、
  harness_binding.py（docstring+版本键）；测试新 test_next_turn_fencing.py、
  test_turn_application_gate.py，改 test_next_choice_wire.py、
  test_plugin_registration.py。
- **T04 产品/前端**：新 `products/server/src/ordessa_server_product/turn_application.py`
  （ProductTurnApplication/ProfileTurnIntentSink/NativeModelEligibilityPort）；
  改 composition.py、profile_sessions.py；前端 next-turn-client.ts、
  chat-api-entry.tsx、entry.tsx、glue.ts、picker-model.ts；新测试
  test_turn_application_product.py、test_native_model_turn_composition.py、
  turn-application-dispatch.test.tsx，追加 native-submit.test.ts 1 例。
- **T05 三品牌**：新 products/server/tests/test_native_model_turn_three_brand.py。
- **跨界追认 1 处**：`plugins/profile/src/ordessa_profile/repository.py`
  `upsert_session` 的 action_seq 重绕 bug（T04 发现并一行修复，与该函数
  docstring"None=leave alone"语义一致，T02 全部测试保持绿）。
- build 自动再生：`products/desktop/extensions.lock.json`（closeout §0 允许）。
- 证据目录：`.cleanup-evidence/zcode-profile-model/`（t00 基线、t05 矩阵/三品牌
  trust、t06 复跑日志）。

注：T04 报告曾列 `native_configuration.py` 为改动，经 diff-of-diffs 核实其
ensure_native/observed_native/has_live_native 均已在 HEAD 提交中，本批净改动
为零——以 diff 为准。

## 2. T00–T06 状态与证据

| 任务 | 状态 | 证据 |
| --- | --- | --- |
| T00 接管基线/无竞争写者/红账本 | PASS | t00-baseline.txt、t00-baseline-full.diff（HEAD/branch/status）；进程扫描无本树写者（仅 ChatGPT 桌面自带 codex app-server 与 VS Code，均不写本树）；13 例复跑 8F/5P exit 1（t00-sparse-red-rerun.log） |
| T01 契约附录 | PASS | zcode-profile-model-appendix.md（§1 方案选择、§2 wire DTO、§3 双模式单应用、§4 schema v3、§5 队列围栏、§6 反例映射、§6b 四项裁定） |
| T02 A：13 例转绿+补反例 | PASS | sparse 13/13 exit 0；Profile 套件 228P+8F→251P exit 0；新增 13+2 例（P06–P11、C04）；迁移反例 2 例 |
| T03 B：独立意图+共享端口协议 | PASS | model-provider server 236P→282P exit 0；beginTurnApplication 注册+46 新例（fail-closed/幂等/M08/M09/M10/M12 插件层） |
| T04 产品/前端合成 | PASS | 合并门 843P→868P exit 0；前端 67P+60P exit 0；typecheck/build exit 0；M01–M07/M09/M11/M12/C02/C03/C05 全落地 |
| T05 受控矩阵+三品牌 | PASS | 矩阵 7 门全 exit 0（t05-matrix.log）；合并门 883P；三品牌 trust 校验 verified:true×3（t05-three-brand-plan-verify.json，18 参数，零 prompt） |
| T06 复跑/build/文档/停写 | PASS | 主会话复跑：sparse 13 exit 0、合并门 883P/1 既有 warning exit 0、前端 5f/60P+6f/67P exit 0、typecheck exit 0、`git diff --check` exit 0、root gate 见下 |

**Root gate**（§6 最终门）：
`ORDESSA_WIRE_LIVE_PYTHON=.cleanup-evidence/product-integration-venv/bin/python
ORDESSA_BUNDLED_ROOT=.cleanup-evidence/product-dev-runtime-URGO6TDv
ORDESSA_PREVIEW_OUT=/tmp/ordessa-zcode-profile-model-preview npm test`
→ **exit 0**（ROOT_GATE_EXIT:0；全部工作区 suite 通过，含受控 Electron 门；
preview 独立输出于 /tmp/ordessa-zcode-profile-model-preview，未触碰
docs/ui-preview；完整日志 t06-root-gate.log）

## 3. P/M/C 验收门逐行台账（受控层全 PASS）

每行证据 test ID 均在合并门 883P 或前端两 workspace 内；详细逐条台账见
T05 报告存档于本报告同目录（`t05-matrix.log` + 下表摘要）。

| 门 | 状态 | 关键证据（test ID） |
| --- | --- | --- |
| P01 | PASS | test_sparse_profile_precedence.py 13/13（原 8F/5P→全绿，核心断言零删改） |
| P02 | PASS | `test_omitted_item_never_compiles_to_reset_and_stays_effective_next_turn[*]` + `test_native_full_target_keeps_omitted_items_as_retained_base` |
| P03 | PASS | retained_base 不读最新 revision：`test_retained_base_is_labelled_and_never_read_from_the_newest_revision` |
| P04 | PASS | `test_profile_overwrites_only_matching_overlay_item_not_facet_sibling`、`test_brand_omission_never_resets_and_declared_removal_does[pi|codex|claude-code]` |
| P05 | PASS | `test_ordinary_submit_and_global_profile_edits_still_respect_session_override`、projection 系 |
| P06 | PASS | `test_global_edit_reaches_uncovered_items_but_never_a_user_overlay` + retained_base 标注反例 |
| P07 | PASS | `test_reconcile_uses_the_admitted_mask_not_the_profile_it_is_facing_now` |
| P08 | PASS | `test_a_newer_pick_during_a_failed_operation_is_never_overwritten[*]`、`test_recovery_state_never_rewrites_the_binding_or_the_pending_choice` |
| P09 | PASS | `test_same_value_rewrite_during_apply_is_not_cleared_by_the_older_apply`、`test_an_older_apply_cannot_clear_a_same_value_rewrite_under_reconcile` |
| P10 | PASS | `test_repeating_a_turn_operation_has_zero_new_effect`×3 + `test_same_operation_key_replays_with_zero_new_effects` |
| P11 | PASS | `test_first_native_submit_same_selected_profile_applies_complete_choice`、`test_first_submit_requires_application_not_just_configuration_resolution` |
| M01 | PASS | `test_without_profile_choice_applies_through_shared_c4`（Profile 库文件不存在断言）+ 三品牌版 |
| M02 | PASS | `test_profile_unload_keeps_shared_authority_and_model_route`、`test_profile_reuses_neutral_uid_and_unload_cannot_dispose_shared_authority` |
| M03 | PASS | `test_bound_last_action_wins_both_ways_single_apply_temp_model_kept` 第 1–2 段 + 前端 "B then C applies only C, once, at submit" |
| M04 | PASS | 同上第 4 段（mask 内旧临时项被切换消费，m1 胜回） |
| M05 | PASS | `test_mask_external_profile_switch_keeps_the_model_pick` |
| M06 | PASS | 同 M03 测试逐轮副作用计数（每 send 恰 1 次原生操作）+ 前端 bound 不提交断言 |
| M07 | PASS | 同 M03 测试第 3 段（普通续轮保持 m2） |
| M08 | PASS | `test_an_undecided_application_blocks_every_further_resolve`、`test_a_blocked_session_never_degrades_into_the_no_intent_path`、`test_the_block_survives_a_newer_pick` |
| M09 | PASS | `test_same_native_id_on_two_channels_never_routes` + 插件层 routing identity 系 |
| M10 | PASS | `test_a_catalogue_change_after_queueing_refuses_the_stale_plan`、`test_the_submit_gate_operation_key_is_version_bearing` 等 |
| M11 | PASS | `test_pick_during_in_flight_application_only_queues` + 前端 M11 例 |
| M12 | PASS | `turn-application-dispatch` "a submit from a stale session never reaches the wire" + next-turn-client 迟到系 |
| M13 | PASS | `test_native_model_turn_three_brand.py` 15 例（三品牌真实注册端口、方言编译、真 trust 证据引用）+ 资产 trust 校验 verified×3；反例：读回偏离=unknown、伪 readback 入口被断言不可达 |
| C01 | PASS | 共用 authority/journal 断言（`test_profile_unload_keeps_same_c4_unknown_session_fence` 等） |
| C02 | PASS | `test_runtime_restart_replaces_authority_and_old_consumers_fail_closed`、`test_restart_rebinds_the_model_ports_to_the_new_authority` |
| C03 | PASS | 三品牌缺席/资源不支持 typed 拒绝零 prompt（9 例）+ 端口缺席 refused/ADAPTER_MISSING |
| C04 | PASS | `test_v2_store_migrates_forward_without_losing_a_record`、`test_restart_after_v2_migration_recovers_and_reconciles`、`test_upgrade_is_idempotent_when_run_twice` |
| C05 | PASS | `test_product_injects_real_turn_ports_with[_without]_profile`（注入类型为真端口类）+ build 19 扩展含两 contribution |

## 4. 新旧测试语义变更清单（逐 ID，old→new）

全部按最新用户裁定改强，无删除/skip/降断言：

| ID | old→new | 理由 |
| --- | --- | --- |
| test_native_turn_application.py cross_profile_removals | `('style','choice').op=='reset'` → `=='set'` 值 'terse' + `source=="retained_base"` + 声明移除 reset 另立断言 | FR-02 省略≠移除；原生首发需完整目标，省略项以保留值随行 |
| test_sessions_v2.py v2 reset | 同上拆分（省略无 intent + retained_base；reset 仅经 declared_removals） | 同上 |
| test_brand_matrix_pa5.py brand reset | omission 侧 `ops[(facet,extra)]=='reset'` → `not in ops`；reset 移至 declared_removals 用例 | 同上；三品牌参数化保留 |
| test_brand_matrix_pa5.py clears_overlay | `EXTRA not in values` → `values[EXTRA]==EXTRA_VALUE` + `sources=="retained_base"` | B mask 省略 extra → 保留；in-mask 覆盖断言不变 |
| test_us2_switch.py 全清 | （经 T02 语义自然通过，未改文件；判别力由 test_sessions_v2 m3→m2 补强覆盖） | — |
| test_harness_real_service.py reset unsupported | 未改——声明移除不被支持必须阻塞的语义对 declared_removals 仍成立 | 语义保留 |
| test_migration_v2.py 系 ×3 | 版本序列 `[1,2]`→`[1,2,3]`；新增列 PRAGMA 断言 | schema v3 |
| test_storage.py schema | max 版本 2→3 + 三新列存在断言 | 加强非弱化 |
| test_us5_projection.py 列集 | 精确列集加 4 新列 | 同上 |
| test_native_session_wire.py 显式重选 | （单 item 不区分 mask/全清，T02 后自然绿；显式重选清 mask 内 overlay 语义由 M04 产品测试钉住） | — |
| model-provider test_plugin_registration/test_next_choice_wire 计数 | 方法数 7→8（+beginTurnApplication） | 新 wire 方法 |
| injections.py 两个 double | clear_overlays→consume_overlays；upsert_overlay 带 action_seq | 生产签名演进 |

## 5. 实际模型/安装/真实 UI 分账（未跑不勾选）

- **真实三品牌聊天/模型/Profile UI：NOT_RUN**（§7 明确本批无模型权限；
  历史两品牌真实证据发生在抽离前，不复制为本轮结论）。
- **安装/deb：NOT_RUN**（本批不安装资产；三品牌 trust 校验为只读）。
- **root gate 全量 JS 聚合**：见 §2 行（本批改动相关 suite 全绿；历史遗留
  的 ui-preview 状态以 root gate 实际输出为准）。
- 受控 M13 的诚实边界：native ACP agent 进程是受控 double（编译/fence/
  readback/journal/trust 全为生产代码）；"真实三品牌无模型进程验证"属用户
  验收，不在受控门内。Claude restoration 路由与 Codex managed-account 登录
  分支受控不可达（已登记，未伪造）。
- 既有已知限制不变：Codex 官方→Go→官方跨 provider 密文恢复（上游限制）、
  Claude 公开再分发 NOT_VERIFIED、完整 deb 验收。

## 6. 用户回来后的复跑与 5 步验收

复跑命令即 §6 受控门 7 条 + root gate（见 takeover-progress 附录或本报告 §2）。
真实 UI（需授权后）：

```bash
node products/desktop/probe-profile-ui.mjs --brand=<pi|codex|claude-code> --key-file=…   # 库存/连线检查（无模型）
# 实际聊天验收（需明确授权真实模型调用后）：
node products/desktop/probe-profile-ui-driver.mjs   # 临时数据根，同会话多轮，凭据用后精确清理
```

5 步操作与期望（每步记录：期望有效配置、是否调用原生 apply、同会话标识）：

1. **普通无 Profile 会话 → 选模型 → 发送**：模型选择仅入队；发送前
   beginTurnApplication 经共享 C4 一次应用（真实 readback 确认）→ 才发出
   prompt；Profile 数据库记录增量 0。
2. **绑定 Profile（含 model M1）→ 再选模型 B → 发送**：同项最后动作胜——
   B 生效，Profile 其余声明项照常应用；每 send 恰一次原生应用。
3. **反向：先选 B → 再选含 M1 的 Profile → 发送**：Profile 的 model 项胜
   （mask 内旧临时项被消费）；Profile 未声明项保留 B/原值。
4. **选 B → 切换到不含 model 的 Profile**：B 保留（mask 外不清）。
5. **输出进行中选择模型**：只排队不打断当前 run；下一次输入才应用。
   已知限制：unknown 后会话持续阻断直至 reconcile；Codex 跨 provider 密文
   恢复为上游限制。

## 7. 终态、阻塞与最小用户动作

- 终态：**IMPLEMENTATION_REVIEW_READY**。无未解决阻塞；硬边界均已按
  "记录后继续独立项"处理（附录 §6b 裁定、T05 §4 诚实边界、上述分账）。
- 最小用户动作：① 审整 diff（本报告 §1 的 37 文件 + 接手初始脏改动）；
  ② 决定 root gate 之外的提交/合并；③ 授权后执行 §6 的真实 UI 验收；
  ④ 裁定 T02-A 报告的三项低风险遗留（declared_removals 无 UI 生产者、
  移除非粘性、ConfigIntent.source 前缀仅两种——见其报告 §6）。
- 本报告完成后停止写入；不启动新任务/后台巡检。

## 8. 修复轮（Codex 复审响应，2026-10-02 晚）

复审文档：`codex-zcode-review.md`（REQUEST_CHANGES：F1/F2 P1 接线缺陷 +
F3 证据缺口）。修复契约冻结于附录 §6c；FIX-1（单写者修 F1+F2）、FIX-3
（F3 真实进程检查）两个子代理执行，主会话复跑全部门。

### F1 点击顺序失效 → 已修（证据升级 M03/M11/M12）

根因：Profile 显式选择只进前端 store、登记推迟到发送时 selectForSession
（selection.ts:102），而模型选择点击即 chooseForSession → sink 立即写
overlay 盖 action_seq——发送时登记的 Profile 反而拿到更晚 action_seq，
压掉用户实际更晚点击的模型（复审受控复现 acme/m1 胜出）。

修复：① 显式选择点击时立即 wire `selectForSession`（后端此时盖
action_seq）；applyOnSubmit 只做 beginTurnApplication，未登记 pick
fail-closed 拒绝；点击登记失败 UI 呈现（picker alert）可重试；连续选择由
后端 pending newest-wins 吸收。② 跨插件点击序列化 seam：Profile glue 经
与 bound-fact 同款只读投影暴露 `serializeRegistration`（per-session FIFO，
前一任务 settled 才发下一个），模型侧 choose 经它入队（对方缺席直调，
语义不变）→ 服务端到达顺序=点击顺序。③ 组合反例
`test_bound_intent_order_composition.py`（8 例）+ 前端
`click-order-composition.test.tsx`（真实双 glue 组合，旧码红点
`expected [] to deeply equal ['profile-select']` 已捕获）覆盖复审全部
验收象限：P(m1)→M(m2)=m2 胜、M(m2)→P(m1)=m1 胜、M(m2)→无模型 P=m2
保留、两请求乱序（点击序）、应用中后续选择留待下一轮、每 send 恰一次
原生副作用、零全局回写。

### F2 转交失败仍放行 → 已修（证据升级 M06/M08）

根因：sink 把写 overlay 异常折叠为 False（turn_application.py:424）、
队列保留意图返回 pending-next-turn、前端 bound 分支无条件 ready
（chat-api-entry.tsx:285）——转交失败后发送按旧模型放行。

修复：① sink 三态：True=已转交/False=确未绑定/绑定但失败抛类型化
`TurnIntentHandoverError`。② `chooseForSession`/`queryChoice` 响应加
`intentRoute: profile-overlay|independent|handover-failed`（fail-closed；
失败意图保留队列并打标记）。③ 前端 bound 分支核对意图命运
（`NextTurnClient.intentFate()`）：handover-failed/undecided→阻止发送零
prompt 留草稿；routed+绑定消失→fail-closed 拒绝；迟到转交结果按 exact
sequence 围栏。④ 服务端后盾：带标记意图 `beginTurnApplication` typed
拒绝 `HANDOVER_UNRESOLVED`（意图保留、零二次 apply）。产品反例
`test_handover_failure_marks_the_intent_and_blocks_the_send`、
`test_unknown_handover_outcome_is_never_folded_into_unbound` 先红后绿。

### F3 三品牌真实进程检查 → 已补（T05 证据等级升级，含一处主会话裁定）

新增 `.cleanup-evidence/zcode-profile-model/f3-real-process-{pi,codex,claude-code}.json`
+ `f3-summary.json`：真实适配器进程（procfs executable == 已安装资产
entry，经生产 launch authority 的真实 trust 门）完成 initialize /
session/new / `_ordessa/session/configuration` / session/close，全部干净
退出（exit 0、零残留进程、/opt 零写入、prompt/推理请求计数 0——拒绝
服务器 + denylist 强制）。受控 double 层测试保留并在模块 docstring 注明
层级与真实证据位置。

- **pi**：裸跑（无凭据、无前置）全五步 PASS——selectors
  thinkingLevel/model。
- **claude-code**：裸跑全五步 PASS——selectors mode/model/effort/fast。
- **codex**：裸 `session/new` 被资产真实拒绝 `-32000 Authentication
  required`（阻塞已原文记录）；经产品自有无模型 provider 注册前置
  （`_ordessa/channel/configuration/prepare`，custom-gateway + 本地拒绝
  端点 + 自撰非凭据字面量；零登录/零安装/零 key 读取）后真实完成全部
  五步 PASS——selectors mode/collaboration_mode/model/reasoning_effort/
  fast-mode。
- **主会话裁定（可推翻）**：codex 的前置路由属产品正常无模型配置路径，
  符合 F3 证据标准；**T05 记 PASS（codex 带前置，裸跑阻塞透明记录）**。
  若采严格"裸 session/new"读法则 codex 为 PARTIAL——最小替代请求：用户
  供给一个已认证 Codex 账号或单条非托管 API key（无需任何安装）。

### 修复轮复跑（主会话亲跑，命令同 §2/§6）

| 门 | 结果 |
| --- | --- |
| 合并 Python 门 | **891 passed**，1 既有 warning，exit 0（883→891，+8 组合反例） |
| profile-chat / model-provider-chat | 68 passed（6f）/ 84 passed（8f），exit 0 |
| typecheck / build | exit 0 / 19 扩展 exit 0 |
| `git diff --check` | exit 0 |
| Root gate | **exit 0**（ROOT_GATE_EXIT:0；隔离 preview 输出 /tmp/ordessa-zcode-profile-model-preview；完整日志 fix-root-gate.log） |

### 修复轮新增边界登记

1. **routed 标记 + Profile 在点击与发送之间卸载**：前端已 fail-closed
   阻断；服务端 `beginTurnApplication` 对 routed 意图仍答 no-intent（不经
   sink 复核绑定存活）。登记为已知限制，最小后续：sink 读侧探针（小协议
   增量），不在本轮 §6c 冻结范围。
2. **独立意图 + 绑定在点击后出现**：guard 按 §3.3 放行，滞留旧意图经
   只读 reconcile 诚实呈现"未应用"（主会话追认为正确语义）。
3. `onClearSelection` 不撤销已登记后端 pending（§6c 未要求，语义未动）。
