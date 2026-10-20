# Source index and reuse notes

检索时间：2026-10-12 UTC。正文为独立中文概括与适配记录；未复制 GitLab 手册的阶段模板、原文段落或图示。方法名和状态值是识别外部流程所需的引用词。外部页面会变动；除下方记录的页面可见 footer 信息外，此 bundle 没有完整抓取页面内容，也没有把这些 footer commit refs 当作经过核验的页面内容快照。创建报告时保存实际使用的 instance/status model、原始 URL 和观测日期。

| ID | 官方 GitLab 来源 | 本方法使用内容 | 版本观察 |
| --- | --- | --- | --- |
| `gitlab-product-flow` | [Product Development Flow](https://handbook.gitlab.com/handbook/product-development/how-we-work/product-development-flow/) | Validation/Build 双轨、阶段目标、可跳过/重叠、issue statuses、status/label 迁移、Build 与 Improve 阶段 | 页面称其内容是 evolving/current workflow；页面 footer 显示 2026-08-27，链接 commit `4469685d`。页面正文的迁移说明写 scoped `workflow::*` labels 在 2026-02-27 后 unsupported。引用的 footer commit 不是本 bundle 固定的页面 bytes。 |
| `gitlab-application-lifecycle` | [Application Lifecycle Team Workflows](https://handbook.gitlab.com/handbook/engineering/infrastructure-platforms/developer-experience/application-lifecycle/workflow/) | 团队 Kanban、旧 workflow labels、blocker 处理、该团队略过设计/方案验证的说明 | 页面 footer 显示 2026-08-21，链接 commit `6b0a1bdd`；页面仍用 `workflow::*` label。它是一个团队的本地实践，不覆盖 Product Development Flow 的状态迁移说明。footer commit 未在此作为页面 bytes 固定版本。 |
| `gitlab-deployment-paths` | [Deployment Workflow](https://handbook.gitlab.com/handbook/engineering/testing/deployment_paths/) | GitLab.com 与 Self-Managed 的不同部署/发布路径、版本与环境验证；merge 后仍需部署/检查 | 页面 footer 显示 2025-12-15，链接 commit `56a49071`。页面内含 GitLab.com canary/staging/production 例子和 Self-Managed stable branch/tag/package 例子。这些是 GitLab 自身流程，不视为所有项目的统一路径；footer commit 未在此作为页面 bytes 固定版本。 |
| `gitlab-handbook-license` | [GitLab Handbook source repository LICENSE](https://gitlab.com/gitlab-com/content-sites/handbook/-/raw/main/LICENSE) | 项目许可证标识观察 | GitLab Handbook source repository 的根 LICENSE 标识为 MIT。本文为独立概括，未复用实质性手册文本、模板或图示。源仓库 main 分支与许可证文件可能更新。 |

## 主要版本差异

Product Development Flow 页面报告 statuses 已替换 scoped workflow labels，并说明其预期淘汰日期已过；Application Lifecycle 团队页仍以 workflow labels 展示 Kanban 且保留 blocker/每日活动等本地流程。前者最近 footer 日期为 2026-08-27，后者为 2026-08-21。页面日期、footer commit 和内容发布/实例功能启用并非同一个事实。本方法不把页面存在推导为所有 GitLab 实例均使用相同 schema，也不裁定状态功能已经在每个目标实例启用。新报告必须用 `issue_state_model` 明确记录它实际观察到的是 `issue_status`、`workflow_label` 还是其他，并保留 exact value 与 observed-at。

部署页展示 GitLab.com 内部 canary/promotion 与 Self-Managed stable release/package 两条路径；报告分别填充两个路径字段，并以目标环境中的实际证据绑定版本。不得用 GitLab.com 流程推断 Self-Managed 部署完成，也不得用 merge 或 package publication 推断终端实例已上线。
