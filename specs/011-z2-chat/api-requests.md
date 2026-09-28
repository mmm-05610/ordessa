# Z2 api-requests：接缝需求与符号缺口（对 C0）

本线依据 input-contracts.md §3、service-adaptation.md 与本树 `agent.ts` 现状列出缺口。消费者：`plugins/chat`（前端 ACP/Ordessa 会话服务归 C0）。生产者发布检查点后按协议固定 SHA 消费；未发布前相关条目保持未勾选，不猜造 Token。

## R-Z2-1 提交三态结果（submit acceptance）

- 调用者：Chat composer/草稿发送路径（CHAT-V03/V07，input-contracts §2）。
- 现状：`AgentClient.send(sessionId, text): Promise<void>`、`createAndSend(...): Promise<{sessionId}>`；resolve 语义是「已接受进发送路径」，拒绝/未知不可判定（service-adaptation §3 已登记）。
- 请求：会话服务公开 `accepted / refused(reason) / unknown` 可判定结果；`unknown` 保留 requestId、禁止自动重发。文本兼容保留。
- 失败反例：断连后 resolve 不得解释为 accepted；拒绝不得清草稿。
- owner：C0（connectors/acp、connectors/ordessa、会话服务）。

## R-Z2-2 附件 prepare content / 发送引用

- 调用者：附件贯通（CHAT-V07、A02–A06）。
- 请求：`prepare(target, 内容, 幂等键) → 不透明 ref`（可取消/清理、所有权归服务）+ submit 接受 refs 集合；类型/大小/数量/路径引用能力查询 `capabilities(target)`。
- 反例：元信息无内容不得 ready；远程不可达路径不得直送本机绝对路径；refused 保留附件；unknown 不自动清理/重传。
- owner：C0（资源传输 + 会话服务适配）；品牌差异归 Harness。

## R-Z2-3 原生命令目录

- 调用者：/ 斜杠原生命令组（P04/P05、CHAT-V06）。
- 请求：`target → commands/loading/error/capability` 目录投影；无目录时缺席（本地插件菜单仍可用），不显示伪命令。
- 反例：目录错误局限该来源；缺席不阻塞本地来源。
- owner：C0（会话/ACP 投影；Harness 品牌差异）。

## R-Z2-4 项目服务的全局弹窗取数

- 调用者：US4 全局项目选择弹窗、添加项目（N01–N04）。
- 现状：本树 `AgentSessions` 已有 `selectWorkspace/addWorkspace/refreshWorkspaces` + `AgentWorkspaceSnapshot.draft` 门（可用，已验证）。缺口：弹窗需按**服务身份分组**展示项目（serverInstanceId + normalizedPath）；`AgentWorkspaceInfo` 目前只有 `id/normalizedPath/environment`，弹窗「显示服务归属、重名不混淆」可用 connection 列表组合实现，暂不新增字段。
- 请求：无新接口；要求 C0 集成时保留 draft gate 语义（`canSend/blockReason/endedBy`）不回归。
- owner：C0（集成保持）。

## R-Z2-5 reasoning/消息块序列增强（非阻塞）

- 现状：`AgentMessage.reasoning: string` 无独立状态/耗时；无统一消息块序列。
- 请求（增强，缺席不阻塞展示）：reasoning 独立 streaming/complete/interrupted/unknown + 真实 duration；块序列按到达顺序。
- 本线处理：无证据时显示 unknown/无耗时，快照展示，不猜交错顺序（service-adaptation §2）。
- owner：C0（会话/协议投影服务）。

## R-Z2-6 native picker 安全读取

- 现状：`window.projectDirectory?.choose()` 已存在（electron preload）。
- 请求：附件需用户选择的**文件/图片** picker 同等安全通道（授权资源，非任意路径读取；不带 Node fs 进 renderer）。
- 反例：无 picker 时入口按原因禁用，不伪造。
- owner：C0（平台桥）。

## 已可消费（本树真实服务，非请求）

- `AgentSessions` draft/project gate、`startDraft/discardDraft/selectWorkspace/addWorkspace`、`send/stop/respond/setOption`、runs/interactions/options 投影：本树 `96fef2db47` 已有并测试覆盖；Chat 直接消费。
- Workbench `composition.addOverlay/addSettingsSection/addModule`：本树已有，弹窗/设置章节用它，不另建浮层系统。
