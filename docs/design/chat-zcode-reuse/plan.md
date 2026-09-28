# Chat v2 实施计划

## 实施状态与边界

本包是可审阅的完整需求/实现路线，不是“所有前置代码已具备”。当前平台开发 SHA 观察值 `3411401795`；它仅为观察记录，不是批准的实施基线。另有 Workbench 侧栏独立树，本批不修改它。

代码所有权：Chat UI/菜单/草稿展示归目标 `plugins/chat`；现存 conversation/sessions 先做映射，保留 extension/view ID；会话与传输服务保持原所有者。附件贯通不承诺仅改 Chat。产品 manifest、包依赖/lock 仅由集成阶段单一写者做最小接线，禁止手改生成 lock。

## 分阶段执行

1. **S0 基线与契约 proof**：读取已完成的平台检查点，实跑基线，核实 C7/C8 API；列旧文件/测试→目标表和已有会话服务。对 input-contracts 的每行记录已提供/需补/所有者/测试。输出编译级类型及最小调用 proof。范围外服务缺口一次性列齐再派发，不反复逐个追补。
2. **S1 服务接缝**：在被明确分配的服务包补命令目录/附件能力与发送内容适配，使用受控对端，保留文本发送兼容，禁止 reviving 旧链。验证项目拒绝零通道及目标身份隔离。不得让 Chat 直接传私有协议。若 S1 未授权，S2–S4 独立 UI 仍可做，但整批报告 PARTIAL。
3. **S2 输出展示**：按 research-plan 移植正文、思考、紧凑工具与输出跟随，不推翻既有 run/审批状态服务。
4. **S3 创建和固定输入区**：全局选择项目弹窗/添加项目子流程；项目 + 直接草稿；首次提交才开通道；底部固定 composer、待处理审批区与历史记录分离。
5. **S4 输入扩展与附件**：实现共享 plus/slash 面板、scoped sources、附件草稿生命周期与 capability 门禁；UI 控制夹具先行，随后接 S1，不能 mock 后宣称产品贯通。
6. **S5 集成和验收**：明确选择新 UI 的产品装配、来源许可、原测试迁移与回归、真实浏览器矩阵、受控附件往返与完整报告。合并需另批。

可并行：S1 与冻结 DTO 后 S2 的显示组件；S3/S4 修改 composer/store，串行同写者。API、entry、产品配置、lock 单写者。主代理派实现子代理、亲审 diff/复跑；此文不授权新树或新会话，也不覆盖已有任务。

## 新增 ZCode 复用清单

固定源 SHA 沿 research-plan。路径相对 packages/ui/src。逐文件读取完整实现与其必要依赖后再提取，记录 source hash/license/符号→目标，不能仅凭下面文件名直接移植。

| 模块 | 来源 | 提取与适配 |
| --- | --- | --- |
| / 触发与键盘 | SlashCommandPlugin.tsx | 提取 token/query/选中/关闭与 portal 交互；删 Skills/Subagents/Provider 直接依赖，用 Chat input sources。它依赖 Lexical：只移植可分离逻辑到现有受控输入，不为一个菜单引入第二套编辑器 |
| 建议分组 | slashCommandPanelSections.tsx、mentions/components/MentionPanel.tsx | 分组、loading/error、名称/说明布局；通用组由来源声明，不硬编码 ZCode 业务 |
| 过滤/替换 | lib/promptInputTriggers.js 对应源文件、mentions/activePromptInputToken 对应源文件 | 搜索/活动 token/陈旧选择处理；保留 IME、光标移动反例，按真实源扩展名核对 |
| 附件输入生命周期 | v4/composer/useComposerAttachments.ts | 选择/粘贴/拖放、准备、移交后清理的逻辑；剥离 whiteboard、ZCode store/runtime generation。不可直接复制全 hook |
| 附件卡片/预览 | components/ai-elements/attachments.tsx、ChatMediaAttachmentPreviewDialog.tsx | 基础文件/图片展示、移除与预览；删除不在本批的媒体/业务能力，保留安全 fallback |
| 发送适配参考 | v4/composer/attachmentUpload.ts、v4/attachmentUploadTransaction.ts | 参考 content/ref、幂等/清理边界；不移植 ZCode v4 RPC、自动重试/本地路径直送策略，按 Ordessa 的真实服务做适配 |

+ 与 / 共用 Chat 私有 InputPanel，不新建平台业务组件包。上游依赖需要新增时先检查现有锁定版本，仅在所属包声明，由包管理器更新锁。不得为复用而搬整套 ZCode 编辑器、store、Tailwind 配置或协议栈。

## 验证、运行与交付

测试命令以固定集成树 package.json/pyproject 的真实脚本为准，S0 写进报告；缺测试脚本不等于通过。需 Chat 定向、会话适配、typecheck、根现有聚合、产品 build、Electron 冒烟。历史注册红按 ID+原因比较。新接缝测试必须真的执行，未接/skip 不算完成。

浏览器：1280×800、900×600、360px 嵌入视图、200% zoom；深浅主题、IME、键盘、长名单、长文件名、长工具输出、弹窗打开时切目标/卸载提供者；窗口不够时菜单缩高滚动，不能盖住唯一关闭入口。

受控链：选择项目→新草稿→添加文本文件/图片→发送→对端校验内容 hash/类型/目标→接受后只清快照；另跑拒绝/未知/断连/切目标，零模型。真实 Harness 支持矩阵不能从一个 fake 通过推广到全部品牌，单列未验证。

交付 report.md：baseline/提交、每条任务证据、源码复用账、契约变更、原失败 ID 对照、截图、控制链日志、资源清理、未验证项。只有 UI 不算附件完成；只有 gallery 不算产品接入；不自动合并/push、不操作现有服务。
