# PX-report · prompts 八家 EXT(品牌收窄执行)016 夜批交付

状态:**REVIEW_READY(zcode 代打)**。分支 `codex/plugin-prompts`,工作树
`worktrees/overnight-2/son-px-prompts`,写入面 `plugins/assets/prompts/**` +
`specs/016-overnight-batch/{reports,api-requests.md}`。执行记录:qoder 按环境级
裁定不可用(两次封装运行只读受阻 + 降级条款裸调探针证实模型白名单名不可用且
账户额度耗尽,旁证 overnight-1/3 同款失败;证据链见父会话
`worktrees/overnight-2/reports/qoder-unavailable-record.md`),本包按 spec.md
红线 5 由父会话代打,标注**「qoder 失败、zcode 代打」**。git 纪律同 EXT:父会话
只读 git,改动全部留工作树不提交,待用户验收。

## PX-0 / EXT-00 · R0 实测盘点

环境动作登记:为运行本包测试,`ordessa-prompts`(son-px 树)以 editable 方式装入
共享验证 venv(baseline.md 环境本就要求该补录;主仓此前无 prompts 安装,无覆盖)。

四件套实测(2026-09-29 02:0x):

| 套件 | 计数 | 说明 |
| --- | --- | --- |
| pytest(plugins/assets/prompts) | **187 collected / 187 passed / 0 failed** | 原 149 条 + 本包净增 38 条(新测试函数 35:brand_table 9 + conformance 19 + G01 增 2 + citations 5;其余 3 条为 G01 文件级参数化对 3 个新子包文件的扩展) |
| vitest ×2 | **不在本写入面** | prompts 树内无 vitest 工程;contracts/*.ts 的类型镜像由 pytest G01 跨语言契约测试强制,不另有 vitest |
| tsc | **不在本写入面** | contracts/ 无 tsconfig(纯类型导出);类型检查归 desktop 构建线 |

账实对齐:树内账 43 项未勾(addendum 时点 36 未勾/1 勾;其后追加 EXT-00..05 六项,
现共 43)。逐项处置见下表。**账本文件本身不在本包写入面**(仅 prompts/** 与
reports/),故补勾以本表为准落账,账本勾选留该账所有者执行。

## PX-7 · 43 项逐项处置(三档口径)

**R 行(线级过程门)**

| 项 | 处置 | 依据 |
| --- | --- | --- |
| R0 | ✅ 本报告即 R0 产物(实测+对账) | 上节 |
| R1/R2/R3/R4 | ⛔ 卡点:线级过程门(跨域集成/发布线),超出本包写入面与授权 | spec.md 写入面红线 |

**prompts T 行(内容库已实现;适配器本包交付;前端/集成线外)**

| 项 | 处置 | 证据/卡点 |
| --- | --- | --- |
| T00 冻结基线 | ⛔ 卡点:implementation-baseline.md 不在树内(q2 线产物);pin 事实已由 packaging 锁在案(packaging/{pi,codex,claude}/package*.json) | 部分事实可用 |
| T01 三品牌版本+instruction 路线 | ✅(事实面) | pi 0.84.2/0.5.0(packaging/pi/package-lock.json:45-46)、codex 0.147.0/1.1.14(codex/production.py:88+packaging/codex/package.json:9)、claude 0.81.2(production.py:67)/CLI 2.1.274 注记级(toml:111);路线判定=capabilities.py 三行 instruction 格 |
| T02 套件全文/失败 ID 冻结 | ⛔ 卡点:无该证据文件在树 | — |
| T03 DTO/纯出口(G01) | ✅ | tests/test_g01_api_purity.py(181 passed 之一) |
| T04 revisions/CAS(G02/G03) | ✅ | test_g02_revisions_cas.py、test_g03_clone_archive_lifecycle.py |
| T05 导入导出/容量/授权/隐私(G04–G07) | ✅ | test_g04..g07 四件 |
| T06 Server 方法注册(G08) | ✅ | test_g08_plugin_surface.py |
| T07 三品牌 adapter assess/compile/verify、claims、组合/reset、隐式 include 拒绝、版本矩阵(G09–G12) | ✅(就绪+待通) | 本包 harness_adapters/(三 adapter+19 项 conformance 测试函数);**compile=类型化拒绝(AR-6)**:registry 无 instruction target 声明(schema.py:64 无字段、toml 零条),隐式 include 拒绝=synthesis 枚举+payload schema 固定,reset 格=unsupported(HM §5 baseline 不可隔离),claims=空(无 target 可 claim) |
| T08 Profile facet(G13/G14) | ⛔ 卡点:未实现(plugin.py 仅消费 profile.prompts_authorization 端口;无 facet 注册),归 Profile 接线项 | — |
| T09/T10 Settings UI/Profile editor(G15–G17) | ⛔ 卡点:前端,超出写入面 | — |
| T11 提交路径冻结语义(G18) | ⛔ 卡点:Harness 提交链集成 | — |
| T12 三品牌真实装载(G19) | ⛔ 卡点:AR-6 通路缺失(同 T07 待通);缺格不报 supported 已由能力表强制 | api-requests.md AR-6 |
| T13/T14 产品装配/隔离 wheel(G20–G22) | ⛔ 卡点:C0/发布线 | — |
| T15 汇总报告 REVIEW_READY | ✅(本包范围)= 本报告 | — |

**command-templates T00–T15(16 项)**:⛔ 全部卡点——该域不在本包写入面
(独立分支 codex/plugin-command-templates、独立域包),016 夜批 PX 包范围仅
prompts;逐项留该分支所有者。

**EXT 行(品牌收窄后)**

| 项 | 处置 | 说明 |
| --- | --- | --- |
| EXT-00 R0 实测补账 | ✅ = 本报告 PX-0/PX-7 节 | — |
| EXT-01 四家三语义判定表 | ✅(三家)+ ⛔ 四家转阶段二 | 三家判定=capabilities.py(逐格证据+反例);并入 docs/design/prompts/harness-adapters.md 矩阵属 docs/ 越界,登记为接入请求(见下);四家(OpenCode/dsh/Kilo 三家判定已予 unknown 预置格+反例,Hermes 同)的**可派单方案包**归父会话阶段二 |
| EXT-02 四家 adapter;G09–G12 扩八家 | ✅(三家 adapter)+ ⛔ 四家转阶段二 | 三品牌 adapter 交付(compile 拒绝式);八家扩展转阶段二 |
| EXT-03 dsh persona 对接 | ⛔ 转阶段二 | dsh persona prefix/suffix 判定格+组合顺序/移除恢复反例已预置于 capabilities.py,供阶段二方案包直接取用 |
| EXT-04 G19 八家 | ⛔ 卡点(AR-6)+ 四家阶段二 | 缺格不报 supported 已强制 |
| EXT-05 八家×三语义矩阵进报告 | ✅ | = capabilities.py 全表(三家逐格+四家 unknown 预置+qwen 除名行),本报告引用 |

## 品牌收窄执行记录(用户裁定 2026-09-28)

- **实施**:pi/codex/claude 三品牌 adapter(_descriptor/assess/verify 全量+
  compile 诚实拒绝)。
- **转阶段二**:hermes/opencode/dsh/kilo 四品牌全部格子(判定预置 unknown+
  反例,不实施)。
- **qwen 除名**:QWEN.md / context.fileName / import / includeDirectories /
  rules-file 行全部跳过,QWEN_REMOVAL_NOTE 逐面登记;harness 侧摘除归 PE2-8。
  代码/测试/报告中无任何 qwen 能力行。

## 复用与自建清单(红线 7)

复用:published `ordessa_harness_api` 全套词汇、`harness.configuration-adapters`
注册通路(AR-2,与 skills/extensions 同点)、G01–G08 既有内容库与其 149 项测试、
packaging pin 事实、skills/extensions 的能力表+conformance 形制、G01 的
边界扫描机制(白名单增两项=新子包与其 contribution 模块,无断言删除,敌例仍在
并有双向证明测试)。
自建:三品牌 prompts adapter 本体、三语义×八品牌能力表、固定合成顺序的 payload
schema(为投影落地日预留)。自建占比约四成;凡有发布词汇与既有事实处一律复用。

## 接入请求(写入面外)

1. capabilities.py 三家判定格并入 `docs/design/prompts/harness-adapters.md`
   矩阵(EXT-01 要求的 docs/ 落点不在本包写入面)——留 docs 所有者或授权后执行。
2. AR-6(已入 api-requests.md):harness 侧 instruction target 声明 + 路线核读。

## 测试证据(实跑)

`python -m pytest plugins/assets/prompts -q` → **187 collected / 187 passed /
0 failed**(2026-09-29 03:3x 复核;原 149 条 + 净增 38 条:brand_table 9 函数 +
conformance 19 函数 + G01 增 2 函数 + citations 5 函数 + 文件级参数化对
3 个新子包文件的扩展)。
`git -C <son> status --short` 零越界(仅 prompts/**、api-requests.md、reports/)。

## 审阅

run-review.sh 返回「空 diff」(代打未提交,父会话 git 只读);按降级条款同口径裸调
pi+mimo-v2.6-pro 审阅工作树伪 diff。**共 6 轮**:首轮(HM 路径 replace 拼错/白名单
账实/反例断言缺位)→修复;二轮(测试计数口径/边界扫描覆盖证明/死代码)→修复;三轮
(报告两节计数矛盾/测试死 context/证据引用不可核→新增 citations spot-check 使其
可证伪)→修复;四轮(报告计数失实 182→186 收口)→修复;五轮(报告"22 项"残留/
zero-consumers 与 hooks_target 主张入测试实开核对/compile 异常面 fail-closed)→
修复;六轮(恒真子集断言改硬编码期望/注释实名对齐/citations 注释与实现对齐)→修复。
**终态:六轮意见全部落实,187 passed/0 failed;审阅方六轮一致确认「无 fake green、
写入面无越界」;末轮残留为弱断言/注释口径三项,已修,未再起轮。**轮次原文:本目录
PX-review-round1..6-20260929.md。
