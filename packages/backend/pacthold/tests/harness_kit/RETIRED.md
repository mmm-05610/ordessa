# 退役用例 → 替代覆盖对照 (HD-002)

裁定要求：旧链专属行为测试随旧链明确退役，**逐例记录替代覆盖**；通用传输、进程清理、
安全与品牌接入测试保留。本文件对 5 个被删测试文件、47 个 `test(` 声明逐条给出三种处置之一：

* **替代** — 新链里同一事实仍被断言，给出用例编号；
* **保留（重定位）** — 事实与链无关，被搬到仍存活的文件；
* **随旧链消失** — 该断言描述的正是被裁定移除的行为，**没有替代**，理由写明。

文件名（`E*` = `access_entry_behavior.test.mjs`，`T*` = `acp_passthrough_target.test.mjs`，
`C*` = `acp_channel_behavior.test.mjs`，`F*` = `controlled_harness_self_proof.test.mjs`，
`R*` = `real_adapter_protocol.test.mjs`，`PY` = `tests/access/test_acp_boundaries.py`）。

## 1. `tests/access/sidecar_boundary_behavior.test.mjs`（12 例）

| # | 原用例 | 处置 |
| --- | --- | --- |
| 1 | 显式入口 + 项目目录，不写 Agent home | **替代** E1（另含 `readdir(home)` 为空）；启动上下文由调用方点名这一事实另由 T1 的前置成立 |
| 2 | 注册要求显式入口，adapter 环境是校验而非信任 | **替代** E2（`ADAPTER_LAUNCH_REQUIRED`、`ADAPTER_ENVIRONMENT_INVALID`、敏感键与 `sk-` 拒绝），E3（未连接时零 Agent 记录） |
| 3 | 反向权限请求交给宿主消费者，选项来自 Agent 自己的列表 | **替代且更强** T5：反向请求以 Agent 原帧到达，宿主自己的回复原样到达 Agent；插件不再"选选项" |
| 4 | 有界授权自动挑 `allow_always`，不可用 kind 被拒 | **随旧链消失**。自动批准即裁定禁止项；选项挑选归宿主，见 T9 |
| 5 | 关 round trip 时答案来自品牌声明的 `permissionMode` | **随旧链消失**（这正是要移除的代答）。替代的是反向事实：E3 `ACP_CONNECT_FIELD_RETIRED` 拒绝 `permissionRoundTrip`/`permissionTimeoutMs`，T9 断言无人应答时**不产生任何回复帧** |
| 6 | cancel / disconnect / close 是三个不同事实 | **拆分替代**：cancel 是通知 → C5 + T2；disconnect → T10 + E4（`transport_end{reason:"adapter_exit"}`，不借任何 `stopReason`）；close → E4 + E7 |
| 7 | 未声明的 resume 不得被报成成功重开 | **随旧链消失**（插件不再声明任何 reopen）。等价事实由 T3 承担：客户端点名的 agent-bound 方法原样到达，Agent 拒绝就返回 Agent 的拒绝 |
| 8 | Agent 拒载的存储会话不被认领为已打开 | 同上，**替代** T4（Agent 的 error 帧原样回到客户端，不被信封改写） |
| 9 | 标准与自定义 capability 字段原样存活 | **替代** C3 + T2（未知字段仍在帧里）|
| 10 | 一个 Session 跨轮保持身份，两个 Session 互不串 | **替代** E5（两条 Session 各自 id 与轮次计数，由客户端自己 `session/new` 开） |
| 11 | Agent 失败的成因留在信封 error 里 | **替代且更强** T4：不再是"消息字符串保住"，而是整个 error 对象（含原生 code）原样通过 |
| 12 | 关一条连接只放掉它自己的进程 | **替代** E7（两个 Sidecar，邻居 pid 仍活）+ E4（`waitGone`） |

## 2. `tests/harness_remote/sidecar_envelope.test.mjs`（6 例）

| # | 原用例 | 处置 |
| --- | --- | --- |
| 1 | 无 Worker 隔离标记则拒跑 | **替代** E8（`SIDECAR_ISOLATION_REQUIRED`） |
| 2 | native 入口接受无隔离的 provenance-only 操作 | **替代** E8 + E6（未连接即可应答 `harnesses`） |
| 3 | native 入口拒绝隔离标记与未知执行旗标共存 | **替代** E8（`SIDECAR_MODE_CONFLICT`）+ E3（`ACP_CONNECT_FIELD_UNKNOWN`） |
| 4 | provenance 校验拒绝被篡改的快照 | **替代** E8（临时根里追加一行 → `PROVENANCE_MISMATCH: bridge/src/acp-client.js` 且无任何 `"ok":true`）+ PY 的 `provenance_violations`（unlisted/absent/mismatched 三态自证）|
| 5 | 信封驱动 register/start/create/prompt 与 pre-terminal 事件 | **随旧链消失**。四个 op 已不存在。流式事实的替代：C2（通知逐字到达，含未知方法）与 T2 |
| 6 | 信封以类型化错误拒绝未知 op 与重复注册 | **替代** E3（`UNKNOWN_OP`、`ACP_ALREADY_CONNECTED`、retired 字段按名拒绝） |

## 3. `tests/harness_remote/snapshot_seams.test.mjs`（13 例）

假接缝层（直接对 `AcpClient` + `fake_acp_peer` 断言），多数钉的是已删文件的内部行为。

| 原用例 | 处置 |
| --- | --- |
| ACP 保留 adapter `data.error` 成因 | **覆盖变更**：`transportOnly` 下桥不再格式化 error，error 帧原样过路（T4）。`PATCHES.md` §7 注明该补丁在无消费者路径上，只为升级 rebase 保真保留 |
| prompt 终答前先投递实时事件 | **替代** C2 |
| `AcpService` 保原生 Session 身份并择 resume | 身份部分 → **E5**；resume 选择 → **随旧链消失**（同 §1-7） |
| 原生 cancel 是通知；子进程断开拒绝在途工作 | **替代** C5 + C6 + T10 |
| OpenCode 保鉴权 health 路径与托管 Windows 进程边界 | **不在本链**，仍由 `tests/opencode_*.test.mjs`（32 例，实跑全绿）覆盖 |
| OMP undo/redo 需原生 session hash 与进程身份 | **随旧链消失**（该状态机属被删的扩展面）。`omp-extension-action-state.js` 仍在快照内，但其消费端不在新链 |
| 未知 model 变体在到达原生 Harness 前被拒 | **随旧链消失**：校验/改写 `model` 与透明 transport 互斥（PY `test_the_access_entry_translates_no_model_and_names_no_brand` 反向钉住：入口不得出现 `resolveNativeModel` 与任何品牌名） |
| 权限 resolver：grant 选中 optionId / deny 记 cancelled / 无 resolver 时 static deny 记 cancelled / 超时默认 deny / 越界 optionId deny | **随旧链消失**（5 例）。这四类"由桥替用户决定"正是裁定要求停止的；替代为 T9（未应答就保持未应答，配品牌、配 timeout 都不产生回复）与 T7（并发反向请求各留自己的 id 与答案）。**明确的覆盖缺口**：`acp-client.js` 非 `transportOnly` 默认分支的 resolver 语义现在无测试——该分支在新链中已无消费者，故不补，见 `REMOVALS.md` 四 |
| 注册工厂构建单个 profile 且不含 daemon 控制面 | **替代** E6 + `harnesses/index.mjs`（发现即列 9 个 ACP 品牌，`opencode` 不在其中）+ PY 的品牌目录不得互抄实现 |

## 4. `tests/harness_remote/four_harness_component.test.mjs`（9 例）

| 原用例 | 处置 |
| --- | --- |
| 四个家族经同一基座注册、无品牌分支 | **替代**：入口层无品牌分支（PY 上述新用例）+ E6 一次发现全部 9 家、`HARNESS_UNDISCOVERED` 拒未知 |
| hermes 由 AgentBox 注册、未验证能力保持 false | **替代** C3（如实报告声明的能力，含未知键；未声明即不在） |
| 逐家族能力差异可观测且 driver 可见 | **替代** T2（能力字段是帧字段，原样过路，差异天然可观测） |
| 逐家族 initialize / pre-terminal / 原生身份 / resume | **部分替代**：initialize 等帧改由客户端发（T1、T3）；pre-terminal → C2；身份 → E5；resume → **随旧链消失** |
| 逐家族 cancel 以协议通知到达原生对端 | **替代** C5 + T2 |
| 对端断开拒绝在途工作而非伪造完成 | **替代** C6 + T10 + E4 |
| 逐家族审批决策：allow/deny/unanswered/forged option | **替代** unanswered 一支（T9）；allow/deny 由宿主自己发（T5）；"forged option" 已无处发生（插件不再构造 option），**随旧链消失** |
| 未声明 resume 如实报告而非假定 | **随旧链消失**（见 §1-7） |
| 一个家族失败不阻止其他家族注册 | **替代**：发现与连接分离——E6 在零连接下应答，单个品牌连接失败不影响另两家（E7 两条独立 Sidecar；跨品牌逐一实跑属包外端到端，见交付报告断点） |

## 5. `tests/harness_remote/turn_completion_facts.test.mjs`（7 例）

全部围绕"插件合成轮次完成事实"：终答缺席时不得报干净停止、drain window 计数、尾部 chunk 归属。
新链不做轮次记账，因此**7 例整体随旧链消失，无替代**，理由与被删文件对应：
`acp-prompt-echo-filter.js`（回声过滤/排空窗口）与 `task-model.js`（轮次状态机）都不存在了。

替代事实只有一条，且由 T10 + E4 双向钉住：**Agent 没说的话就是没说**——进程退出如实上报为
`transport_end`，在途请求保持未应答，不写 `cancelled`、不写 `end_turn`、不补一个 result。

## 6. 夹具自证

裁定要求"夹具先自证，不靠改断言或跳过测试变绿"。自证用例共 **6 条**，分在两处：
`acp_channel_behavior.test.mjs` 的 C9–C11（异步失败记录器会看见失败并自我卸载、成功回复被记录在
线上、仅 error 回复带着成因 reject 且不留悬挂），和 `controlled_harness_self_proof.test.mjs` 的
F1–F3（成功应答被收到并记录且结束所握的轮、error-only 应答同样、多个请求各自保持独立且轮次只在
最后一条应答后结束一次）。`real_adapter_protocol.test.mjs` 的 6 条再把方法名与结果字段钉到磁盘上
的真实 adapter bundle，并含一条"扫描器不是空匹配检测器"的反空转用例。

因此 T* 里的缺席断言（未应答、零帧、无 reverse-reply 行）不是"因为没接通所以没记录"：每条缺席
断言之前都有同一连接上的一次成功往返，E3 更直接先断言 Agent 侧记录条数为 0。

## 7. 存活用例总数（实跑）

| 套件 | 用例 |
| --- | --- |
| `tests/access/acp_passthrough_target.test.mjs` (T1–T10) | 10 |
| `tests/access/access_entry_behavior.test.mjs` (E1–E8) | 8 |
| `tests/access/acp_channel_behavior.test.mjs` (C1–C11) | 11 |
| `tests/access/controlled_harness_self_proof.test.mjs` (F1–F3) | 3 |
| `tests/access/real_adapter_protocol.test.mjs` | 6 |
| `tests/capability_claims.test.mjs` + `tests/harness_remote/frame_buffer_lifecycle.test.mjs` | 21 |
| `tests/opencode_*.test.mjs`（6 个文件） | 32 |
| **node 合计** | **91** |
