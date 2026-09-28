# Z2 analyze/converge 查漏（R4，2026-09-28）

对 spec/plan/tasks ↔ 实现 ↔ 证据做逐条覆盖核对（Spec Kit analyze 阶段的人工执行；仓库脚本仅提供目录校验）。结论：**本线范围内无未解释缺口**；跨线缺口全部登记所有者。

## 覆盖矩阵（需求 → 证据）

| 需求来源 | 条目 | 证据/状态 |
| --- | --- | --- |
| spec.md 职责 | 复用正文/思考/紧凑工具展示 | display 11 例 + upstream-manifest |
| spec.md 职责 | 项目弹窗/项目内草稿/共享 + 斜杠菜单/附件贯通 | approval-project 10 例、panel-draft 7 例、composer-flow 7 例 |
| spec.md 职责 | DTO 与反例提供（前端会话服务归 C0） | api-requests R-Z2-*、adapters/agent.ts |
| spec.md 成功条件 1 | 四组来源→目标→行为→差异→测试 | upstream-manifest.json（kept/dropped/adapted）+ 测试 |
| spec.md 成功条件 2 | 深浅/宽度可读、键盘可达 | unit 层已证（主题 key、aria、键盘面板）；**浏览器宽度/缩放矩阵未验证→C0 装配** |
| spec.md 成功条件 3 | 流式/静态、同名跨会话、卸载重激活、审批失效反例 | 已证（display/composer-flow/approval） |
| spec.md 成功条件 4 | 独立 fixture 不加载真实业务服务 | facade-fixture + api 测试均为纯 fixture |
| spec.md R01 | 版权/许可/修改说明 | THIRD-PARTY-NOTICES.md + licenses/ + upstream-manifest |
| spec.md R02 | 只消费 DTO/受控状态/明确动作；不 import ZCode store/协议 | 审计通过（无 any、无跨域 import） |
| spec.md R04 | 展开状态按会话+内容隔离、随视图回收 | ViewExpansionState + display 例；无模块级 Map |
| spec.md R05 | 日志类文本不富渲染；无危险 HTML/自动远程请求 | Markdown 纯文本 fallback、linkSafety、流式外不执行（渲染层）；shiki 不执行代码 |
| spec.md R06 | 扩展面经由 chat-api；平台无 Chat 槽位名 | contract.ts 六槽位；平台包零改动 |
| spec.md R07 | 服务语义/磁盘 ID/引用不变 | facade 只消费；无 ID 改写；integration-request §4 |
| input-spec US4–US7 | N01–N06/C01–C04/P01–P06/A01–A06 | tasks.md 逐条勾选 + report §2；A06 内容 hash 待 C0 |
| 共同 spec R03 | chat-api 先发布、受控 proof、消费按固定 SHA | 三个 checkpoint + foundation 消费记录 |
| 共同 spec R05 | 上游未发布先做独立任务 + 精确接缝 | api-requests.md；无猜造 Token |
| 共同 spec R06 | 原包任务可追踪 | tasks.md 保留原 ID + 逐条证据 |
| 共同 spec R10 | clean commit + 报告 + 检查点 | 本次发布 codex/011-z2-ready |

## 查漏发现（本轮 analyze 新增/确认）

1. **基线测试计数变化**：foundation 合入后根套件从 13 文件/146 例变为 27/27 套件聚合（tooling/test-all）。已按新事实更新报告，沿用旧数字会失真。
2. **agent-contracts 位置迁移**：foundation 将 `packages/desktop-platform/contracts/agent-ui` 迁至 `plugins/agent/contracts`。本线别名/测试导入已同步更新（merge 0a05235d0f + 后续修正），契约 id `ordessa.agent-contracts` 未变。
3. **lucide-react 1.17.0 无实际引用**：取材清单曾声明，实现后未使用，已从依赖移除并同步 notices/manifest——避免「声明而未用」的许可噪音。
4. **chat-page `+` 按钮与 slash 面板的互斥**：由 PanelState 单状态保证；已由实现结构确认（无独立测试用例——标记为低风险，两个入口的开关行为在 panel/flow 测试中间接覆盖）。
5. **未完成项**（全部带所有者，非本线偷懒）：A06 受控 hash 往返、命令目录/附件真实接线、浏览器矩阵、产品启用与旧链关闭、根锁生成——见 report.md §5。

## converge 结论

- 本线可交付面已收敛：`codex/011-z2-ready` 指向最终提交；后续接缝落地（R-Z2-1/2/3/5/6）后在本分支继续接线并回填 report，不重开需求。
- 与兄弟线的两个接缝提醒：Z1/Q1 消费 chat-api 请固定 r3 分支 SHA（3d8c3fa410）；C0 装配请按 integration-request §1 顺序同时启用 chat-api 与 chat。
