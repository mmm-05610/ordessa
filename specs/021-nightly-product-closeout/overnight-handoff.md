# 021 第二轮夜间收口：ZCode 入口与执行计划

日期：2026-10-01。状态：实施交接，**未完成验收**。

## 1. 任务终点

收口 Ubuntu/Linux amd64 的 Ordessa Harness Desktop：Pi、Codex、Claude Code
真实可用，Profile 是可复用配置图纸，模型/供应商与 Profile 能在同一会话的下一次发送前应用，
已有历史不丢失，多会话不串配置。最终给出可试用的安装产品及逐条证据。

不是重新设计平台，也不是协作系统、子代理系统或全部资源配置大开发。
先修已有路径与缺口，不重新实现已有插件。不 push、不合并 main。

本轮材料按 Spec Kit 的需求/场景 → 技术计划 → 依赖任务 → 验证证据组织，
不另建派工单控制面。协作技能只采用独立写权、反例和主会话亲验；不引入永久调度循环。

阅读顺序：本文件 → `overnight-acceptance.md` → `overnight-tasks.md` →
`takeover-progress.md` 顶部及固定 TODO → 相关源码。只读本文件不能开始宣告完成。
旧 `README.md`/`execution-plan.md` 的 2026-09-30 deadline 已过期，不照旧时刻空转。
旧 `acceptance.md` 的发行/产品要求仍保留：本轮不满足其 18 条，不得写 MORNING_CANDIDATE=YES。

## 2. 精确起点与保护面

| 项 | 交接时事实 |
| --- | --- |
| 工作目录 | `/home/maoqh/projects/ordessa/worktree/021-ordessa-product-closeout` |
| 分支 | `nightly/021-ordessa-product-closeout` |
| 已提交起点 | `7d9d6a0dec`；开工必须核对实际完整 SHA，不擅自 reset 到这个点 |
| 根工作树 | `/home/maoqh/projects/ordessa`，main；禁止 checkout、实现、安装指向改写 |
| Python | `.cleanup-evidence/product-integration-venv/bin/python`；验证 editable 路径指向本树 |
| 证据 | 原始日志 `.cleanup-evidence/`，脱敏摘要本 spec 的 `evidence/` |
| 用户凭据 | 本树 ignored `key.txt` 第 1 行 DeepSeek、第 2 行 OpenCode Go；只由脚本读取，不能打印 |
| 官方账号 | `~/.ordessa/accounts/codex`，Ordessa 独立登录、原生 keyring；不读/复制 `~/.codex` |
| 他属改动 | `docs/ui-preview/01-empty.png`，保留且不提交、不还原 |

### 2.1 已有收获，不能从零重复

以下来自已有实测账，执行者核对证据，不重复用昂贵推理来建立同一个事实：

- 三品牌首次 Profile 配置与原生独立读回，后台真实聊天已有证据。
- Codex 官方 Desktop Profile 首发及同 provider 下一轮模型选择有 UI 证据；不等于三品牌完整 UI 验收。
- Pi DeepSeek → Go 在同 native/canonical 会话 live-registration，历史回忆与两次 C4 已通过；
  透明 relay 和直接公网都通过。参考进度顶部，不把早期 DNS 阻塞当当前状态。
- Claude 完整后端产品 DeepSeek → Go restart/resume 与历史回忆已通过；不等于全部反向/UI场景通过。
- 单官方账号、多个 Codex 官方实例和独立 API 实例共存已有证据；无需再发明 token 代理。
- 配置存储/编辑只校验 URL 语法；真实连接探测仍做 DNS/SSRF；不能继续放宽联网检查。

### 2.2 当前真正的 blocker

Codex 官方 → Go 的两次独立有界验收失败：第二轮回复没有第一轮标记，
真实目的地也未证实；当前安装版本 close 只是 unsubscribe，不是原生进程重启。
不能把 setter/恢复回执或非空回复当成功。

源码依据（锁定原生版本而非猜测最新版）：

- ACP 1.1.14 的 closeSession 仅调用 thread/unsubscribe。
- Codex 0.147.0 默认在最后订阅撤销后延迟卸载；已运行 thread/resume 忽略配置覆盖。
- 原生源码/文档链接已记录于 `takeover-progress.md` 顶部；这确认生命周期缺陷，
  **不宣称已证明具体失败的唯一根因**。

### 2.3 未提交的 Codex 修复草稿：必须接管，不能当已验收

以下是我刚写的草稿，不得删除，不得直接投入生产：

```text
plugins/harness/packaging/native-profile/
  codex-process.mjs / codex-process.test.mjs       新增
  enhance.mjs / bridge.mjs / restoration.mjs      修改
  configuration.test.mjs                         修改
plugins/harness/src/ordessa_harness/configuration/model/
  backend.py / restoration.py                    修改
plugins/harness/tests/test_provider_restoration_service.py  修改
```

已实现草稿：退出确认后启动新子进程、初始化失败清理、owned rollout 路径校验、
同 ACP 对象换 native client、私有 rollout resume、后端 managed-account 目的地解析。

本轮第一手验证：native-profile Node **50/50**（随后新增路径所有权测试尚未重跑，
不要把它计入这 50）；Python configuration_model/restoration/Pi registration/products/server
**330P**；候选实际官方/API 初始化与一次官方 session/new 通过，**modelCalls=0**。
一次 Python 命令误指不存在的 test_configuration_model.py，未跑，不算通过。

候选路径：`.cleanup-evidence/codex-native-restart-candidate/artifacts/codex-runtime`。
构建记录 treeDigest `sha256:eedd7a181341bb2307c03a69f116e76ec86ba37cf344320cf6c11f576d50fdf0`，
537 entries / 320862848 bytes；**未安装，后续源码修订后这些摘要失效，必须重建**。

必须先处理的草稿缺口：

1. `startCodexConnection` 默认 spawn Node 的 `codex.js` 启动器，再由它 spawn 原生二进制。
   当前 helper 只确认直接子进程退出；若 SIGKILL 启动器，原生后代可能仍活着。
   必须满足 A 段“真实原生进程死亡”门，不能把 launcher PID 当 native PID。
2. 真实 Codex rollout 路径/恢复后文件位置、双向恢复以及请求实际目的地尚未通过。
   当前路径保护允许已绑定的原历史路径跨 HOME；必须用真实原生场景验证，不能放宽成任意文件。
3. 初始化成功不等于恢复成功；恢复/读回失败后，旧绑定必须保持无效，不能放行 prompt。
4. 私有 RPC 解析、account owner 注入、旧资产能力与清理还需要统一反例和独立复审。

开工先用显式文件列表做 diff/hash 记录，认领草稿；不要 stash/reset/clean。
提交只提交本轮接管的文件，不带他属截图。不要为了建立“干净起点”强行提交未验证草稿。

## 3. 已定产品/安全语义，不交给执行者自由改

1. Profile 保存配置图纸；资源业务归各资源插件；Harness 内处理所有品牌差异。
2. Profile 只依赖通用应用能力，不新增 permission 凭证/放行业务；原生工具权限由 Harness 执行。
3. Profile 选择仅改变所选配置；输出中不打断；下一次用户发送时准备、独立确认，然后 prompt。
4. 会话内逐字段临时覆盖不回写全局 Profile；未覆盖字段随全局更新在下轮应用。
5. 显式切换同 Harness Profile 清除临时覆盖，无提示；不新增跨 Harness 换会话功能。
6. provider/model 同一会话切换：Pi live；Codex/Claude 必要时实例 restart/resume，UI不变成新对话。
7. 一个官方 Codex 账号；多个实例独立配置，可同时存在官方实例和 API 实例。
8. owner、canonical session、native session、runtime generation 必须分别核对；
   重启有新运行代次，原 execution 已结束则不可复活，恢复后按既有内核语义建立新 execution。
9. accepted / refused / unknown 三态保留；Unknown 只查询，不重放 prompt、session/new 或恢复效果。
10. 默认 data root 由产品建立/复用；临时 root 只用于代理自身测试，不作为正常产品启动默认值。
11. 不修改全局 Harness 登录/config；不 clone 全量 `.codex`/`.claude`；不按 Profile 建 HOME。
12. 不增加平台品牌逻辑、不绕安装完整摘要与所有权校验、不为绿删除断言或恢复退役 compat。

## 4. 并行组织：一个 ZCode 主会话，最多三名 worker

不新建树，不启动第二个持久调度会话。主会话在现有树内委派明确文件所有权的子代理。
每个 worker 深度 1，不再派 worker。无独立代理能力则按相同依赖串行，不当环境 blocker。

| 线 | 唯一写权 | 任务 | 独立原因 |
| --- | --- | --- | --- |
| A Harness | `plugins/harness/**`；不写 products/文档/全局锁 | A01–A24、B01–B14 的 Harness 部分 | 不改 Profile/Chat；私有 RPC 差异在同一所有者内串行 |
| C 会话配置 | `plugins/profile/src/**`、`plugins/profile/tests/**`；model-provider `server/`、`profile-contribution/` Python源码/测试 | C01–C22 | 只验证已有中性会话配置契约，不改 Harness 私有接口 |
| D 前端 | `plugins/profile/frontend/**`、`plugins/profile/integrations/chat/**`、`plugins/chat/frontend/**`、`plugins/connectors/{acp,ordessa}/**`、model-provider `desktop/`、`chat-contribution/` TS源码/测试 | D01–D24 | 在既有通用接口上测试 UI 与发送；不写 Python/native |
| Lead 集成 | `products/**`、`packaging/**`、本 spec、进度/证据、必要全局锁/构建配置 | P/S/F、真实探针、主验收 | 接收三线成果，资产与产品测量单写者 |

worker 不做 git 写操作，不改共享 API/host、不写进度汇总、不运行真实模型、不动系统资产。
测试需要公共契约变更时先报告契约缺口，Lead 决定是否既有接口就能修；真正新协议/语义必须询问用户。
公共 API 如需机械一致性修复由 Lead 串行处理，不能让多个 worker各造一套。

并行上限是资源上限，不是强制同时跑满。Electron/全量 npm/deb/native 大构建最多一个；
局部小测试可并行。真实模型测试全由 Lead 串行。不要同时运行三套 npm ci、全量 pytest 和 Electron。

## 5. 依赖与检查点

```text
T0 认领现场/冻结起点
 ├─ T1 A：Codex原生生命周期 → T2 B：双向恢复/C4 → T5：构建资产/验证
 ├─ T3 C：Profile/供应商会话语义 ──────────────────┐
 ├─ T4 D：UI/发送/失败语义 ───────────────────────┤
 └─ T6 P：打包/默认装配审计（先审计，后绑定新资产） ┤
                                                 ↓
T5 安装前候选验证 → [用户sudo安装：可阻塞此边] → T7真实后端恢复
T2 + T3 + T4 + T7 → T8实际Desktop矩阵
T6 + T8 → T9最终回归/deb/安装验收/报告
```

T3/T4 可先靠冻结中性契约完成受控反例，不需要等 T1。
T6 可先修打包缺席、路径、装配门，不提前发布未通过 T5 的资产。
任何一条阻塞只暂停其依赖闭包，继续其余可做任务。每个编号的完成条件在另两文档。

检查点：CP-N0 现场；CP-N1 原生安全；CP-N2 受控语义；CP-N3可信候选；
CP-N4真实后端；CP-N5实际Desktop；CP-N6发行候选。
这些是验收窗口不是停止点。Lead 在各检查点提交已验证改动并更新进度。

## 6. 授权、成本与夜间阻塞处理

- 已授权的两个 Key 与 Ordessa Codex 账号只用于本任务最小验收；不得外发、打印、复制进仓库。
- 默认真实模型验收预算：最多 **24 个显式用户 prompt/turn**，每个测试最多 3 个短prompt，
  每次输出目标 ≤128 tokens；原生辅助模型验证请求也要可见计数，无法计数写 unknown。
  用 token/请求限制可实现的供应商限制；超额需要用户裁定，不能用“随便用”无限烧。
- 一个确定失败的真实场景最多修正根因后独立重测一次；其后继续受控定位，
  不反复用真实输出碰运气。Unknown 不纳入这条重试许可，它绝不能自动重放。
- sudo需要用户、登录需要浏览器、网络/供应商不可用、实质架构/安全决策是硬依赖。
  记录准确命令/诊断和被阻塞 ID；不把缺资源写 PASS 或 skip；继续其他任务。
- 新系统资产只能加到新目录，完整验证、不覆盖旧资产；没有 sudo 不可改 trust 到用户可写目录。
- 不自动安装 deb、替换现有运行产品或重启用户服务；可生成安装命令供用户确认。
- 没有用户协助时，仍可交付源码/离线门/候选包/安装脚本；总状态必须 PARTIAL_USER_ACTION。
- 小实现问题、fixture错误、导入层级错误不是停止理由。边界内自行修并补反例。
- 终态限定：COMPLETE_VERIFIED / PARTIAL_USER_ACTION / BLOCKED_DECISION / STOPPED_BY_USER。
  不采用“夜跑了很久所以完成”，不在达到一个低门槛后无限扩范围。

## 7. 进度与报告格式

`takeover-progress.md` 是用户观察入口，Lead唯一写者；每个检查点更新顶部，保留历史。
每 30 分钟有实际工作时更新一次简短进度，任务仍在跑时记录子进程/阶段，不编造完成数。
收尾进度按 ID 报：PASS/FAIL/BLOCKED/NOT_RUN/引用旧证据。只有当前候选实测才算新PASS。

每条证据至少包含：ID、候选 SHA/工作树差异摘要、资产 digest、环境、命令、退出码、
观察量/反例结果、请求数及未知项、临时资源归属/清理、未验边界。
UI 证据需 session/owner 相关性，截图不能替代真实发送；后台回执不能替代 UI操作。

最终一次性输出：完成条目、未完成条目与原因、所有新增问题及方案、
可试用入口、deb SHA256、用户需执行的完整命令、复现步骤、无越界证明。
不要让用户在两名代理之间复制多轮逐条反馈；Lead 独立审阅并一次性收口全部已发现问题。

## 8. 给 ZCode 的短提示词

```text
/goal 在当前 worktree 完成 specs/021-nightly-product-closeout/overnight-handoff.md、overnight-acceptance.md、overnight-tasks.md 规定的产品收尾。先认领未提交草稿和保护他属改动，按依赖并行派最多三名子代理；你独占集成、提交、资产及真实验收。逐ID补反例、亲跑门、更新 takeover-progress.md，不降低标准、不扩架构、不动main、不push。一个阻塞只暂停其依赖，继续独立任务；sudo/登录/新安全决策立即准确上报。全部当前候选证据齐全才报 COMPLETE_VERIFIED，否则列清缺项和用户动作，检查点后继续。
```
