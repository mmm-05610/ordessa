# 阶段报告契约

本契约把一次外部阶段观察记录为一个 Ordessa `evidence` artifact。记录只表述提交者看见的状态；Gerrit、Zuul、Nova 会议、Launchpad 或 OpenStack 发布都仍是上游权威。每个报告以相同 Nova blueprint URL 和 release cycle 关联；`predecessors` 明确指出前序 `report_id` 及不可变 artifact revision，返工通过新报告延续链，禁止覆盖旧记录。

`projection/documents/phase-report/schema.json` 是 `phase-report` 的 method-content value schema。调用 `engineering.artifacts.create` 时需传 interface-2 的完整输入：`kind: "evidence"`、`method_refs: [当前投影方法的精确 MethodRef]`、`initial` 为 MethodPayload envelope。`initial` 的 `content_kind` 为 `method_content`；`inline_value.schema_ref` 精确绑定当前 MethodRef、投影内 schema resource id、逻辑路径和 SHA-256；`inline_value.value` 是报告对象；`rendered_body_ref` 为 `null`。`schema_id` 必须等于绑定 schema 的 `$id`。当前 artifact material closure 可验证此精确引用和报告 value；仅有 schema resource 并不强制校验，且此校验不构成完整流程执行。

schema 对 `phase` 使用有限枚举，并对 spec 分支、Gerrit/Zuul、合并、发布报告施加各自必填项。无 spec 的 cycle approval 可明确携带 `spec_required:false` 与 `spec:null`；spec required 为 true 但 spec 尚未提交时也可暂为 null，正式 design review 通过或要求修改时才要求 spec 对象。条件规则仅用于报告文档形状，不会形成方法图上的条件跳转。其余重要的语义校验在 `PROCESS.md` 规定：cycle、Blueprint、Gerrit change/topic、patchset、Zuul buildset、合并 commit 和 release version 必须相互匹配；报告必须提供可追溯上游链接。schema 有效不证明 URL 真伪、状态新鲜度、角色资格、批准效力或测试结果。

`engineering.artifacts.create` 的唯一本地 workflow 输出是 `completed` 或 `rejected`。它们表示工程 artifact 命令持久化成功或业务拒绝，不代表 Blueprint 获批、设计通过、Gerrit 合入、gate 通过或 Nova 发布。`projection/` 内的 `report-intake` 是一份报告的 capture smoke 投影；每阶段由独立报告会话登记。它不是 Nova 流程调度器，更不是完整流程投影。完整能力覆盖判断见 `COVERAGE.md`。
