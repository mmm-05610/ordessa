# Nova feature delivery 阶段报告

请填一个外部阶段的报告 value。结构有效不认证身份、角色、审批或上游状态。每份报告须绑定其 blueprint、当前 cycle、前序报告的 artifact revision 和精确上游证据。

- `report_id` / `phase` / `reported_at`：
- reporter `actor_id` / `role_claim`：
- `cycle` 与 Blueprint URL / ID / 状态：
- spec requirement / spec 状态（仅筛选阶段填写；`spec_required=true` 时可以先没有 spec URL）：
- `decision` / `decision_record`（角色、决定时间、上游 authority URL、理由摘要）：
- `result` / `summary`：
- Gerrit change / patchset（适用时）：
- Zuul pipeline / buildset / Verified / failure class（适用时）：
- merge commit 或 release version / URL / included commit（适用时）：
- blocker、owner、next action、resume condition：
- predecessors 与 evidence URLs：
- limitations：
- `feedback_summary` / `follow_ups`（feedback 阶段必填）：
