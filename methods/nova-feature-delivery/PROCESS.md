# Nova feature delivery 外部流程

## 目的、边界和输入

本方法供 Nova feature 从 Blueprint 提案到一个正式 Nova release 版本的跟踪。它要求开发者和指定 Nova 社区角色完成上游决定，并要求报告与其权威记录链接。Git 分支、补丁、文档修改、Gerrit、Zuul、合并、打包和发布由 Nova/OpenDev 外部执行者完成。Ordessa 只登记阶段报告、决定摘要、明确周期和精确版本绑定；其工程 artifact 成功不替代任何 Nova/Gerrit/Zuul 权限或验收。

开始时由贡献者提供：目标问题与用户影响、拟议行为和边界、兼容/升级影响、测试/文档影响、依赖和安全/性能考虑、候选发布周期、可联系的 feature liaison 或 Nova driver、已知 blueprint/spec/bug 链接。没有清楚问题或周期的提案先补齐，不进入批准请求。所有外部阶段输出应包括来源链接和时间；Ordessa 报告以固定方法快照和不可变 revision 串起版本链。

## 角色

- **贡献者/blueprint owner**：撰写并维护 Launchpad Blueprint 和适用的 Nova spec；回应评审；实现补丁、测试和文档；维护 blueprint whiteboard / Gerrit topic；发布阶段报告。
- **Nova drivers / nova-specs-core / PTL**：按 Nova 社区权限讨论优先级、是否需 spec 和周期批准。只有具有上游相应权限的人给出的决定才是该步骤的依据。工程系统中声称的 actor 身份本身不能授予此角色。
- **Nova reviewers / core reviewers**：审阅 Gerrit change、给出 code-review vote 和 Workflow 批准；具体规则以目标仓库当时的项目策略为准。
- **Zuul / OpenDev CI**：运行配置的 check 与 gate jobs，将结果报告回 Gerrit。日志中的结果须与精确 patchset、pipeline 和 buildset 绑定。
- **发布团队 / release manager**：处理冻结后例外和发布准备；按官方发行流程宣布版本。
- **Ordessa 报告者**：将外部证据摘要为 `phase-report`，保留上游 URL、周期、先前报告 revision 和限制；不得把自述变成上游通过证明。

## 阶段及进入/退出条件

每个阶段只产出一个新报告；同阶段重报代表新 revision。必须报告适用性；跳过规则限于以下情况，报告仍以 `not_applicable` 记结果并说明依据。

1. **Blueprint**：输入具名需求和 owner。贡献者建立或更新 Launchpad Blueprint，说明目标、用户/运维影响、候选周期和未决事项。退出条件：Blueprint URL 与标识可访问、状态可辨，且提案足以讨论。没有登记 Blueprint 不进入审批。
2. **判定是否需要 spec**：Nova 规则是凡需要 spec 就需要 blueprint；API 改动需要 spec；单个小补丁、触及范围小、运维者和文档影响有限时通常可不需要 spec；不确定时请 PTL 或其他 Nova driver 判断。报告 `spec_required` 必须是 `true` 或 `false`。如果需 spec，进入 spec 审查；无需 spec 时保留此分支，依据和判断者必须记录，随后仍要走 Blueprint 的本周期讨论/批准。不能因方法包里没有 spec 而静默略过。
3. **设计评审**：需要 spec 时，贡献者提交 Nova spec，讨论方案、API/数据库/安全/兼容/升级/运维/测试/文档影响。spec 记设计协商，不代替最终代码文档。退出条件：相应 Nova reviewer 的评审结果已明确为修改、拒绝或获批；修改意见需有责任人和待办。
4. **本周期批准**：需要 spec 的项目要有在当前 release cycle 获批的 spec；Nova spec 只对一个周期批准，跨周期要重新提案。无需 spec 时将 Blueprint 放到下次 Nova 会议议程并提供足够上下文。退出条件：记录被授权的 Nova 角色给出的当前周期决定及上游状态。待议/待回复保持 waiting；不把 `+1`、Ordessa 人类确认或外部公司同意替代 Nova 批准。
5. **补丁、测试和文档**：仅周期批准后进入实现。按已讨论的设计完成小步代码补丁、测试、用户/管理员文档及必要发行说明；所有相关补丁采用同一 Gerrit topic，commit message 关联 Blueprint。报告实现 revision、测试覆盖和文档链接；尚未齐备则继续实现，不标记可审阅。
6. **Gerrit review**：将每个 change/patchset 上传到目标项目 Gerrit，正确关联 Blueprint 并维护 whiteboard。评审通过、请求修改、程序性阻断、放弃均分别记录。负评时先回复澄清，按意见修改并上传新 patchset；不理解的意见直接询问；评审者之间冲突时先暂停推补丁并协商，必要时提 Nova 会议仲裁。新的 patchset 必须重新经历 check；不得把旧 patchset 的 +1 或绿灯套给新 patchset。被 abandon 的 change 若重提须报告新链接。
7. **Zuul check**：每个新 patchset 会触发项目 check jobs，结果以 Gerrit `Verified +/-1` 回报。报告必须绑定 change、patchset、pipeline、buildset 和日志。如果相关错误是本次代码/测试导致，修复后上传新 patchset；若怀疑已有非确定性失败，先查日志、elastic-recheck 和相关 bug，再按上游惯例请求 recheck。若是 CI/基础设施失败，检查 OpenDev 状态与 IRC/Matrix，必要时将基础设施故障报给 openstack-gate；分类未明时 `unknown` 并等待诊断。严禁仅因出现失败就标成产品代码失败，也不能用 `recheck` 掩盖已确认的变更缺陷。
8. **Zuul gate**：上游评审满足项目规则并由 core reviewer 置 `Approved +1` 后才进入 gate；gate 通过由 Zuul 给 Gerrit `Verified +2`。依赖 change 时核实 `Depends-On` 和队列顺序，无循环；CI 设置本身的变更不等于在生产模拟环境中已验证。退出条件：精确 patchset 的 gate 通过并满足 Gerrit 所有合并门槛。相关代码失败回到修改/check；设施失败回到外部故障诊断/等待；未决不前进。
9. **合并**：Zuul gate 成功并通过授权规则后由 Gerrit/Zuul 合入，不由报告者自称合入。记 repository、branch、commit SHA、合并时间和关联 change。退出条件：Gerrit 显示已合并且实际 commit 可解析。post/merge-check 若失败，按其外部流程调查；不把合并观察报告为测试全绿。
10. **发布准备**：确认合并 commit 已包含在目标 Nova 分支/周期，补齐 release-note、文档、翻译冻结、依赖冻结和发布团队所要求的事项。Nova 周期过程区分 Feature Proposal Freeze（代码应已送审）、Feature Freeze（feature code 应已合入）、String Freeze、Dependency Freeze。冻结后要延期，必须报告未完成项、错过哪个 freeze、拟定的新周期，并请 Nova drivers/PTL 和受影响横向团队/release manager 重新评审；Nova blueprint 仅对单周期有效，重获批准前不能继续声称本周期可合并。此方法不替用户虚构固定日历日期。
11. **正式版本**：只有官方 Nova release 页面或正式 release notes 证明版本已发布，才记录 release。绑定版本号、官方 URL、发布时间与确切 commit/change 清单。仅发布准备完成、stable branch 上有提交或某个别测试通过，都不是正式版本发布证明。

## 等待、返工、拒绝、取消与反馈

等待是一种外部流程状态：报告 `waiting`/`deferred` 的事实、负责角色、上游待办链接、所等条件、最近检查时间和恢复所需证据。恢复时先重新确认周期批准、Blueprint 当前状态、最新 patchset 及 gate 状态；若冻结或授权过期，退回当前周期评审，而不是沿用旧批准。此方法图没有发布的 wait descriptor/event source；因此等待、唤醒和恢复均由外部负责人执行并另行提交阶段报告。

评审负面意见进入返工：把每条意见映射到修改/澄清/反对理由和新 patchset；保留负评历史。负面意见解决不等于流程批准。评审拒绝、Blueprint 未纳入周期、spec 未获批或优先级冲突，均停止当前周期实施；可记录拒绝并由 owner 选择撤回或下一周期重新提案。延期不伪装为通过，必须重审 Blueprint/spec 及周期批准。

贡献者可在未开始或任何未合入阶段取消，需记录取消人、时间、原因、遗留 Gerrit/Blueprint 状态及是否需要 abandon/撤回；外部账号动作由授权上游用户完成。合并后的取消不能撤销历史：新建后续修复/撤回/弃用提案，遵循 Nova 正式治理。方法自身没有 cancel operation 或外部副作用能力。

每个周期完成/停止后生成反馈：结果（发布/拒绝/撤回/延期）、目标周期和真实最终版本（若有）、偏差与原因、失效/迟延的等待点、check/gate 失败分类、未解决风险和方法改进建议。没有正式版本时必须保留 `release: null` 并说明。Ordessa 可登记该反馈，但不能以此证明用户部署、运行或采用。

## 与已核实 Nova 示例的对照

Nova spec 的历史记录显示同一 virtiofs/Manila Blueprint 经 Yoga 引入后多次在不同周期重新提案，最终 2025.1 Epoxy 目录中的条目标记为 `implemented`。官方 2025.1 Nova release notes 亦列出 Manila shares 可通过新的 Nova shares API 直接附加实例。证据只支持“该功能进入 2025.1 正式发布范围”和 spec 页面记录的实现状态；不证明全部 CI job、客户环境部署或每个后续补丁均已通过。请求中给出的 `2025-03-06` 完成日期未由可访问的上游记录独立证实，本包不把它记成事实。
