# Tasks：Chat v2 实施与验收

产品语义以 spec.md + input-spec.md 定稿；以下旧 D/I 项继续追踪，新增 v2 阶段为完整范围。按 plan.md S0–S5 顺序，不把文档已写当作类型/运行验证完成。

## v2 阶段任务

- [ ] CHAT-V01 / S0 绑定正式平台 SHA，实跑基线；source→destination、测试 ID、持久标识与服务所有者表完整。
- [ ] CHAT-V02 / S0 冻结编译级 input source、Composer props、文件引用和提交结果类型；正反例证明无 any 绕过。范围外服务修改一次性列明并取得派发授权。
- [ ] CHAT-V03 / S1 项目/命令/能力/prepare/submit 服务 proof；文本兼容，受控附件内容实际到达，目标化及接受语义不靠 UI 推断。
- [ ] CHAT-V04 / S2 完成旧 I01–I03 的 ZCode 输出组件复用、安全与滚动状态反例。
- [ ] CHAT-V05 / S3 全局项目弹窗、添加项目、项目 + 直接草稿；取消零通道/首次提交重验证；固定输入与审批操作区。
- [ ] CHAT-V06 / S4 共用 plus/slash 面板、搜索/分组/键盘/焦点；注册来源、缺席/错误/卸载/陈旧动作测试。
- [ ] CHAT-V07 / S4 附件选择/拖放/粘贴/预览/移除/重试及所有权；能力限制/远程路径/发送快照/未知结果反例。
- [ ] CHAT-V08 / S5 接真实服务实现与受控协议对端、最小产品装配；关闭旧 UI 注册链但保留 ID，不把会话模型搬入 UI。
- [ ] CHAT-V09 / S5 checklist.md 全矩阵；真实浏览器截图、受控 hash 校验、根与包回归/构建/适用 Electron 门。
- [ ] CHAT-V10 / S5 报告来源、许可、逐项证据/已知红/未验证；独立审阅修复范围内问题后提交待审，不自动合并。

以下是本版工作顺序，不是本次已授权代码修改。用户审核后再给完整执行提示词。

## 设计前置（未完成前不能宣称无人值守就绪）

- [ ] CHAT-D01 绑定 C7/C8 合格集成 SHA，盘点真实会话 API、已有 Chat 分支与根目录实现；列 source→destination/测试/extension ID 保留表。
- [ ] CHAT-D02 冻结四个拟公开组件的 props、scope与key；确认会话上下文/贡献位置的最小权限；类型反例先行。
- [ ] CHAT-D03 冻结现有服务→显示 DTO 字段表；未能表示的状态列缺口，不靠 UI 猜测补齐。
- [ ] CHAT-D04 确认用户接受本版与 ZCode 的明确差异：不移植排队摘要动画/工作流/代码评论/Mermaid；保留喜欢的主要外观与交互。

设计增补：D02 的语义草案已落 `contracts.md`；D03 的现场映射与缺口已落 `service-adaptation.md`。未勾选表示尚未完成集成基线绑定、可编译类型与实施前检查，不表示仍需从零设计。

## 实施序列（设计冻结后）

- [ ] CHAT-I01 按固定 SHA 获取源码，生成逐文件 provenance/license；先做 Markdown/代码/样式隔离和包兼容 proof。
- [ ] CHAT-I02 US1：正文/思考/代码组件与反例；独立 fixture，不接真实服务。
- [ ] CHAT-I03 US2：ToolFrame/ToolSummaryRow/CommandOutput 移植与语义适配；优先紧凑行而非大卡片；同名/键盘/滚动/清理反例。
- [ ] CHAT-I04 US3：输入/草稿/固定布局，保留现有接受/拒绝/未知、停止/审批门禁；不引入第二套会话存储。
- [ ] CHAT-I05 scope贡献与组件注册，受控其他插件注册工具栏按钮/新内容块；卸载仅撤 UI，数据与运行保留。
- [ ] CHAT-I06 实际服务适配与旧 UI 切换；保留原测试 ID/断言映射；独立构建验证key/React单例。
- [ ] CHAT-I07 浏览器深浅/宽度/键盘/流式/网络断言；现有业务回归；逐模块原来源→目标→证据报告，待审不自动合并。

## 贡献与适配专项验收（并入 I05/I06，不另开架构）

- X01：受控字段插件注册 toolbar/独立设置；无 Chat 时独立设置可用，卸载 Chat 不丢字段后台服务。若宿主 optional 连带卸载，验证独立 glue 入口方案。
- X02：贡献撤回只清本条位置；C7 provider 可继续被另一消费者使用；贡献重复 ID/内容 kind 冲突拒绝，加载顺序不改变结果。
- X03：会话 A 的延迟点击/请求结果遇到切换 B：不调用 B 服务、不更新 B 控件；同一provider未卸载仍需位置 revision 守卫。
- X04：新 kind 显示专用组件；缺 provider/校验失败保留可读 fallback；projection/render 错误仅影响本条且可见。
- X05：send 中继续编辑或切会话，返回只处理原身份/版本；审批 resolved 不展示成工具成功；断连/停止不提前造终态。
- X06：缺 commands/attachments/harnessId/diff 数据的真实服务 fixture，不出现伪能力；不通过 toolName 猜数据来使测试通过。

正文/思考与工具两个模块在共享类型/rendering冻结后可并行；共享 entry/API/lock/产品清单必须单一写者。前端平台当前工作树不为本批提前修改。Chat 执行者不得写 Server/Pacthold/Harness；v2 S1 如需这些包，由 S0 明确接缝/所有者后单独授权，不向 UI 执行者隐式扩权。
