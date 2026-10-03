# 迁移状态

## 2026-10-03 003 空环境完成（codeReady）

前序：002@8155d4b1a5。`pacthold.environment.Environment` 落地（经 public 导出）：实例级唯一索引
（activation/instance/capability/Object 全键/Activity 按 request key/Usage）、显式空启用集
（installed≠enabled）、history-read 与 use/invoke 分权、reliable 缺端口发前拒+raw 存活、
request key 同 digest 重放/异 digest 冲突、双环境零共享。测试：pacthold 229 绿（+11 新，含
in-tree 子进程零产品 import）；隔离 wheel+fresh venv 启动只读验证通过（/tmp 受控）。
守卫修订三处（public 链允许 environment 模块并新增产品前缀禁入；n4r1 allowlist 唯一合同包；
pacthold 依赖 +ordessa-environment-api，006/012 同步安装闭包）。证据 evidence/order-003-report.md。
003=DONE（codeReady）；004 解锁。缺口如实：drain/retire/reply/subscribe 属 004；C2 同根排他属 005。

## 2026-10-03 002 合同冻结完成（codeReady）

前序：001@51889021a0。002 交付：

- **编译合同**：`packages/backend/environment-api`（新 dist `ordessa-environment-api`，stdlib-only、零状态；
  identity/targets/guarantee/sequences/receipts/references/services/ports/errors/codec；
  CONTRACT_VERSION=`oe-contract/1`）+ TS 镜像 `foundation/src/open-environment/`（codec/types，
  esbuild 产物上逐字节断言）+ A1 面 `plugins/agent/contracts/src/config-owner.ts`（v0.2.0 追加导出）。
  共享向量 `tests/contracts/vectors/open-environment.json`（17 例，Python 权威生成）。
- **六份台账**（evidence/contracts/，JSON 全部可解析，hash 见 manifest.md）：public-api、identity-map
  （88 wire 方法逐 owner + 钉面外 2 方法闭合=`modelProvider.beginTurnApplication`+`acp.sessions.list`、
  18+5 extension 身份、33 workspace、29 dist、carrier/token 面、兼容构造退出单）、authority-map（20 类
  事实 owner，侦察修正 2 处：set_overlay 实现在 profile 插件、Linux SecretStore 在产品层）、
  capability-matrix（7 品牌×资源实际状态，惰性链如实标 inert）、contract-tests（33+6 绿）、
  domain-paths（逻辑 manifest schema + 24 行映射）、guarantee-levels（Q01–Q12 + request-key MAC 编码 +
  M04–M06 映射）。
- **测试接线**：`node-test:packages/desktop-platform/contracts` 入聚合（41→42 suites；连带把从未入聚合的
  token-identity.test.mjs 纳入门）。合同套件：Python 33 绿、TS 6 绿；typecheck 绿；workbench/chat-api/
  agent-connections/agent-sessions 绿；pacthold 218 绿；runtime-compat 163 绿；products/desktop 1 红=
  001 已登记继承红（pi 钉名）。发现并登记：pytest 组合调用 pacthold+runtime-compat 有同名测试模块收集
  冲突（分开跑均绿，按 baseline.md 串行单套件调用）。
- 002=DONE（codeReady）；003 解锁。侦察子代理 2 个（repo-scout），只读，主代理复核采纳。

## 2026-10-03 001 受控基线完成（codeReady）

启动词授权后，起点 `ebe712c796`。T001-01…07 全部完成，证据在
`evidence/baseline/`（T001-01-03-report、source-manifest-a/b 双算一致、suite-discovery、
test-baseline、baseline-receipt、server-red-ids）。四门过：来源/授权链核对（含 3 份 AGENTS、
known-issues §Services 不触碰清单）、3347 文件分类 0 违规 0 symlink、发现表（npm 41 套件、
Python collect 218/846/1264/163/9/59、Go 10 包、rig 81）、受控基线逐 ID/原因记录。
**001=DONE(codeReady)；002 解锁。**

基线快照（详见 test-baseline.md）：pacthold 218P 绿；harness 3F=台账继承集；runtime-compat
163P 绿；server-compat 2F（`native_identity_for` kwarg 漂移，69c0ea2818）；apps/server
78F/2E（钉面漂移 10 ID 已证机制——live 88 vs 钉 86——精确方法归因 UNKNOWN 留 002 identity-map
闭合；其余为继承/scope-red 类别）；acp_orchestration 28F=裁决保留；Go 桥 7ok 全绿；JS 33/41
绿，红=products/desktop 1（pi 资产钉名，865f3ab45f 同提交漂移）+rig 1（发送钮 a11y 文本，
865f3ab45f）+electron 6 腿（环境前置：/opt/ordessa 无 python/bin，安装未授权，U/P 缺口）。
环境修复记录：根 npm ci 曾被管道掩盖失败、重装恢复；claude 打包闭包与 ACP rig 闭包本地补装；
venv 需 setuptools。无断言删除/无 skip 求绿。

## 2026-10-03 R6兼容退役修订

已完成方案盘点：以实施树8d4bc64为源码来源，99个Python模块/9份SQL，扫描1349个tracked Python文件，179个包外绝对import引用文件（含测试）。路径/符号/消费者见evidence/compat-inventory.json，目标归属与退役要求见compat-retirement.md。
取消永久legacy-compat领域插件；002/006/007/010/012及A95纳入逐符号迁移与C95-1–7必需断言。12工单/114任务/95主case保持，不能以目录移动代替退役。静态盘点不覆盖动态/相对/发行/wire引用，002需补齐；未运行产品测试，未改产品源码/服务/真实数据。本次方案在准备实施分支检查点固化，主树只保方案工作副本，不提交main。
主树及准备实施树方案结构检查均PASS（23破坏样本）；不是新增子断言已通过，也不是独立架构复审。实施树001仍source-prepared/PARTIAL，后序未开始，本段不覆盖既有受控基线缺项。

2026-10-03：R2方案完成三角度攻击→修订→复核，见reviews/report.md；当前R4生产迁移未开始，001–012全为NOT_STARTED。12工单/114任务/95验收。main/P只读检查不算001源冻结完成；没有当前生产回归/GUI/模型证据。

R3补E3/F3受管理能力关联、领域单写者和订阅/操作生命周期；同一Pacthold Environment承载，不增关系核心，不引入外部业务语义。M10确认，新增A66–A75及工单分配。R3未独立审查；结构校验不算实现验证。本轮仅文档、不派工、不编码/提交，沿用本包设计阶段流程豁免。

R4按用户要求补3遗漏和2合同细化：E4/F4平台服务、E5持久关联、A1 Agent公共领域接口与plugin-architecture目标格局。新增18任务/20验收，写权同步；平台适配包无治理状态，逻辑插件manifest不二次调度，兼容发行/数据ID保留。R4仅主会话校核，尚未独立攻击或生产验证；无云端更新/发布、源码迁移或服务操作。

## 用户决策
R5完成主会话整包回审：8类设计/执行接缝已补，execution-detail建立R01–R17追踪与具体交付，启动循环/可用性归属/缺写权/阶段漂移已修。结构校验12/114/95、23破坏样本PASS；没有独立新增复审或产品验证。实施仍NOT_STARTED，启动范围待001确认。

M04/M05/M06已确认。操作授权仍按decisions M09。

## 进度
任务表见tasks.md。不得用包数/文件移动数换算完成百分比。codeReady与fullDone分列，前者只解锁声明的S/I依赖，不把U/P待验升级完成。阶段完成统计为已通过必需task数/总数，同时单列缺授权验收，不能用百分比遮蔽真实缺口。

## 证据层次
source-inspected / design-reviewed / finite-reference / controlled-integration / product-real。本包当前仅前两级待审；024/025有限参考不算新生产证据。

## Questions
尚需实施前确认源合成与实施工作目录/编码范围；真实数据和运行授权按后续具体方案提出，不提前泛化索取。

## Spend
本轮仅文档与只读审查；真实模型测试0。子代理请求及费用无法精确取得时标未知，不伪记。

## Checkpoints
无迁移实现检查点；已准备源码/方案基线4ec124a2fce10878d55808963ac7e471dc4f7354，见evidence/preparation-receipt.md。

## 实施准备（最新）
2026-10-03用户已授权新树和批准范围基线提交，M12记录见准备回执。001现为PARTIAL/source-prepared，尚无codeReady：来源快照已固定，测试发现/隔离基线及剩余指令盘点未跑。002–012仍NOT_STARTED。旧“全NOT_STARTED/待源许可”描述为R5审查时点，不是本次准备后的状态。
zcode主代理建议GLM-5.3；子代理配置/工具/简短启动词见zcode-handoff.md。没有配置或调用真实代理模型。
