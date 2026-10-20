# Flow coverage boundary

The complete process is specified in [PROCESS.md](PROCESS.md) and represented as a report contract in [projection/documents/product-change-report.schema.json](projection/documents/product-change-report.schema.json). No full-flow manifest is present. The only method manifest is [projection/method.yaml](projection/method.yaml), named `ordessa.gitlab-product-change.report-smoke`, and explicitly declares `full_flow_support: unsupported`.

| External stage or behavior | Preserved in the complete process/report contract | Covered by smoke projection | Full-flow execution support |
| --- | --- | --- | --- |
| Problem / issue validation | Yes: evidence, hypothesis, confidence, decision, owner, rationale | A completed report may record it | Unsupported |
| Design and solution validation | Yes: design/research/test evidence and justified skip/defer decisions | A completed report may record it | Unsupported |
| Planning, prioritization, refinement | Yes: MVC/scope, dependencies, milestone, acceptance and test plan | A completed report may record it | Unsupported |
| Development, test, MR review, and merge | Yes: reported revision, checks, reviewers, decisions, MR and exact references | A completed report may record it | Unsupported; no Git/CI/review operation |
| Validation and Build as independent, overlapping/parallel tracks | Yes: independent track status, overlap/feeds/blocks/handoff links, skip decisions | A completed report may record the relationship | Unsupported; no parallel execution or route |
| Block, wait, resume, and unblock | Yes: blocker, owner, actions, expected/review times, resume condition and history | A completed report may record before/after observations | Unsupported; no wait descriptor/source bound here |
| Rework and new revision | Yes: trigger, affected stage, follow-up issue/revision, exit checks and outcome | A completed report may record history | Unsupported; no lifecycle loop or automatic restart |
| GitLab.com deployment verification | Yes: stages, target environment, live version and evidence | A completed report may record claims/references | Unsupported; no deployment/current-state source |
| Self-Managed upstream stable release/package availability | Yes: upstream release/package version and availability | A completed report may record it | Unsupported; no release source |
| Optional Self-Managed target installation and live-version verification | Yes, separately from upstream release | A completed report may record the instance and evidence | Unsupported; no target-instance source |
| Result measurement, customer feedback, Improve, iterate/rollback/abandon/restart validation | Yes: metric definition, baseline, window, outcome, decision, owners and follow-up | A completed report may record the outcome | Unsupported; no observer or subsequent-cycle routing |
| Postpone, reject, cancel, close, or leave open | Yes: decision, owner, reason, unfinished work and resumption/closure criteria | A completed report may record the result; rejected operation only rejects report capture | Unsupported as issue-state changes |
| Report artifact capture | Yes: complete report payload structure | One registered engineering.artifacts.create call only | Supported only as a single report-capture operation, pending coordinator verification; not flow completion |

## Exact compiler/catalog evidence

- ordessa.methods/v1 is a bounded manifest/workflow contract. packages/engineering/src/ordessa_engineering/methods/definitions/schemas/v1.py defines its current expression; packages/engineering/src/ordessa_engineering/methods/validation/workflow.py enforces registered operation outcome sets and acyclic reachability. There is no general conditional, loop, or parallel node. A method can only route on an exact registered operation outcome.
- The catalog snapshot docs/implementation/packages-convergence-20261012/engineering/CAPABILITIES.json lists 18 registered commands and 2 checks. The sole operation in this smoke projection is engineering.artifacts.create, interface version 2, digest 0bc02e9e5a17ada14fc47a3da92abd6c360247768ab0ab1debfc6ec444b213f4, with outcomes completed and rejected. The descriptor's completed outcome is artifact transaction completion only.
- The same catalog snapshot contains an empty published_wait_descriptors list and notes wait families require trusted current Work business bindings; no event/registered wait catalog was fabricated. docs/implementation/packages-convergence-20261012/engineering/methods-luna/METHOD-EXPRESSION.md explains that structural waits and CAS-backed run resumption have partial implementation, while trusted owner source/catalog binding remains a separate dependency. That is a general capability fact, not a GitLab event adapter.
- The projection binds the report schema by exact method resource and its ID is urn:ordessa:gitlab-product-change:report:v1. engineering.artifacts.create maps input slots; this method does not place fixed command values in config. The projection's actual compilation/payload codec remains coordinator-owned verification and is not asserted in this package.

All three files under _support/design-traces/ are synthetic schema examples. They do not show compilation, workflow execution, trusted GitLab source admission, or successful artifact creation.


协调者进一步核对了编译与运行差异：分支语法存在，但当前运行桥只消费有限命令的 journal completed/rejected；Work入口还须是通用current-condition wait并绑定resume contract。完整分类、精确接口和三个设计问题见 [_support/verification/design-findings.md](_support/verification/design-findings.md)，实际静态校验见 [_support/verification/README.md](_support/verification/README.md)。
