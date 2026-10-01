# 夜间任务清单：依赖、落点与完成条件

仅Lead勾选任务；task绿必须对应 `overnight-acceptance.md` 的ID证据。
不因worker结束、一个套件绿、构建成功或一个品牌可聊天而勾整项。
接口以当前公有源码为准，本文件不授权发明新公共协议。

## T0 · 现场认领、起点与资源（Lead，所有任务前置）

- [ ] **T0.1** 核实 cwd/branch/HEAD/worktree列表/status/本树AGENTS，root仍main；
  本树改动中区分Codex接管草稿、他属截图、本次交接文档，不reset/stash/clean。
- [ ] **T0.2** 记录未提交草稿文件清单与内容hash、当前asset manifests、Pythoneditable来源；
  不把共享venv editable重装到别棵树。旧实现/失败日志保持可追溯。
- [ ] **T0.3** 本树实际跑一次轻量Node native-profile与Python相关基线，
  记录实测而不是抄50/330；新增/已修改门已经在草稿中，基线不是“修复前”。
- [ ] **T0.4** 盘点live services，只读确认能操作的都是本任务自有进程；
  sudo/keyring/login/端点状态分别记available/unavailable/unknown，不能一锅当网络问题。
- [ ] **T0.5** 委派A/C/D三个文件面，worker只拿其需要文档/源码；Lead独占git、文档、产品接线与真实测试。
- [ ] **T0.6** 建ID证据索引，进度顶部写本轮NOW/NEXT/BLOCKED；复核实际npm聚合门清单。

交付：CP-N0现场记录。T1/T3/T4/T6开始；不为补全全量基线耽误所有独立小测试，
但最终inherited-red必须有同环境可比较起点。

## T1 · 原生进程替换与故障回收（A，依赖T0）

落点：`plugins/harness/packaging/native-profile/codex-process*`、`enhance.mjs`、
`bridge.mjs`、`restoration.mjs`、相关native-profile tests。

- [ ] **T1.1** 补launcher/native区分及强杀孤儿反例，先运行现有草稿确认能抓到缺口。
- [ ] **T1.2** 修改原生启动策略，使关闭/TERM/KILL观察的确是实际native所有者；
  直接binary方案在Harness内使用已锁定/已校验artifact的原生位置，不把路径拼接暴露products。
- [ ] **T1.3** 退出确认后才spawn新native；stop窗口、init异常、ACP关闭清理有界，
  一个失败保留主异常及清理失败，不能仅killflag通过。
- [ ] **T1.4** 接fresh Codex client、availableCommands与event handlers；
  保存已有ACP client capabilities/config选项，清理旧session callback。
- [ ] **T1.5** 本owner thread/read获取rollout，严格路径/文件/UID/identity校验，
  同历史跨instance允许仅私有已绑定路径；防止客户端任意path注入。
- [ ] **T1.6** 原生resume同thread、config/application/model/preferences独立确认；
  不足以证明历史的空thread或损坏rollout拒绝，禁止newSession兜底。
- [ ] **T1.7** busy/transport-loss/exit-loss/Unknown/query/同ID不同参数反例齐全。
- [ ] **T1.8** Lead亲跑全部A01–A24门，审processgroups/PID复用/事件订阅/失败绑定；
  草稿未经这一步不得提交为“原生恢复完成”。

交付：CP-N1，A条完整L1与实际进程L2；未有真实历史时准确保留A23依赖。

## T2 · 双向目的地、恢复票据与 C4（A+Lead，依赖T1；不与T1抢同文件）

落点：Harness `configuration/model/{backend,restoration,provider_registration,initial}.*`、
native-profile bridge/reader、Harness owner/action tests。

- [ ] **T2.1** API→managed-account由Harness账户工厂解析，原生account/read检查；
  no factory/unlogged/wrongscope先于任何停止/恢复效果拒绝。
- [ ] **T2.2** 每实例官方/API env切换、gatewayConfig/认证头清理，
  既有官方B不被A的改动影响；不使用profile HOME、不复制账号凭据。
- [ ] **T2.3** effect-once恢复request/独立query保留；获取新owner/generation票据后重新Profile应用。
- [ ] **T2.4** 审privateRPC路由的调用者授权/字段约束、旧asset行为、错误脱敏；
  没有真实重启能力的资产不能凭旧ACK得到新成功证明。
- [ ] **T2.5** 受控三段official→API→official保留same canonical/native，
  重启新代次、旧target拒绝、query/replay不重启、每轮C4确认后才发消息。
- [ ] **T2.6** Lead亲跑B01–B09/B12–B14与A影响门，保留B10/B11实测缺项。

交付：CP-N2 Harness部分；可以构建T5。T7真实目标地/历史是独立硬门，不能在此勾它。

## T3 · Profile/供应商中性语义（C，依赖T0；可与T1/T4并行）

写权：`plugins/profile/src/**`、`plugins/profile/tests/**`；
`plugins/assets/model-provider/server/**`及`profile-contribution/**`中的Python源码/测试。
不写这些目录的README/pyproject/契约/全局锁；需要装配修改交Lead。

- [ ] **T3.1** 按C01–C08补逐字段overlay、全局revision竞态、显式切profile清空、输出中零效果反例。
- [ ] **T3.2** 对C09–C13的卸载保数据、首发失败、Unknown、失效owner验证，不造新operation状态机。
- [ ] **T3.3** ModelProvider catalogue/API Key/语法与probe分离、keyring错误路径及账号/API引用边界。
- [ ] **T3.4** 实现最小修复，只消费既有Harness能力。所有Codex/Claude/Pi分支交A，不移入Profile。
- [ ] **T3.5** C19–C21 CRUD/持久化/边界测试；注入越界import证明门能抓住。
- [ ] **T3.6** Lead亲跑C01–C22相关L1，产出实际产品场景参数供T7/T8复用；
  不能将受控fixture的330P当当前实际DB/原生配置证据。

交付：中性语义测试与修复；供CP-N2。涉及Harness私有字段不用等A完成也不能越权猜接口。

## T4 · 前端选择与发送交互（D，依赖T0；可与T1/T3并行）

写权：`plugins/profile/frontend/**`、`plugins/profile/integrations/chat/**`、
`plugins/chat/frontend/**`、`plugins/connectors/{acp,ordessa}/**`、
`plugins/assets/model-provider/{desktop,chat-contribution}/**`中的TS/TSX/CSS与局部测试。
不改shared contracts/package-lock/products/host。Chat-contribution实际selector不能漏掉。

- [ ] **T4.1** 检查Profile picker/Provider picker当前生产入口是否都已装配，不凭preview判定。
- [ ] **T4.2** D02–D10：草稿零会话、首发次序、输出中选择、下一发送、最新选择、Unknown零重放。
- [ ] **T4.3** D11–D15：加载恢复/已知历史列表/多session事件工具审批/滚动与完成态。
- [ ] **T4.4** D19–D23：实际场景预备、断连拒绝/重启诚实状态/账号入口/renderer不持密钥。
- [ ] **T4.5** 在现有界面做最小修复，不重画Workbench、再造UI库或改变用户交互方案。
- [ ] **T4.6** Lead亲跑L1、检查无品牌分支/越界import；交实际Electron驱动脚本/步骤给T8。

交付：CP-N2前端部分。D16–D18/D24仍等新可信asset和生产运行，不能让fake server替代。

## T5 · 新Codex候选与可信安装材料（Lead，依赖T2）

- [ ] **T5.1** 从锁定源重建全closure，校验固定sourceLockDigest/源文件pin；
  当前候选是草稿产物，任何修复后重新计算digest，不能复用handoff摘要。
- [ ] **T5.2** 候选实际初始化、官方/API独立readback、零模型首次准备验证；
  本次自有进程清理。初始nomodel probe已存在，可复用不另写重复框架。
- [ ] **T5.3** 封装root不可写资产校验，生成唯一新destination安装脚本；
  pin完整摘要/verifier/清单，stage失败不publish，不覆盖旧目录。
- [ ] **T5.4** 输出用户可直接运行的安装命令与作用面；sudo缺席时P05/B10/B11保持阻塞。
- [ ] **T5.5** 用户提交安装结果后重新运行可信验证，不只相信“Verified”文字。
- [ ] **T5.6** 更新产品asset选择及probe显式覆盖，确保prod测试仍走相同严格verifier；
  candidate开发路径可做开发探针，不能据此伪称installed-prod通过。

交付：CP-N3可信候选（安装前/后分别标），P01–P07相应门。无sudo继续T3/T4/T6/S/离线最终回归。

## T6 · 产品装配/发行路径审计与最小修复（Lead，T0后可先审计）

- [ ] **T6.1** 真实检查 products/desktop默认manifest/lock与products/server entrypoints：
  三Harness、Profile/模型选择/Key存储/账号入口前后端均存在，不只是contract包存在。
- [ ] **T6.2** 盘点packaging是否包含当前增强assets，以及安装后userland如何找到它们。
  特别检查 `run-native.mjs`、`probe-profile-ui.mjs`、Codex probe 仍固定旧目录的落点。
- [ ] **T6.3** 建“打包漏asset/漏plugin/source-only绝对路径”反例，修release映射；
  Harness内部解析binary，不让产品装配自己计算Go/Pi/Claude内部路径。
- [ ] **T6.4** 安全默认data-root/原生instance目录/账号目录/keyring配置，与开发临时root隔离。
- [ ] **T6.5** 默认launcher传Server origin/token与进程监管检查；不得回退只启动空shell。
- [ ] **T6.6** S01–S05已有资源smoke审计；合同缺项记录，普通缺装配/接线可修，
  新的大型资源适配必须报决策，不能偷偷扩scope。

交付：P08–P12/S证据、发行接线修复。最终deb绑定T5通过的新asset，真实安装等用户授权。

## T7 · 真实后端恢复与配置语义（Lead串行，依赖T2/T3/T5可信安装）

复用探针 `products/server/scripts/probe-installed-codex-managed-profile.py`，
给asset选择增加显式受校验输入/新default，不在测试里绕root完整校验。

- [ ] **T7.1** 单场景最多三轮：official A记标记→Go A回忆→official A回忆；
  B官方和C合成API不推理，仅验证同时独立。Key由脚本第2行读取，官方由原生keyring读取。
- [ ] **T7.2** 每轮记canonical/native/channel/owner/generation、实际PID/出口、C4、
  restore/prompt/new调用次数；不输出标记正文/Key/原生原文到公共证据。
- [ ] **T7.3** Go直连或固定上游透明relay证明出站、历史携带、认证匹配bool；
  relay不补header/body、不靠代理修协议。官方出口用独立native账户/route读回，无需抓token。
- [ ] **T7.4** B10/B11/B12全部断言执行完才通过；失败立即停止该场景，不用换随机问题遮掩。
- [ ] **T7.5** C02/C03/C08/C10/C16实际产品观测：能用无推理配置/DB/owner读回验证的不用额外模型。
- [ ] **T7.6** 本场景资源/locator/通道/自有processgroup清理，旧asset/用户账号/既有服务不动。

交付：CP-N4、脱敏JSON证据+raw logs。不把prior Claude/Pi成功抄成新Codex成功。

## T8 · 当前候选实际Desktop（Lead，依赖T3/T4/T7；可提前做无模型UI准备）

- [ ] **T8.1** 使用真实产品manifest/Server，进入实际Electron；禁止UI-preview fixture作验收。
- [ ] **T8.2** 按D16/D17/D18串行覆盖三品牌，复用后端结论但必须实际选择/发送及trace关联。
- [ ] **T8.3** 一个正在输出的场景切model/Profile，再下一发送确认；同Profile A/B overlay和全局更新。
- [ ] **T8.4** 工具只读自有项目、原生approval支持时真实allow/deny；禁止操作真实用户项目/安装软件。
- [ ] **T8.5** 失败/断连/取消/重启场景优先受控注入；无法操控GUI时给用户精确3–5步与预期，
  不写UI已通过，保持L4阻塞并继续打包/回归。
- [ ] **T8.6** Lead自己看最终截图/trace/事件关联，无白屏/正文序乱/无限loading/密钥泄漏。

交付：CP-N5，L4矩阵。screenshots写本spec新证据目录，不覆盖他属`01-empty.png`。

## T9 · 最终回归、deb与一次性交回（Lead，依赖所有非阻塞实现收口）

- [ ] **T9.1** 收回worker写权，审全部diff，修全部已发现P0/P1；冻结单一candidateSHA。
- [ ] **T9.2** 下述门按最终candidate执行，ID+原因比基线，缺席失败，记录各自退出码。
- [ ] **T9.3** build/deb/安装路径检查，输出可安装产物摘要；真实install需用户，不覆盖服务。
- [ ] **T9.4** P13/P14普通安装产品正常启动/最小任务/关闭重启；缺sudo/GUI只能交PARTIAL。
- [ ] **T9.5** F01–F12、原acceptance18条核对；一次性报告全部剩余项，不藏“还有最后一步”。
- [ ] **T9.6** 进度顶部/固定TODO/证据/最终报告一致，所有文件提交显式pathspec，main不动、未push。

交付：CP-N6，COMPLETE_VERIFIED或精确PARTIAL，只有确实达到终点才停止goal。
阻塞不得导致无限空转巡检或扩大到协作系统；可做范围耗尽后有证据交回。

## 实际门禁命令（开工核对存在与聚合，不复制旧计数）

在本树执行。Python仅本树venv；npm重装只用lock，必要时先停止自己测试而非用户服务。

```bash
node --test plugins/harness/packaging/native-profile/*.test.mjs
.cleanup-evidence/product-integration-venv/bin/python -m pytest plugins/harness/tests/configuration_model plugins/harness/tests/test_provider_restoration_service.py plugins/harness/tests/test_pi_provider_registration_service.py products/server -q
.cleanup-evidence/product-integration-venv/bin/python -m pytest plugins/profile plugins/assets/model-provider -q
npm run --workspace plugins/profile/frontend test
npm run --workspace plugins/profile/integrations/chat test
npm run --workspace plugins/chat/frontend test
npm run --workspace plugins/assets/model-provider/desktop test
npm run --workspace plugins/assets/model-provider/chat-contribution test
npm run --workspace plugins/connectors/acp test
npm run --workspace plugins/connectors/ordessa test
npm run typecheck
npm run build
npm test -- --list
npm test
npm run test:packaging
npm run test:agent-shell
npm run test:electron
npm run build:deb
```

最终Python另跑 `packages/pacthold`、`plugins/harness`、`apps/server`、
`tests/acp_orchestration`、`products/server`，各自JUnit/exit/failed-ID差分。
不要跑错path后用tail的exit0冒充pytest成功；日志重定向必须显式保存原exit。
`npm test`若已运行部分门，重复可避免，但要证据逐项映射，不能只报一个总绿。

真实probe CLI先 `--help`/读参数守卫。要求显式 `--allow-model-calls`、Key文件/行、
可信asset、受控root/实例；没有guard先补测试，不临时直接把Key贴进shell。

## 任务状态记录最小模板（由Lead写入进度/证据）

```text
ID / PASS|FAIL|BLOCKED|NOT_RUN|REUSED_EVIDENCE
源码SHA或未提交文件hash；assetDigest；L1..L5；时间
命令/真实exit；断言结果/反例；日志与脱敏摘要位置
prompt/辅助请求数（未知写unknown）；清理完成与剩余资源
依赖阻塞ID；用户动作完整命令；下一独立任务
```

## 阻塞矩阵（必须继续可做的任务）

| 阻塞 | 暂停 | 仍能做 | 交回 |
| --- | --- | --- | --- |
| sudo安装asset | T7、新asset的T8 | T3/T4/T6/S/全部离线门/安装脚本 | 完整命令+pin摘要，不改trust |
| 官方需重新登录 | 官方B10/B11/T8 | API/Pi/Claude/受控恢复/打包 | 原生浏览器登录动作，不读全局auth |
| Go接口不兼容/网络 | Go L3/L4 | 生命周期/中性语义/其他品牌/回归 | 请求阶段/错误码/修法；不透明relay补协议 |
| 无GUI自动化 | T8/P13 | 后端真实/打包/回归 | 用户操作步骤，L4未验不得勾 |
| 真正公有协议或内核新设计 | 受影响依赖闭包 | 所有独立冻结接口任务 | 一句可裁定的选项/代价/建议 |
| 发现源码缺陷 | 当前相关门 | worker或Lead修复、其余线继续 | 不把普通bug变成用户阻塞 |
