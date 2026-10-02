# ZCode 接管：Profile 稀疏配置与独立模型应用

日期：2026-10-02，Asia/Shanghai。状态：READY_FOR_IMPLEMENTATION。

这是 **Spec Kit 021 的有界增量实施与验收合同**，不是新项目，不是持续整夜
巡检任务。完成本文指定范围即交付停写，不继续旧文档中的无限推进目标。
本文件中的最新用户裁定优先于旧 spec 的 replacement/reset/全清 overlay
口径；其余安全、真实证据和兼容要求不变。

## 0. 执行位置、范围与退出条件

- 工作目录：`/home/maoqh/projects/ordessa/worktree/021-ordessa-product-closeout`
- 当前分支：`nightly/021-harness-rollout-opencode-hermes-dsh-kilo`
- 交接 HEAD：`e560f7a19b9e1b1d0e876bdfde5fe43bb4b14873`
- **接管当前未提交工作，不从 HEAD 重建，不 stash/reset/checkout。** HEAD
  不包含今天的重要实现；本树初始脏状态就是交接基线，不是待丢弃垃圾。
- 根仓保持 main，其他工作树只读；不要新开分支、工作树、常驻会话。
- 当前 Codex 三个执行子代理已结束；Codex 不与本轮同时写实现。
- 本批不 commit/tag/merge/push。用户回来后由主控验收并决定提交。
- 目标只到本文 A/B/C；打包、公开分发、其他 Harness、协作系统不在内。
- 终态：`IMPLEMENTATION_REVIEW_READY`（实现与受控门全满足，实际用户验收
  单列），或 `PARTIAL_BLOCKED`（明确不可自行解决的阻塞，其他可做项已完成）。
  不得把“保存/队列成功”“API ready”“控件可见”写成模型应用完成。

### 写权

允许：

- `plugins/profile/**`：配置合成、会话状态、恢复与 Chat glue；必要的插件
  自有 schema 增量迁移与契约说明。
- `plugins/assets/model-provider/**`：目录解析、会话意图、生产端口和 Chat
  contribution；插件自有公开 DTO/方法的必要加法。
- `plugins/harness/src/ordessa_harness/configuration/**`、相应 Pi/Codex/Claude
  配置模块及测试：复用既有实际适配、owner/C4，不改变原生策略。
- `products/server/src/ordessa_server_product/**` 与对应测试：薄产品装配、
  可选 Profile 接缝、共享会话配置权威。
- `products/desktop/probe-profile-ui*.mjs`、相关脚本/测试：必要的验收增强。
- 本 spec 的 `takeover-progress.md`、本轮新报告/契约附录；旧证据保留。
- `products/desktop/extensions.lock.json` 仅允许 build 自动生成。

禁止：

- 改 `apps/server`、`packages/pacthold`、前后端 platform/host，或重写 Chat。
- 修改 `docs/ui-preview/01-empty.png`、`.zcodeignore` 等他属初始改动。
- 改凭据/用户 data-root/全局 `.codex`、`.claude`、Pi 配置；启停用户服务。
- 修上游 Harness 的密文历史、推理、工具授权、沙箱或原生内部缺陷。
- 删除原测试、skip/xfail、降级断言、伪造 readback、第二会话/应用账本。

如确实需要范围外改动：写清最小文件、原因、反例、影响，阻塞该项；
继续不受影响的项，不用架构大搬家解决本轮接线。

## 1. 开工必读与事实基线

依次读根 AGENTS、`docs/baseline.md`、`docs/architecture.md`、
`docs/known-issues.md` 的服务边界，再读本文和 `takeover-progress.md`。
旧 `overnight-*` 只作历史和既有证据，不重新启动其中的全部工作。
阅读各写入目录的局部 AGENTS；不要把陈旧仓库地图当成当前代码事实。

开工记录 branch/HEAD/status、允许目录的初始内容摘要；将不含秘密的
基线差分/日志存 `.cleanup-evidence/zcode-profile-model/`。不清理初始脏改动。

### 已有可复用产物——不要重写

1. `products/server/.../native_configuration.py`：本轮已从 Profile 抽离。
   端口 `native.configuration`；唯一观察到的 native owner 绑定唯一 canonical
   UID，生命周期随 ACP 运行轮。Profile 缺席/卸载不销毁此端口；旧轮拒绝。
2. `NativeModelServices`、C2 adapters、C4 `ConfigurationApplicationService`、
   `OperationJournal`、实际 readback、provider restart/resume 已存在。
   不新增通用 session/application engine。
3. 共享 journal 保持 `plugins/profile/native-configuration.sqlite` 的已有
   数据路径。路径历史名称不代表依赖 Profile；本轮不另建/重命名 ledger。
4. Profile Chat 已修普通续轮不重复 `selectForSession`；explicit pick 才选择。
   receipt/readback、失败草稿、等待期间新选择保留机制必须保留。
5. model-provider-chat 已启用、公共 Token 唯一、model-selector UI 真实注册。
   缺生产端口时诚实禁用；不要把这个状态改成无证据 supported。
6. Harness wheel verifier 与开发/发行共享 native plan 已实现。本批不再
   处理发行 launcher、deb、安装资产。

### 可核验的现状（不是本轮完成证据）

- 新反例 `plugins/profile/tests/test_sparse_profile_precedence.py`：主控亲跑
  **8F/5P**，13 例，exit 1；已有生产实现尚不满足新用户裁定。
- 添加这份新反例前，主控后端相关回归 769P；Profile Chat 59/59，
  typecheck/build exit 0，产品 19 扩展。加反例后不能再称全套全绿。
- Pi/Claude 实际开发 UI 各完成两次短真实回复和同会话 Profile 配置变化，
  journal confirmed/receipt `harness-api-confirmed`。**不是 installed deb，
  也未证明两个不同上游模型。** 不可复述成你本轮重新验证的结果。
- Codex 上游跨 provider 某些加密历史恢复缺陷仍属已知限制，本轮不修。
- ProductSkills 当前依赖 Profile，`include_profile=False` 省略 Skills；
  本轮只证明普通聊天/模型应用不依赖 Profile，不宣称 Skills 已解耦。

## 2. Spec：用户裁定与可观察行为

### FR-01：Profile 可选且只是预设清单

普通聊天和 provider/model 切换无需 Profile。未选择/未加载 Profile 时，
不得自动创建全局 Profile 或 Profile 会话记录来绕过接线缺口。
模型供应商的目录、凭据引用、模型资料属于 model-provider；原生差异、
实际应用、实例隔离、恢复和证据属于 Harness。Profile 不掌握品牌分支。

场景：`include_profile=False` → 创建受控普通会话 → 独立选模型 → 下次
发送前实际应用确认 → 才发送；Profile 数据库记录增量为零。

### FR-02：按项覆盖，不是全量替换

配置项身份为 `(facet_id, item_id)`，不能用整个 facet 代替 item mask。
后操作只覆盖它明确声明的项；Profile 省略某项，不意味着 reset/删除。

例子：

| 操作顺序 | 最终有效配置 |
| --- | --- |
| Profile A 含 model=M1、prompt=P1，再选 model=M2 | M2、P1 |
| 先选 M2，再选含 model=M1 的 A | M1、A 声明的其他项 |
| 先选 M2，再选只含 prompt=P2 的 B | M2、P2，其余项保留 |
| B 只含 style/choice，不含同 facet 的 style/detail | detail 原值仍有效 |

仅因新 Profile 未包含旧项，不能生成 reset，也不能删除该项的临时修改。
显式移除/reset 是另一种明确意图，不能从“没有字段”推断；本批不增加
新 reset UI。清除 Profile 内某配置项的保存值，不等于立即清除会话原生值。

### FR-03：会话临时改动与全局预设分离

会话修改不回写全局 Profile。当前 Profile 全局更新：未被用户临时改动的
项可在下一次发送生效；用户临时改过的同项继续被覆盖，其他全局项仍跟随。
切换 Profile 仅覆盖本次声明 mask 内的旧临时项；mask 外保持。
保留项不能被伪装成新 Profile 的全局保存值，也不能变成阻止未来全局更新
的“用户手动 override”。必须区分保留的会话基底和用户显式临时覆盖。

### FR-04：下次发送生效，不中断输出

选择动作只记录意图，不 apply、restart、release 或 prompt。
对同一 native session，发送冻结本次选择/目录 revision/owner/generation。
应用期间的新 pick、新 override 留到下一次发送；旧结果不得消费新意图。
前端不能靠渲染调用 `session/new` 创建空会话。

### FR-05：一次有效配置应用，单一原生权威

Profile 可选目标和单项资源意图在产品接缝合成有效配置，提交时只执行
一次完整的共享应用管线。需要 provider restart/resume 的 Harness 内部
步骤不算另一条业务应用链；禁止 Profile 默认值先 apply、模型再 apply。
普通续轮不得覆回旧 Profile 模型。

owner/UID/generation、适配发布 token、C4 unknown/BUSY 围栏与 journal 共用。
可以保留资源插件自己的 desired/sequence 状态，但实际应用结果只能引用
共享 C4 operation + 独立 readback，不建第二份真实结果 authority。
不要将普通会话状态寄存在必须安装 Profile 才有的容器里。

### FR-06：确认、拒绝、未知及恢复

- Confirmed：实际原生 readback 与目标、owner、generation、目录版本吻合，
  才允许该次 prompt；只消费本次版本的选择/覆盖。
- Refused：零 prompt，原有效配置/草稿保留，所选意图可由用户显式重试；
  不自动重试、不偷偷用旧配置继续发送。
- Unknown：零 prompt，保留不安全状态和新旧意图的身份；query/reconcile
  只观察、不重放 apply/prompt/resume；后续不能因为队列已 pop 而误放行。
- 外部成功、本地 commit 失败：记录可对账的 unknown，不清新 pick 或 overlay。
- 对账用本次 admission 冻结的事实，不能用后来更新的 Profile mask。
- 所有 UI 恢复、receipt 和队列消费都以 exact session/operation/sequence
  围栏处理；同 native sessionId 在不同 channel 时不得串路由。

## 3. Plan：归属、接缝与实现约束

### A. Profile 稀疏项合成与恢复

重点文件：`core.py`、`sessions.py`、`repository.py`、既有 resolver/journal。

1. 消除“current ∪ target → omitted reset”的 replacement 逻辑。冻结
   目标 Profile 的不可变 revision 和明确 item mask，合成当前有效基底+
   本次 patch；required/conflict 验证不能只看稀疏 target 而忽略现有效项。
2. 保留省略的旧基底项在下一轮及 inspect/projection 中的有效性。不能
   只保留 overlay，否则没有 overlay 的原 model 仍会在切换后消失。
3. 原生首发仍需完整有效目标确认；“已保存相同值”不是已应用证据，
   不得恢复为空 desired 而触发 native port 的空模型差分失败。
4. 成功/对账只消费 frozen mask 内 **admission 版本仍匹配** 的 overlay。
   时间戳或值相等不够证明没有较新写入（同值重写也是新意图）。
5. 在现有 journal/会话状态内保存必要的非秘密恢复事实：来源 revision、
   mask、旧基底身份、pending sequence、overlay revision、关联 operation。
   不把完整秘密写进 `detail_refs`；它是引用字段，不是随意塞状态的口袋。
6. success/rejected/unknown/commitfail/reconcile 都在事务内重读当前行，
   CAS 消费本次选择；`_mark_needs_recovery` 只更新安全状态，不回灌旧 pending。
7. 若需要 schema 增量，采用插件自己的幂等向前迁移，保留旧库/标识，
   补迁移反例；不能直接重建/清空库或仅对全新 DB 实现正确。

### B. 独立模型消费者与发送接线

重点：model-provider `{choices,next_turn,harness_binding,plugin}.py`，
产品 `native_configuration.py/profile_configuration.py/composition.py`，
model-provider Chat contribution 和 Profile glue。

1. 注入当前轮 `native.configuration`；按真正观察到的 channel/native owner
   解析 target。客户端的 UI sessionId/canonical UID 不能代替后端 owner。
   对信息不足或有歧义的目标 typed refusal，不能“找到第一个就用”。
2. 不生产复用旧 `ConfigurationServiceHarnessPort` 的伪 readback：目前它
   固定 target、缓存请求 model 充当读回、操作键缺 version/generation。
   必须改接当前 session C4、fresh readback、资源目录解析和 credential refs。
3. 修 `NextTurnSelector` 的提前 pop：冻结 sequence 后确认才消费该版本；
   Refused 保留；Unknown 阻塞后续；晚到结果不能清掉更新选择。
4. 模型临时意图由 model-provider 拥有。产品可选桥接 Profile 的有效项，
   但不能 require/import Profile 才能独立选择，也不能 policy 拒绝后旁路。
5. 模型 wire 的 choose 仍只排队，query/reconcile 仍只读。允许在该插件
   注册薄的 `modelProvider.beginTurnApplication` 提交方法来消费冻结意图；
   契约由执行主会话在改调用者前写成附录，注册、客户端 DTO、反例同步。
   必备语义：稳定 submission operationKey、exact native target、期望意图
   sequence；返回 ready/refused/unknown 与匹配的 operation/目标/序列及
   真正应用证据引用。字段校验 fail closed，不能任意布尔值放行。
   如果复用既有后端 prompt 边界可完全满足同样判据，也可不新增方法，
   但不得同时实现两套实际 apply 入口。两种方案选择及原因须写进本轮附录。
6. Profile 与模型的前端 guard 不得各自 apply。通过现有 Chat guard 接缝
   与上述产品共享入口保证一条实际应用；同时维护双方独立 UI/生命周期。
7. 明确记录用户 **选择动作的先后**，不能用 guard order 或 apply/网络
   返回顺序当成用户选择顺序。无序/旧 sequence 不可猜测；补乱序反例。
8. 支持空闲与正在输出时选择；输出不被中断，下次输入才应用。
   不解读品牌内部历史、不读取全局配置、不复制整个 native home。

### C. 收口

只改自有接缝和发现的相关 Ordessa 缺陷。生产链确实遇到 upstream 原生
限制：记录已知限制并 honest fail closed，不进入修 Harness 本体任务。
无法确认的安装资产/认证/DNS不得弱化 trust 检查来造绿。

## 4. Tasks 与并行

ZCode 主会话负责契约附录、产品共同接缝、集成、账本与最终复跑。
允许最多 **2 个有界子代理**，深度 1；不得再开常驻会话。默认组合：

- A 子代理：Profile backend + 独立测试；不写产品接缝/契约/账本。
- B 子代理：model-provider backend 队列与生产消费端口的局部实现/反例；
  不写 Profile/产品接缝/前端/契约/账本。
- 主会话：先冻结接口附录，之后串行接产品桥和两前端 integration。

共同契约、同一文件、字段优先级与一次应用合成不得分给两个写者。
没必要开子代理的纯机械小修直接做；不用多层代理/反复独立重跑浪费额度。

- [ ] T00 接管初始差分、确认无竞争写者、复跑 13 例红账本。
- [ ] T01 写最小接口/恢复事实附录；保留本文产品语义，不自行换架构。
- [ ] T02 A：13 例全部转绿；补同值重写、迁移、晚 pick 对账与重复恢复。
- [ ] T03 B：独立模型意图和真实共享端口；无 Profile 的受控实际应用闭环。
- [ ] T04 产品/前端合成：同项最后动作优先、异项保留、单次 apply。
- [ ] T05 完整受控矩阵与三品牌 native 端口检查。
- [ ] T06 主会话复跑回归、build、文档、交付；停写等待我们验收。

依赖：T00→T01→(T02 || T03)→T04→T05→T06。
每项报告 pass/fail/blocked + 证据；不得因拿到一个绿 checkpoint 扩展 scope。

## 5. Acceptance：完成门（逐行留证据）

每行必须有实际 test ID/命令/退出码；缺席、未知、fixture 不足不能计 PASS。

| ID | 必须证明 | 必须能抓到的反例 |
| --- | --- | --- |
| P01 | 13 条新语义反例全绿 | 原状态 8F，不能改掉这些核心断言 |
| P02 | prompt/style-only patch 不 reset 模型 | 旧 union/reset 编译 |
| P03 | model-only patch 保留其他项到后续轮/inspect | 只改 apply，不保留有效状态 |
| P04 | 同 facet sibling 保留，精确 item mask | 按整 facet 清覆盖 |
| P05 | 临时值不回写全局 Profile | 比较保存库前后版本/值 |
| P06 | 全局改未覆盖项生效，用户改过项不被盖 | 把 retained 基底误标为用户 overlay |
| P07 | 对账用 admission mask 与来源 revision | unknown 后全局新增字段导致误清 |
| P08 | success/rejected/unknown/commitfail 保留晚 pick | 旧快照 upsert 回灌 pending |
| P09 | 旧 apply 不清后来写的 overlay（含同值重写） | 按字段/值/非唯一时间戳删除 |
| P10 | 再次对账/重复 operation 幂等、零新 effect | query/reconcile 隐式重试 |
| P11 | 原生首发相同 desired 仍获得真实确认 | 空 diff 重新出现 |
| M01 | 无 Profile 时独立选模型→应用→prompt | 偷建 Profile 或依赖其 Token/记录 |
| M02 | Profile 卸载后普通会话/模型仍工作 | shared authority 被其 disposal 关闭 |
| M03 | Profile A→model B，同项 B 胜 | 固定 Profile guard 顺序盖回 A |
| M04 | model B→含 model 的 A，A 胜 | 旧 pending 下轮又复活 B |
| M05 | model B→不含 model 的 A，B 保留 | 全清/reset 或全 Profile 取代模型 |
| M06 | 同一 submit 仅一个有效 application | 两 guard 分别 apply；统计 side-effect 次数 |
| M07 | ordinary 下一轮保持有效临时模型 | Profile 每轮复写默认模型 |
| M08 | 队列拒绝/未知不 pop 后放行；零 prompt | unknown 下一次变“无队列” |
| M09 | 同 ID 不同 channel/owner/generation 不串路 | 只用 nativeSessionId/旧 target 路由 |
| M10 | 目录修改/凭据变化/适配卸载后旧 plan 拒绝 | 复用旧版本/旧 publication token |
| M11 | 输出时只排意图，下一轮生效 | 选择立即 restart/中断当前 run |
| M12 | 新选择、乱序回包、切页不消费旧/其他状态 | 迟到结果改 UI 或覆盖更新的意图 |
| M13 | Pi/Codex/Claude 都用注册的真实 Harness 端口 | 生产 fake supported/缓存请求读回 |
| C01 | 同一 shared C4 journal unknown fence 阻止双消费方 | 两套真实结果 ledger/独立锁 |
| C02 | stop/start 后新 authority，旧引用失效 | 复用上一轮 owner/services |
| C03 | 插件缺席/资源不支持时明确拒绝且零 prompt | 缺端口 fallback/default success |
| C04 | 旧数据库迁移不丢记录，重启可恢复/对账 | 只给新 DB 建 schema 或清库 |
| C05 | 全部新功能接线进入真实产品装配 | 只测试未被产品启用的函数 |

旧测试若明确钉了“省略即 reset”或“清全部 overlay”，允许 **按最新用户
裁定**改为更强的 sparse/mask 断言；逐 ID 列 old→new 与理由。不得删除
覆盖、改无关红例或用 skip 掩盖。重点旧用例：native_turn_application 的
cross_profile_removals、sessions_v2 reset、brand_matrix_pa5 reset、
harness_real_service reset unsupported、us2_switch 全清、C05 注释/断言。

## 6. 可直接复跑的门与环境

所有命令从本文工作目录执行；Python 用独立 integration venv，不能改
共享 `.venv` editable 指向。环境缺依赖要先查是否用错解释器，不先重装。

```bash
.cleanup-evidence/product-integration-venv/bin/python -m pytest plugins/profile/tests/test_sparse_profile_precedence.py -q
.cleanup-evidence/product-integration-venv/bin/python -m pytest products/server/tests plugins/profile/tests plugins/assets/model-provider/server/tests plugins/harness/tests/configuration_model -q
npm test --workspace=@ordessa/plugin-profile-chat -- --reporter=dot
npm test --workspace=@ordessa/plugin-model-provider-chat -- --reporter=dot
npm run typecheck
npm run build
git diff --check
```

最终 root gate（生产 trust 校验需要能看到真实 root 资产所有权；沙箱
映射 nobody 不是放松 trust 的理由）：

```bash
ORDESSA_WIRE_LIVE_PYTHON=/home/maoqh/projects/ordessa/worktree/021-ordessa-product-closeout/.cleanup-evidence/product-integration-venv/bin/python \
ORDESSA_BUNDLED_ROOT=/home/maoqh/projects/ordessa/worktree/021-ordessa-product-closeout/.cleanup-evidence/product-dev-runtime-URGO6TDv \
ORDESSA_PREVIEW_OUT=/tmp/ordessa-zcode-profile-model-preview \
npm test
```

对新增目录/模块补相应 workspace/package tests，不以 root suite 聚合缺席
为理由省略。全量 Python 红例按 ID 和原因与 **开工基线**比较，不能只有总数。
门不支持上述本地环境时记录具体缺席项；不把 fake/env error 当实际成功。

## 7. 无人期间权限与真实验收分账

本次派发默认只做实现、受控测试、无模型的 native 端口验证；**不要读取
key.txt、发真实模型请求、触发浏览器登录或 sudo 安装**。用户回来后我们
共同验收实际三品牌聊天/模型/Profile。历史授权与真实证据保留，不复制
成此次模型调用或安装的授权。若资产必须更新，生成可审的构建/安装请求，
不发布到 /opt；列明哪个实际场景被旧资产挡住，其他受控项继续推进。

三品牌无模型检查使用已安装且完整验证的资产，拒绝 missing manifest/
trust/hash。真实聊天未跑写 NOT_RUN；公开 Claude license closure、完整
deb/安装验收、Codex upstream 密文恢复限制均不在本批解决范围。

## 8. 交付文件与人工验收步骤

主会话更新 `takeover-progress.md` 并新建 `zcode-profile-model-report.md`：

1. 本批净修改面（区分接手初始改动）、接口附录/迁移说明。
2. T00–T06 与 P/M/C 每行状态、test ID、命令、计数、退出码、证据路径。
3. 新旧测试语义变更清单；所有原绿退化/新增红必须解决或明确阻塞。
4. 实际模型/安装/真实 UI 分账：未跑不能勾选；不得只写“可交付”。
5. 我们回来可复跑的启动命令和 5 步操作：普通无 Profile→选模型发送；
   绑定 Profile→再改模型；反向顺序；省略模型的 Profile；输出中选择。
   写期望有效配置、是否调用原生 apply、同会话标识与已知限制。
6. 终态、阻塞及最小用户动作，完成后停止写入；不启动新任务/后台巡检。

无小阻塞停工：普通代码/测试/依赖接线问题在写权内直接解决。遇到需要
改变本文产品语义、修改 host、用户凭据/服务/系统资产、或修上游 Harness
的硬边界，登记并继续独立项；禁止以“难”为由模糊降级，也禁止为不停工
越过安全边界。我们回来一次审完整 diff 与证据，而不是逐个补丁复制粘贴。
