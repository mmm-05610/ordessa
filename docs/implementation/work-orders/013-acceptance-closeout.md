---
id: "013"
slug: acceptance-closeout
batch: migration-repair-20261004
baseline: "0887b95bf900f50d2021a673aa7cfce967a2c3c2"
depends_on: []
write_paths: ["packages/backend/**", "packages/frontend/**", "plugins/**", "apps/**", "products/**", "packaging/**", "scripts/**", "tests/**", "docs/**", "specs/026-open-environment-migration/**", "package.json", "package-lock.json", "pyproject.toml"]
forbidden: ["/opt/**", "credentials/**", "runtime/**", "user-data/**", "other-worktrees/**", "AGENTS.md"]
ruling: "R-0261"
terminal: ["CONTROLLED_SCOPE_DONE", "PARTIAL", "BLOCKED"]
waive: []
parallelism: "none"
parallelism_reason: "One Codex session owns this queue; canonical-owner, transaction and assembly changes share contracts. Do not launch extra agents or worktrees by default."
---

# 013 — 修复验收反例，完成 026 剩余受控工程收口

## Objective

在既有迁移分支继续完成一个核心职责清楚、Profile 可选、三 Harness 接线完整且可从干净发行产物运行的受控 Desktop。修复已证缺陷，并完成原 010–012 无需用户授权的剩余工作。不重新设计 024–026，不重做已验证底座，不把 Harness 的内部功能搬入平台。

本单是已有队列的纠偏与执行排序，不是替换原验收标准。原 tasks/acceptance/contracts 仍为语义权威。本单具体反例为必须追加的回归条件。

R-0261 是本单执行边界的引用编号：沿用原 M01–M14 与 026 合同，用户要求为独立 Codex 会话准备方案；实际实施由用户启动新会话授权。复用既有队列，不初始化第二调度框架；本单初次投递未提交，执行者接管时记录 digest 后仅提交自己纳入的计划。不含新增外部操作授权或放宽产品验收。

## Current state

- 固定评审基线：0887b95bf900f50d2021a673aa7cfce967a2c3c2，分支 codex/open-environment-migration。
- 2026-10-04 上午独立实测：Agent 后端 15、ui-components 77、model-provider/chat-contribution 120、profile/integrations/chat 93，均通过；合计 305。不等于全量产品完成。
- 任务账实际 106/129 勾选；010=8/14、011=1/9、012=5/13。旧最终报告计数和部分日期过时。
- 已跟踪未提交文件：package-lock.json、packaging/bundle-manifest.json、products/desktop/extensions.lock.json。必须先解释来源，不能 reset、stash 全树或混入自己的首次提交。
- 评审原文（只读）：/home/maoqh/projects/ordessa/specs/026-open-environment-migration/reviews/overnight-acceptance-20261004.md。
- 654 前端全量、wheel/deb、Server 继承红集为上一执行者报告；本执行者必须重新证明承重条件，不能直接复制计数。

## Scope

工作目录为 /home/maoqh/projects/ordessa/worktree/026-open-environment-migration。开工先核对 HEAD/branch/status、章程、各目录 AGENTS 和是否仍有执行者写同一树。如果仍有另一执行者，停止写入并报告所有权冲突；不要杀进程。

必须读：原 charter.md、decisions.md、tasks.md、acceptance.md；contracts/agent-domain.md、frontend-infrastructure.md、frontend.md、environment.md、submission.md、recovery.md、lifecycle-evidence.md、shipping.md；orders/008、010–012 及对应最新 evidence。以实际存在的文件名为准。

写权仅用于原 026 职责、接线、测试、构建和文档的补齐。保留对外 ID、namespace、磁盘格式和已冻结保证；不新增产品功能、不全面美化 UI、不引入第二内核或兼容执行引擎。平台工具按 F5 既定归属组织：runtime 管机制、server-bridge 管授权投影/查询、ui-components 管 React/编辑工具、Workbench 管呈现。避免为归位重造另一份实现。

HostUiAdapter 属于当前实现的宿主适配接缝，可修正其内部条件写语义并同步全部调用方和独立样例；不得默默改冻结的 F5 公共合同。若原合同无法表达必要 revision 或保证，记录最小合同缺口、影响和选项，暂停该接缝而继续独立任务。

## Requirements

### Requirement: 快照不能被消费者改写，通知和生命周期受控

#### Scenario: 浅冻结的祖先不掩盖可变子对象
**WHEN** 创建 `{child:Object.freeze({nested:{value:1}})}` 并从只读快照尝试修改 nested.value，**THEN** 修改失败或没有效果，owner 值保持 1；不能出现值变成 2 且通知数为 0。

补循环对象、共享引用、重复读取身份稳定、no-op 不通知、批量更新单次完整通知、监听器抛错隔离和重入更新的有界执行。明确支持的数据形状；不能声称支持 Map/Set 等任意对象却仅 Object.freeze。拒绝不支持形状不能破坏已支持领域消费者。

#### Scenario: 释放后迟到回调失效
**WHEN** source snapshot(1) → projection.close() → 已排队 snapshot(2)/delta/gap 回调，**THEN** 不再修改投影或通知消费者；close 幂等。同步 attach 内 revoked、撤权、旧连接代次、缓冲 overflow、旧 cursor、零 credit 都有独立反例；按已冻结 E3/F5 定义处理，不能发明隐藏重连或自动效果重试。

查询 invalidation 发生于请求在飞时，旧结果不能将被失效记录重新标 fresh；scope 释放或代次变化后旧请求不能污染新 entry。任务 cancelWait 不显示原生工作已停止。

### Requirement: 共享 UI 保存必须真正冲突检测

#### Scenario: 同一版本的两个并发写只能一个成功
**WHEN** 两个独立 store/窗口共享同一宿主存储，以同一 ifRevision 并发写 A/B，**THEN** 恰一 written、另一 conflict，成功版本唯一且可按公开方式取得，不静默覆盖。必须有真实存储适配/两个独立客户端证据，不能只顺序执行或共用前端 singleton。

条件比较和提交在适配器的同一原子边界完成，revision 不能来自每窗口重置的计数器。缺真实适配时保持 session-only，不声称共享写或重启恢复；共享保证不可用须明确拒绝。

未知 schema 拒写且原记录保留；migrate 不能不迁任何数据却返回 migrated。迁移失败、存储失败、并发删除、命名空间隔离有 fixture；秘密/业务正文不进入 UI 偏好存储。安全值校验必须接入实际写入口，不能只是导出未调用的 helper。

### Requirement: 同一会话只有一个实际配置权威

#### Scenario: Profile 和模型控件操作同一配置目标
**WHEN** Profile A 包含 model=M1，随后单独选 M2，**THEN** 两控件显示共同配置投影中的 M2，A 的其他字段保持；再选只含 prompt 的 Profile B，模型仍 M2；再选包含 M1 的 A，模型变 M1。只覆盖操作包含字段。

后端 Agent owner 拥有会话事实；前端持授权投影、操作意图和编辑缓冲，不将这些当已确认事实。默认生产装配实际调用公开 AgentOwnerPort 并观察同一 canonical target，不各自创建 local Agent owner 拥有当前模型/确认事实。local 实现仅用于明确隔离的 fixture 或合同允许的独立 UI 目标，不能成为生产后端不可用的 fallback。

同会话多控件/多窗口看到相同 revision/代次；不同会话相互隔离。pending 与 confirmed 可区分但来自同一事实链。迟到 A 回执不回退 B，断线后不能以未知状态解锁可靠发送。不能只扫描 Map 消失或类名变 owner 就算完成。

#### Scenario: 没有 Profile 也能完成普通会话
**WHEN** 产品不安装/不启用 Profile，**THEN** Harness、provider/model、首轮和后续消息、历史恢复仍走实际生产接线；不自动创建全局 Profile，不偷启用其服务补依赖。

### Requirement: 可靠提交、结果和恢复保持原生边界

#### Scenario: 捕获后修改不改变已提交消息
**WHEN** capture 后发生新编辑、配置选择、切目标或附件内容改变，**THEN** 原 request 对应固定 target/binding/generation/schema/opIds/内容；新编辑保留，ABA 同文本不能清掉新稿。配置结果、输入接纳和原生运行结果分别记录。

可靠路径必须具备所声明的持久 request/fingerprint/reservation 和条件提交；raw-only 不伪装可靠。可靠路径失败/unknown 不能换 key、换 raw、换实例自动重发。

首次 create-with-config 与 existing session 分开；选择配置不创建会话，unknown 创建只核对原 creationAttempt，不 new 第二实例。输出期间切 Profile/model 只改变下次输入意图，不 stop 原生输出。

#### Scenario: 崩溃后只读核对，不重派效果
**WHEN** 在 mapping、possiblySubmitted、backend intent、native effect、domain result 各跨库窗口真实 kill 子进程，**THEN** fixture 重启只核对已有关联；原尝试不重发、不冒认旧 generation。历史启动即列，点击才原生 load/resume；本流程不自动调用模型。

三品牌的 restart/resume/切换保证只使用 Harness 声明的原生能力；不修原生内部非阻塞缺陷，不把审批、工具调用、workflow 等内部业务移入核心。原生能力缺席明确 unsupported，不能以静态假 ready 通过。

### Requirement: 干净发行产物而非源码兜底

#### Scenario: 无仓库源码仍可运行受控闭环
**WHEN** 在干净 fixture 中解包发行产物并禁用 repo editable/PYTHONPATH/npm 源码补依赖，**THEN** 默认产品与无 Profile 产品都可完成受控首轮、后续轮、关闭重开后的历史恢复；包入口、启用清单、插件变体和 F5 API/React 入口均从产物解析。

外部三个样例、backend-only/frontend-only 变体、缺 required 包拒启、旧兼容执行引擎不能补链，都按原 acceptance 验证。受控 Harness 可模拟外界效果，但必须经过实际装配/wire/owner/持久接线，不能直接调用 local fake owner 代替。

### Requirement: 每个验收 case 的结论必须有对应证据

#### Scenario: 套件绿不覆盖未执行场景
**WHEN** A107 发行测试未执行、A110 并发反例失败或 A104–A106 消费者未迁，**THEN** 对应标未验/失败/部分，而非引用某套件绿。同理 GUI、IME、真实模型不得用受控测试替代。

## Stages

每阶段固定 SHA、显式 pathspec 提交、更新本树 status/evidence。检查点是继续执行的窗口，不是等待用户的停点。

- [x] 0. 接管与基线：确认单一写者；逐个解释三个脏文件的差异，保留前执行者改动，记录处置；保存本单 digest 与基线；纠正报告计数/日期/假绿。重跑承重窄套件，登记逐 ID 继承失败，不以 stash 全树破坏现场。列出每个原 task 的证据与真实缺口。
- [ ] 1. F5 修复：先写浅冻结、关闭晚回调、并发 CAS 红首；修实现；覆盖前述相邻生命周期/query/schema 问题；真实适配和独立客户端验证；核对公共 exports、包归属、React/nonReact 独立消费。对应原 008 与 A96–A103/A110。
- [ ] 2. Agent 生产接线：完成共同 owner/投影/操作入口，拆除生产 local fallback；完成 T010-01 剩余边界、08/09/12/13/14。DraftOwner 与公共编辑工具分清，至少一个资源设置编辑页实用公共工具；任务/通知/查询消费者必须有实际调用证据。不要反复问已经确认的 Profile 可选与字段覆盖语义。
- [ ] 3. 提交与恢复：按 T011-02/03/04/05/06/07/09 完成可靠链、结果分记、首次/已有分流、三品牌受控切换与多会话隔离；真实子进程 kill 五窗，确认恢复零重派。移除双路径生产装配：单 Environment 核心被默认/无 Profile 产品实际使用，封存历史读取不参与新操作。
- [ ] 4. 发行验证：完成 T012-03/04/09/10/11/12/13 所有可受控执行部分；从产物验证闭包和两个产品变体，补 A66–A111 场景映射。生成产物不是启动证据；缺 required 资源对应失败，不允许 skip。
- [ ] 5. 独立复核与交接：最后自己复跑三反例、共同 owner 主链、无 Profile 两轮和产物主链，确认没有新增未解释失败/未提交源码；更新原任务账和本单报告；对真实 GUI/模型/系统安装/真实数据未授权项列准确操作清单。连续执行到受控收口或整队硬性阻塞，最终交回，不继续轮询烧预算。

## Parallel units

本单默认一个牵头会话串行实现，测试按 Desktop 规则串行；不默认启动子代理。若用户另行授权并行，先冻结接缝后可拆不共享文件的 F5 修复切片；契约、Git、lock、装配、status 仍唯一写者。禁止子代理自开下一层或多会话写同一树。

## Gates

| Gate | Assertion | Counter-example | Absent / unknown |
| --- | --- | --- | --- |
| G13-1 快照 | 不可变、稳定身份、批通知、重入有界 | 浅冻结祖先下直接修改后代；subscriber 无限递归 | FAIL，不限制样本来隐藏失败 |
| G13-2 生命周期 | close/撤权/旧代次后不投递 | close 后人为发送已排队回调；同步 revoked | FAIL，detach 不算全部证据 |
| G13-3 共享写 | 原子条件提交、真实唯一版本 | 两独立客户端同 ifRevision 同时写 | 无适配仅 session-only；共享保证 BLOCKED/unsupported，非通过 |
| G13-4 配置权威 | Profile/model 同 target/revision，生产共享公开 owner | 两 local owner 独立确认；只含 prompt 的 Profile 清模型 | FAIL，不能以 wrapper 或 Map 扫描通过 |
| G13-5 独立产品 | 无 Profile 仍走生产首/后续/恢复链 | 删除 Profile 后暗中重启其服务或自动新建预设 | FAIL，依赖缺席不 skip |
| G13-6 提交恢复 | 原尝试关联、结果分记、unknown 零重发 | kill 后换 key/raw/new 实例重派；旧 generation 冒认 | 缺原生保证拒相应路径；不降级 |
| G13-7 发行业务闭包 | 无源码兜底运行默认和无 Profile 受控主链 | 隐藏仓库源码后失败；required wheel 缺席照过 | FAIL，打包/解包单独不够 |
| G13-8 证据与安全 | case 对应实际场景，继承红逐 ID，零未授权外部操作 | 套件全绿覆盖未跑 GUI；新失败当继承；读真实 key | FAIL；涉及授权的部分停止并报告 |

## Validation

开工重测的最小命令（cwd 为本实施树；每个命令分别记录退出码，测试串行）：

```bash
node specs/026-open-environment-migration/checks/validate-package.mjs
.venv/bin/python -m pytest plugins/agent/backend/tests -q -p no:cacheprovider
./node_modules/.bin/vitest run --root packages/frontend/ui-components --maxWorkers=1
./node_modules/.bin/vitest run --root plugins/profile/integrations/chat --maxWorkers=1
./node_modules/.bin/vitest run --root plugins/model-provider/chat-contribution --maxWorkers=1
```

之后按实际发现映射执行 agent-contracts/chat/workbench、Environment/persistence/services、Server wire、typecheck/build/aggregate/Electron controlled 和干净产物验证。不存在的命令先修 runner/发现，不臆造通过。环境缺席不能沿用旧数字。

每条证据记录 command/cwd、源码 SHA/fixture 摘要、工具版本、exitCode、collected/pass/fail/error/skip、失败 ID/原因、正例/反例、保证范围。继承失败逐 ID 对照，不按总数相同归因；无关继承失败不要求本单扩大范围解决。

## DoD

实现、针对性反例、真实受控接缝、回归计数/退出码、清理安全、任务/证据分账六件齐。实际产品新增行为必须经过装配/wire 而非直接调用 fixture helper。检查 staging/测试进程和临时目录只清自己的已确认目标，不动用户数据或 Harness 系统资产。

## Acceptance

- CONTROLLED_SCOPE_DONE：仅指本单所有无需外部授权的实现、受控反例和干净发行验证通过；真实 T011-08/T012-05/A108/A111 必须另列 REAL_PENDING，不能宣布产品全部 DONE。
- PARTIAL：有产出但剩余工程/受控验证未完成，逐项列 task ID、文件、缺条件、下一步。不因已有构建成功申请整项合 main。
- BLOCKED：整队无任何独立可推进任务，给精确缺口、最小所需裁决/授权和已有恢复点。单项阻塞不停止其他 ready 项。

## Notes for the executor

不得 merge/push、新开工作树、安装系统资产、启停用户服务、改登录或读取 key/token 文件、迁移真实数据、调用真实模型。仅隔离 fixture/临时受控服务获本任务范围授权；必须自有端口/临时数据根/假凭据，并清理自己的进程。

普通内部实现自行选，不能把 CSS、测试排序、已定语义变成用户问题。真正冻结合同冲突或授权扩张，写本树 status 的 Questions：具体场景、最小选择、影响、建议，并继续独立工作。用户本次开会话不等于 blanket 外部授权。

新证据写本树 specs/026-open-environment-migration/evidence/closeout-20261004/；原历史报告保留可追溯说明，不删失败证据。主树只读，云端文档本单不写。不要为本单另造长期调度系统或第二任务账。

## Batch report

结束时填写：固定 SHA；原任务完成 ID；八道门的实际结果与指针；逐 suite 计数/退出码/失败 ID；三个初始脏文件处置；真实验收未执行项；成本未知则写未知；无权威冲突/二次重派/源码兜底的证据；唯一终态。

## Checkpoint report

每阶段在本树 status 写：检查点 SHA、刚完成什么、实际可试入口及期望、明确未完成、Questions、下一 ready 项。不要使用“最后一阶段”等进度口号；以具体 task ID 和证据说明。最终用户操作清单覆盖三品牌各两轮、Profile→model→Profile、输出时选配置、重启历史、无 Profile、多会话隔离及失败草稿，但不在缺授权时自行执行。
