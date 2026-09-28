# Q2 任务与原包追踪

本线副本，允许勾选并追加查漏任务。共同 plan 的 owner 分配优先；原表范围外步骤登记依赖/C0 集成，不由本线偷改。原包更晚变更须有明确裁定，不自行缩需求。

- [x] R0：读完整输入，冻结实际 SHA/包/红 ID/环境，盘点复用。（证据：`report.md` R0 节；提交 `354a576b06`/`46846b2c25`/`2c0c8bd209`；逐 ID 红账在 `/home/maoqh/.local/share/qe2-evidence/q2-baseline/`。**范围限定**：此勾指**线级**冻结已完成；两域各自的 `implementation-baseline.md`（prompts T00 / templates T00–T02）由域代理产出，交回前不视为已存在，届时在此处补提交 SHA。）
- [ ] R1：独立工作与接口请求完成；消费必需 checkpoint 并留精确 SHA。（接口请求已成交：`api-requests.md` AR-Q2-01..05；**消费未发生**——五条检查点分支经 `git for-each-ref` 实测均不存在，故本条不勾。）
- [ ] R2：本线全部原包任务有实现/验收/依赖归属，生产假接口为零。
- [ ] R3：检查点/接线清单/许可迁移账/报告齐备，定向及相关全链门通过。
- [ ] R4：Spec Kit analyze/converge 查漏，未完成项如实；发布本线 clean ready commit。

## 原包：prompts

来源：docs/design/prompts/tasks.md，2026-09-28 派发快照。以下保留原条目便于追踪；过程授权与 owner 由共同 plan 更新。

# Tasks and traceability

所有任务尚未执行。按 Spec Kit 的依赖任务划分，不是派工单；未授权创建工作树/会话。[P] 仅表示接口冻结后可独立并行。

## Phase 0 — 依赖与基线

- [ ] T00 冻结平台/Profile/Harness 集成 SHA、公开符号、数据根/授权/文件对话框接缝，记录 implementation-baseline.md；禁止引用工作树未提交实现。
- [ ] T01 固定三品牌 native/adapter 版本，核验 instruction 路线；persona/system-replacement 逐格裁定，保留项目加载机制和 reset 证据计划。
- [ ] T02 保存当前各影响套件的全文/JUnit、失败 ID/原因；核查已有 Prompts ID/代码/数据，没有就明确新增，无臆造迁移。

## Phase 1 — 内容与公共 API（US1/US5）

- [ ] T03 实现 DTO/schema/errors、纯 TS/Python 公共出口，独立导入与边界反例（G01）。
- [ ] T04 SQLite records/revisions、CAS/幂等、clone/archive/restore，单事务 latest/正文；失败注入与并发测试（G02/G03）。
- [ ] T05 UTF-8 导入/导出、容量限制、授权/scope、正文隐私及快照一致性（G04–G07）。
- [ ] T06 注册 Server 方法与公共服务，不导入 host internals；无 Profile/Harness 的裸业务管理测试（G08）。

## Phase 2 — 贡献与适配（US2/US4）

- [ ] T07 [P] 三品牌 Harness adapter 的 assess/compile/verify、claims、组合/reset、隐式 include 拒绝和版本矩阵（G09–G12）；依赖 T01/T03/T05。
- [ ] T08 [P] Profile facet/引用校验/专用内容授权、scope dispose 和覆盖联动（G13/G14）；依赖 T03/T05/T06。
- [ ] T09 [P] Settings 管理页、编辑/预览/历史/导入导出/冲突保稿，按复用单用平台基础件（G15/G16）；依赖 T03/T06。
- [ ] T10 Profile editor，多选排序、单选、高级替换、明确两步保存与异步代次保护（G17）；依赖 T08/T09。

## Phase 3 — 生产应用与交付（US3）

- [ ] T11 接既有 Profile→Harness→ACP 提交路径；选择不应用、下次输入冻结、confirmed 才发消息，失败不清覆盖（G18）。
- [ ] T12 三品牌 instruction 启用/更新/排序/移除、双会话隔离、重启恢复与实际装载受控证据（G19）；不能只有 fake service。
- [ ] T13 产品 manifest/锁与真实构建，前端几何/键盘/空/错误/卸载验证（G20）。
- [ ] T14 wheel 隔离安装、干净检出与完整受影响套件逐 ID/原因差分；权限/泄漏扫描（G21/G22）。
- [ ] T15 汇总实施报告、来源许可、能力矩阵、未测/阻塞、数据回退与原始证据位置；所有必需门通过后报 REVIEW_READY，未获授权不合并/push。

## 需求映射

| 需求 | 任务 | 验收 |
| --- | --- | --- |
| FR01/FR10/FR11/FR13 | T01/T07 | G09–G12 |
| FR02/FR04/FR06 | T04/T05 | G02/G03/G07 |
| FR03/FR05 | T05/T08/T10 | G06/G13/G17 |
| FR07/FR08 | T03/T06/T08/T09 | G01/G08/G14/G15 |
| FR09/FR14/FR15 | T05/T07/T09 | G04/G05/G10/G16 |
| FR12/FR16 | T11/T12 | G18/G19 |
| FR17 | T13/T14/T15 | G20–G22 |

小实现错误自行修复并复跑；改变原生语义、扩大 host 范围、修改用户数据或真实模型调用属于新的授权边界，不能为了无人值守绕过。


## 原包：command-templates

来源：docs/design/command-templates/tasks.md，2026-09-28 派发快照。以下保留原条目便于追踪；过程授权与 owner 由共同 plan 更新。

# Tasks（未执行）

每项交付真实文件、提交 SHA、正/反测试、命令/退出码及证据；`[P]` 只表冻结依赖后可并行，不代表已派出。未完成必需门不得报整包完成。

## Phase 0：冻结

- [ ] **T00** 冻结产品/Server/Profile/Harness/Chat 的已验收集成 SHA、公开符号、产品启用点、工具链和既有 suite 红 ID/原因。尤其核实 `addInputSource` 是否真的发布及“参数表单→预览→草稿插入”能否用公开动作表达；缺口交 Chat 所有者做最小契约/反例，不造平行入口。对应 G00/G08。
- [ ] **T01** 固定 Pi/Codex/Claude native+adapter 版本、原生命令目录/优先级/重载和当前 ACP 消息角色；填 supported/unsupported/unknown 矩阵。对应 G15/G16。
- [ ] **T02** 清点现有 compat asset kind、模板/命令消费者及用户数据 ID；锁定迁移/保留/删除账，基线只读。对应 G01/G21。

## Phase 1：领域核心

- [ ] **T03** 新建独立领域包、DTO/错误/schema 与隔离装包。拒绝无效 id、过大/坏编码、越权读取；无 Profile/Chat/Harness 仍能 CRUD。对应 G01/G02/G20。
- [ ] **T04** 修订、摘要、审批、归档、CAS/幂等；发布新版不改绑定。对应 G02–G04。
- [ ] **T05** 自研封闭参数 parser/renderer 与 golden corpus；转义、非递归、类型、边界和原文 hash。对应 G05–G07。
- [ ] **T06** 全局/品牌/项目/项目品牌确定性分配、授权和来源解释；同名冲突与强制策略。对应 G03/G08/G12。
- [ ] **T07** 只读原生文件导入预览/提交，无法无损的动态 include/权限字段拒绝，不碰原件。对应 G21。

## Phase 2：配置与交互

- [ ] **T08 [P]** Profile facet 三态固定版引用、专用内容权限及可选编辑贡献；退出 Profile 不停内容库。对应 G12–G14。
- [ ] **T09 [P]** 本域 Settings 管理/项目分配 UI，复用经发布的平台基础控件与 Workbench 设置贡献；无项目/失败/冲突/窄窗反例。对应 G19。
- [ ] **T10** Chat scoped input source：`/`/`+` 查询、参数填写、预览、光标/目标守卫、只插入不发送；输入法/键盘正反例。依赖 T00/T05/T06。对应 G08–G11。
- [ ] **T11** 现有 ACP submit 的单一发送 owner 贯通，Pi/Codex/Claude 的受控对端见到**最终草稿字节且角色为 user**；不创建第二通道/执行。对应 G10/G17。

## Phase 3：可选原生适配与交付

- [ ] **T12 [P]** Pi 适配评估与有证据时投影；固定 pin 的语法/命名/重载/撤销等价门，不通过则标 unsupported。对应 G15–G18。
- [ ] **T13 [P]** Claude/Codex 适配评估：与 Skills 双投影和 deprecated custom prompts 的负面门必测；未证等价则不实现 native 写入。对应 G15–G18。
- [ ] **T14** 产品启用/构建锁由构建生成，删除重复注册/shim；三品牌受控真实 Ordessa 链、干净装包和 UI smoke。对应 G17/G20/G22。
- [ ] **T15** 基于 T00 账本做受影响套件逐失败 ID/同因 diff、数据备份恢复、边界扫描；独立审阅后报告实施/未测矩阵。对应 G20–G23。

## FR→任务→验收矩阵

| FR | Tasks | Gates |
| --- | --- | --- |
| 01/04/11 | T02–T04/T06/T08 | G01–G04/G12–G14/G21 |
| 02/05/06/09 | T05/T10/T11 | G05–G07/G09–G11/G17 |
| 03/07/08 | T06/T08/T10 | G03/G08/G12–G14 |
| 10 | T01/T12–T13 | G15–G18 |
| 12 | T03/T10/T14–T15 | G11/G20/G22–G23 |

最后更新 verification 中的实际证据而非仅打勾；没有已授权真实模型测试时，L4 留未测、不阻碍本批受控 L3 完成。

## EXT — 八家品牌面扩展（2026-09-28 用户裁定，详见 [addendum-eight-brands.md](addendum-eight-brands.md)）

- [ ] EXT-00 R0 实测补账：逐任务盘点分支实现与账面差异（以实现+测试实跑计数为准），补勾/回退并附证据 SHA
- [ ] EXT-01 四家（OpenCode/dsh/Qwen/Kilo）三语义判定表：instruction/persona/systemReplacement × 可用/不支持/未知，逐格证据+反例，并入 `docs/design/prompts/harness-adapters.md` 矩阵
- [ ] EXT-02 四家 adapter assess/compile/verify 实现；G09–G12 conformance 门扩到八家
- [ ] EXT-03 dsh 原生 persona prefix/suffix 对接裁定与独立反例（组合顺序、移除恢复 baseline）
- [ ] EXT-04 G19 真实装载受控证据扩到八家（缺格不报 supported）
- [ ] EXT-05 八家 × 三语义能力矩阵进最终报告
