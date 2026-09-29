# continuous-operation.md — 持续推进协议（今晚最重要的行为规范）

自 `/goal` 启动持续执行起，直到 **2026-09-30 08:00 Asia/Shanghai**，整个任务
**不得因为以下任何情况而结束**：

- 某一阶段完成 / P0 完成 / P1 完成
- Morning Candidate 达成
- 当前显式 backlog 做完
- 一个 Worker 返回
- 一个测试失败 / 一个 blocker 出现
- 一个 Harness 不可用 / 某外部服务失败

## 唯一正常结束方式

- **A.** 用户明确叫停。
- **B.** 进入最终 Closeout 并完成。
- **C.** 执行环境完全不可用，且：无法重试、无法换 Subagent、无法换方案、
  无法推进任何其他独立任务。
- **D.** 所有仓库内合理任务已穷尽，并经过**至少两轮**主动产品巡检仍找不到值得推进的任务。

**单个 blocker 永远不满足停止条件。**

## Lead 永久在线工作队列

Lead 必须持续维护（在 ledger.md 内）：

| 队列 | 含义 |
| --- | --- |
| NOW | 正在执行的任务（含 owner/branch） |
| NEXT | 已就绪、可立即派发的任务（NOW 快空时提前从 NEXT 拉任务） |
| REVIEW | 等待 Independent-Reviewer 审查的成果 |
| VERIFY | 已 review、等待真实验证/集成验证的成果 |
| BACKLOG | 已发现、未就绪的任务（含主动发现池） |

原则：**Lead 的职责不是"等待所有 Worker"，而是"保证整个系统持续有有效工程工作
在发生"。** 不能等所有 Agent 都 idle 后才思考下一步。

## 完成一项后的默认动作

- **PASS**：review → integrate（cherry-pick 进 NIGHTLY_TRUNK）→ verify（重跑 relevant
  gate）→ checkpoint → 派下一项。
- **FAIL**：第二方案 / Blocker-Surgeon / Integrator / Escalation-Architect；
  同时继续独立任务。
- **BLOCKED**：入 ledger → 找替代路径 → 继续其他任务。

任何 Subagent 说"建议后续……"/"需要用户确认……"/"发现 blocker……"/"任务完成……"
都不能自动结束主会话。

## 主动发现模式

显式 backlog 做完以后，重新审计真实产品，从这些地方主动找任务：

- acceptance 未充分验证项
- `docs/known-issues.md`
- failing/flaky tests
- specs 已实现但未装配能力
- plugin 已存在但默认产品未接
- deb 缺资源
- 开发版/安装版差异
- Profile→facet→Harness 断点
- Skill/MCP/Prompt/Permission/Memory/Runtime Preferences
- multi-Harness capability/UI 不一致
- error handling / restart / persistence / session isolation / plugin boundary
- host 内业务硬编码
- 用户明显会遇到的 UX defect
- 测试薄弱点
- 可安全清理的小型 architecture debt

**不要为了有任务而发明新功能。** 所有任务必须来自现有产品目标、已有实现、
已有 spec、真实问题或合理收尾。

## Morning Candidate 之后

第一次达成 Morning Candidate：立即形成绿色 checkpoint（C-MC1），然后继续，优先序：

1. 扩大真实 Harness 覆盖
2. 补 Profile/Skill/MCP/assets 产品能力
3. 修 UX/error handling
4. 增加 installed-product smoke
5. 修低风险 architecture debt
6. 增加 regression tests
7. 清理代码和文档

后续 candidate：Candidate 2 / 3 / 4……**后一个不能比前一个差。**

## 禁止任务结束心理模型

今晚禁止：`TODO LIST → 做完 → 汇报 → 退出`。

必须采用循环：

```
OBSERVE → PRIORITIZE → DISPATCH → CONTINUE → REVIEW → VERIFY
→ CHECKPOINT → DISCOVER → 再循环
```

直到 Final Closeout。

## 失败策略

- 第 1 次失败：原 Agent 自查。
- 第 2 次失败：换方案。
- 仍失败：Scout 重新定位 / Blocker-Surgeon / Integrator。
- 方案存在架构争议：Escalation-Architect。
- 仍无法解决：记录 blocker。非 P0 → 推进其他任务；P0 → Lead 继续尝试
  alternative path，同时保持其他独立线程工作。

禁止：一个 Worker 报告 BLOCKED → 整夜停止。

## External Blocker 定义

只有真正超出仓库控制的情况才能写 `BLOCKED_EXTERNAL`：用户账号未登录 /
subscription quota exhausted / external provider outage / sudo 不可用 /
网络完全不可达 / 必需外部 executable 根本没装且不能安全安装。

即便如此，必须证明 Ordessa 已运行到 external boundary——不能写"Codex 没跑，
所以不知道"，而应证明：

```
Ordessa → Harness discovery → launch config → process spawn
→ protocol init → external auth/quota refusal
```

然后再标 external。
