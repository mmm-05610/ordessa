# Blockers and bounded decisions

## B1 — 平台最终接口/集成 SHA 尚未冻结（实际开工阻塞）

观察时平台 Server 工作树仍有修改，不能把 `f02228cc9f` 当最终交付。其内部已有 custom contribution point 注册，但产品可消费的公开组合入口、领域 handler 的 busy/unregister 对接必须核验。

解决：等当前平台任务验收，T00 记录已集成 SHA 和真实导出符号；Harness 点由产品公开组合注册，不 import host internals。若缺通用接缝，向平台任务提出一个明确缺口并验收后继续；**不授权本任务回改核心，也不建设第二宿主**。API 纯类型与已有转换研究可先做，但生产集成不能报完成。

## B2 — 配置控制与当前 ACP session owner 的生产接缝未交付（实施内必解）

当前已有透明 transport 和 Claude adapter 探针，不等于存在能安全控制同一会话的生产配置端口。尤其认证配置不能通过桌面 JSON-RPC 暴露。

已裁定路线：扩展 Harness 内部通道控制与现有 connectors/acp 会话提交接缝；唯一 owner 负责协议关联，秘密只经后端 adapter session/start/resume 入口。不得额外建客户端或由 UI 直接编辑配置文件。

解决：T00/T13 给出实际控制端口、请求关联与身份/授权/generation DTO，做 L3 反例；沿现有代码能实现则本任务直接完成，不等另一任务“以后接线”。如果固定 adapter 缺安全 session-scoped 注入入口，提出具体最小 adapter 修改及许可证/pin 影响，不能悄悄改走全局 API。

## B3 — 旧 profile 名义下的数据分界（生产数据迁移条件门）

旧 Harness profile 同时可能指启动资源与预存配置，不能按名字一刀切。用户 Profile 已有独立实现分支，尚不能假设旧数据可丢。

解决：T01/T14 按 schema/调用者分流，用合成 fixture 完成迁移工具和幂等/回滚测试；若确需转换实际用户数据，另列数据格式/备份/回滚并请求授权。本方案只授权设计，未授权读取秘密或修改用户数据。没有实际旧数据则记录证据，不制造空迁移框架。

## B4 — 三主品牌具体 pin 下的配置六格还不是全绿事实（能力门）

已有调研不足以证明每个目标 adapter 都支持完整 provider/model/Skill 切换与 reset/resume。Claude 有受控 provider probe，但非产品全链；Pi/Codex 也必须以本仓 pin 为准，不盲升最新版本。

解决：T02 固定矩阵，优先已有原生控制，其次隔离配置重启恢复；需要小型 adapter 补充则在 Harness 内完成并补探针。无法保持同一会话/隔离的格子必须列未完成原因，不能改成“新建会话”或虚假支持。它阻塞完整完成声明，不阻塞其他可独立任务。

## 本包提出的范围裁定（请审阅，不暗中扩大）

1. 同意一次包含 Harness + Model-provider/Skills 适配迁移 + Profile/ACP 必需 glue + 产品装配；否则只能交框架，无法消除旧链。
2. 同意三主品牌六格为本批强制验收，其余品牌保留原有功能，新配置能力无证据不提供；不是八家全部配置全集实现。
3. 同意新增轻量领域包位于 plugins/harness/api，而非 packages 核心；外部业务依赖 API，不依赖 Harness 实现。

其余架构已在本包给出确定默认，不再把“方案 A/B 自选”留给无人值守执行者。未经用户审定不实施；审定后上述 B1–B4 依证据关闭，不重复询问已定语义，也不把小实现错误升级成新的授权门。
