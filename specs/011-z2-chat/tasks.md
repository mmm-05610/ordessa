# Z2 任务与原包追踪

本线副本，允许勾选并追加查漏任务。共同 plan 的 owner 分配优先；原表范围外步骤登记依赖/C0 集成，不由本线偷改。原包更晚变更须有明确裁定，不自行缩需求。

- [x] R0：读完整输入，冻结实际 SHA/包/红 ID/环境，盘点复用。（`specs/011-z2-chat/baseline.md`，基线门实跑记录在内；commit 98be5571cb）
- [x] R1：独立工作与接口请求完成；消费必需 checkpoint 并留精确 SHA。（chat-api 三检查点：v1 `codex/011-chat-api-ready` @ 54ad26c15d / 实现 a3ec20c046；r2 `...-r2` @ 31fb2db46d；r3 `...-r3` @ 3d8c3fa410 / 实现 47459b0acb。**foundation 已消费**：publication 8844c475bc（实现 8229e20824，祖先已核）merge 0a05235d0f，复跑全绿。harness-api 未发布，R-Z2-1/2/3 接线待其落地。）
- [ ] R2：本线全部原包任务有实现/验收/依赖归属，生产假接口为零。（S2–S4 UI/组件/输入/审批/弹窗已实现并有测试；S1 真实附件/命令/三态接线依赖 C0（api-requests R-Z2-1/2/3），S5 真实浏览器矩阵与受控 hash 往返待接线后执行——见下逐条。）
- [x] R3：检查点/接线清单/许可迁移账/报告齐备，定向及相关全链门通过。（integration-request.md §1–§6、upstream-manifest.json、THIRD-PARTY-NOTICES.md、licenses/、report.md、analysis.md；chat 两包门 + 根 typecheck/聚合/构建绿。浏览器矩阵等装配依赖项在 report §5 如实未验证。）
- [x] R4：Spec Kit analyze/converge 查漏，未完成项如实；发布本线 clean ready commit。（analysis.md 覆盖矩阵 + 5 条查漏发现；ready 分支指向最终提交。独立审阅因派单配额受限由本会话自审执行并登记 report §6，建议 C0 复核。）

## 检查点修订账（协议：修订发布带 -r2 并注明兼容）

- chat-api v1 发布后、无任何消费者消费前，`ChatInputEntryAction` 的 prepare/execute 输入类型由示意 `ChatScopedAction<ref/void>` 修订为显式 `(location) => Promise<ChatPrepareResult/ChatActionResult>`（33abf4efbf）。兼容性：id/major/Token 不变；仅动作成员签名收窄，无既有外部消费者。R4 时以 chat-api-r2 记录或并入 ready 报告，不再改 v1 历史。

## 原包：chat-zcode-reuse

来源：docs/design/chat-zcode-reuse/tasks.md，2026-09-28 派发快照。以下保留原条目便于追踪；过程授权与 owner 由共同 plan 更新。

# Tasks：Chat v2 实施与验收

产品语义以 spec.md + input-spec.md 定稿；以下旧 D/I 项继续追踪，新增 v2 阶段为完整范围。按 plan.md S0–S5 顺序，不把文档已写当作类型/运行验证完成。

## v2 阶段任务

- [x] CHAT-V01 / S0 绑定正式平台 SHA，实跑基线；source→destination、测试 ID、持久标识与服务所有者表完整。（基线 96fef2db47 实跑、迁移表 baseline.md；正式平台 SHA = foundation 8844c475bc 已消费，agent-contracts 迁移后别名已同步）
- [ ] CHAT-V02 / S0 冻结编译级 input source、Composer props、文件引用和提交结果类型；正反例证明无 any 绕过。范围外服务修改一次性列明并取得派发授权。（chat-api a3ec20c046 + contract.typecheck.ts + api-requests 一次性列齐）
- [ ] CHAT-V03 / S1 项目/命令/能力/prepare/submit 服务 proof；文本兼容，受控附件内容实际到达，目标化及接受语义不靠 UI 推断。（项目门/文本发送已对真实 facade 证明；**命令目录/附件 prepare/三态 submit 等真实服务接缝归 C0**，落地后本线接线验证）
- [x] CHAT-V04 / S2 完成旧 I01–I03 的 ZCode 输出组件复用、安全与滚动状态反例。（display 11 例 + upstream-manifest；markdown/reasoning/tool/scroll 全部带反例；commit 33abf4efbf）
- [x] CHAT-V05 / S3 全局项目弹窗、添加项目、项目 + 直接草稿；取消零通道/首次提交重验证；固定输入与审批操作区。（approval-project 10 例 + composer-flow 草稿门 2 例；弹窗宿主为 Workbench composition/overlay）
- [x] CHAT-V06 / S4 共用 plus/slash 面板、搜索/分组/键盘/焦点；注册来源、缺席/错误/卸载/陈旧动作测试。（panel-draft 7 例 + chat-api 15 例覆盖注册/缺席/错误/陈旧插入拒绝）
- [x] CHAT-V07 / S4 附件选择/拖放/粘贴/预览/移除/重试及所有权；能力限制/远程路径/发送快照/未知结果反例。（panel-draft + composer-flow 覆盖生命周期/所有权/未知结果；**真实传输内容往返依赖 R-Z2-2**，当前以诚实禁用呈现，fixture 层已证）
- [ ] CHAT-V08 / S5 接真实服务实现与受控协议对端、最小产品装配；关闭旧 UI 注册链但保留 ID，不把会话模型搬入 UI。（**装配与旧链关闭归 C0 集成**，清单在 integration-request.md；本线入口/服务已按启用即用就绪）
- [ ] CHAT-V09 / S5 checklist.md 全矩阵；真实浏览器截图、受控 hash 校验、根与包回归/构建/适用 Electron 门。（包回归已过；**浏览器矩阵/Electron/受控 hash 依赖 C0 装配后执行**）
- [ ] CHAT-V10 / S5 报告来源、许可、逐项证据/已知红/未验证；独立审阅修复范围内问题后提交待审，不自动合并。（R4 执行）

以下是本版工作顺序，不是本次已授权代码修改。用户审核后再给完整执行提示词。

## 设计前置（未完成前不能宣称无人值守就绪）

- [x] CHAT-D01 绑定 C7/C8 合格集成 SHA，盘点真实会话 API、已有 Chat 分支与根目录实现；列 source→destination/测试/extension ID 保留表。（C7/C8 集成 SHA 待 C0；其余已在 baseline.md 完成——runtime 形状对齐决定与限制如实登记）
- [x] CHAT-D02 冻结四个拟公开组件的 props、scope与key；确认会话上下文/贡献位置的最小权限；类型反例先行。（chat-api 四 key + 六槽位 + typecheck 反例）
- [x] CHAT-D03 冻结现有服务→显示 DTO 字段表；未能表示的状态列缺口，不靠 UI 猜测补齐。（adapters/agent.ts 逐字段 + service-adaptation 缺口表引用；缺口登记 api-requests R-Z2-5）
- [x] CHAT-D04 确认用户接受本版与 ZCode 的明确差异：不移植排队摘要动画/工作流/代码评论/Mermaid；保留喜欢的主要外观与交互。（research-plan 裁决照办，未移植项在 upstream-manifest dropped 字段逐文件登记）

设计增补：D02 的语义草案已落 `contracts.md`；D03 的现场映射与缺口已落 `service-adaptation.md`。未勾选表示尚未完成集成基线绑定、可编译类型与实施前检查，不表示仍需从零设计。

## 实施序列（设计冻结后）

- [x] CHAT-I01 按固定 SHA 获取源码，生成逐文件 provenance/license；先做 Markdown/代码/样式隔离和包兼容 proof。（ZCode 29628c9a 浅取核对，upstream-manifest 逐文件 git-hash + kept/dropped/adapted；streamdown/shiki 包兼容在编译+测试中验证）
- [x] CHAT-I02 US1：正文/思考/代码组件与反例；独立 fixture，不接真实服务。
- [x] CHAT-I03 US2：ToolFrame/ToolSummaryRow/CommandOutput 移植与语义适配；优先紧凑行而非大卡片；同名/键盘/滚动/清理反例。
- [x] CHAT-I04 US3：输入/草稿/固定布局，保留现有接受/拒绝/未知、停止/审批门禁；不引入第二套会话存储。
- [x] CHAT-I05 scope贡献与组件注册，受控其他插件注册工具栏按钮/新内容块；卸载仅撤 UI，数据与运行保留。（chat-api 注册表 + entry 自有贡献样例 + provider 缺席隐藏；受控第三方注册以 chat-api 测试 fixture 证明）
- [x] CHAT-I06 实际服务适配与旧 UI 切换；保留原测试 ID/断言映射；独立构建验证key/React单例。（适配完成；**旧 UI 切换归 C0**；断言映射在 integration-request §4）
- [ ] CHAT-I07 浏览器深浅/宽度/键盘/流式/网络断言；现有业务回归；逐模块原来源→目标→证据报告，待审不自动合并。（**依赖装配**；unit 层深浅/键盘/流式断言已有，浏览器矩阵待 C0 集成树）

## 贡献与适配专项验收（并入 I05/I06，不另开架构）

- [x] X01：受控字段插件注册 toolbar/独立设置；无 Chat 时独立设置可用，卸载 Chat 不丢字段后台服务。若宿主 optional 连带卸载，验证独立 glue 入口方案。（chat-api scope 撤回语义 + 贡献样例；Z1/Z3 消费由其自身 API 完成，Chat 不在时其插件不受影响——设计上 requires ChatContributionsToken 为可选注入，最终以集成宿主校验，登记 api-requests 备注）
- [x] X02：贡献撤回只清本条位置；C7 provider 可继续被另一消费者使用；贡献重复 ID/内容 kind 冲突拒绝，加载顺序不改变结果。（chat-api 测试 1/2/3 例）
- [x] X03：会话 A 的延迟点击/请求结果遇到切换 B：不调用 B 服务、不更新 B 控件；同一provider未卸载仍需位置 revision 守卫。（composer-flow X05 例 + contextRevision 捕获）
- [x] X04：新 kind 显示专用组件；缺 provider/校验失败保留可读 fallback；projection/render 错误仅影响本条且可见。（chat-api decode 失败 fallback 语义 + renderer 重复拒绝；render 错误隔离由 provider 表「缺席隐藏」+ 单条贡献粒度保证）
- [x] X05：send 中继续编辑或切会话，返回只处理原身份/版本；审批 resolved 不展示成工具成功；断连/停止不提前造终态。（composer-flow 3 例 + 审批 resolved 例 + 停止请求态文案）
- [x] X06：缺 commands/attachments/harnessId/diff 数据的真实服务 fixture，不出现伪能力；不通过 toolName 猜数据来使测试通过。（facade-fixture 仅含真实字段；工具 generic 渲染例；能力缺席以 reason 呈现例）

正文/思考与工具两个模块在共享类型/rendering冻结后可并行；共享 entry/API/lock/产品清单必须单一写者。前端平台当前工作树不为本批提前修改。Chat 执行者不得写 Server/Pacthold/Harness；v2 S1 如需这些包，由 S0 明确接缝/所有者后单独授权，不向 UI 执行者隐式扩权。

## 本线执行记录（追加）

- 2026-09-28：子代理派单连续遭遇运行时配额限制（exceed quota limit），按「普通阻塞自行解决」改为本会话直接实现并在报告记录偏差；审阅派单在 R4 前重试。
- chat-api v1 契约在发布后有一次动作签名收窄（见「检查点修订账」）。
- 新增依赖仅落在 plugins/chat/frontend（根 lock 增量登记 integration-request §2）；apps/desktop/tsconfig.json 增加一行契约别名（integration-request §3，请 C0 复核）。
