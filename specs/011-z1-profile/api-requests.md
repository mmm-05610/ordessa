# Z1 api-requests（符号缺口清单，按 checkpoints.md 消费协议维护）

消费者：Z1（plugins/profile）。每次检查点发布后按固定 publication SHA 消费并回填状态。
请求 owner 见 011-plugin-rollout/plan.md；本文件只登记 Z1 需要的公开符号。

## 对 C0 `foundation`（分支 codex/011-foundation-ready，未发布）

| 调用者 | 目标操作 | 需要的符号/包 | 失败反例（缺它时的行为） | 状态 |
| --- | --- | --- | --- | --- |
| profile frontend management | 两级导航/表单/面板 | `@ordessa/ui`：Panel、Toolbar、ScrollArea、Button、Input、Select、Checkbox、Field（reuse-map 指定） | 无则管理器 UI 无法按已审平台控件实现；不私造 CSS 控件替代 | 待发布 |
| profile frontend editors | 贡献组件装载 | `@ordessa/ui-components/react`：ComponentOutlet、useUiBinding（C7） | 无则第三提供者 editor/settings 无法装载（G16/G19） | 待发布 |
| profile frontend settings/management | 管理入口注册 | Workbench `composition.forScope(scope).addModule/addSettingsSection`（contracts/workbench 已在树，需 foundation 装配真实宿主） | 管理器入口无法打开；不改 Workbench 侧 | 待发布 |
| profile frontend | 服务域显示/离线状态 | Server 连接/服务域公开 API（serverRef、可用性） | 服务域选择器与离线标注无真实数据源 | 待发布 |

## 对 C0 `harness-api`（分支 codex/011-harness-api-ready，未发布）

| 调用者 | 目标操作 | 需要的符号 | 失败反例 | 状态 |
| --- | --- | --- | --- | --- |
| profile sessions（PV-07） | 真实应用接缝 | Harness 公开配置端口：inspect/plan/apply/reconcile（application.md §2 语义），类型化 PlanResult/ApplyOutcome/fence | 端口缺席时 begin_turn_application 只能 typed blocked（APPLICATION_PORT_ABSENT），不能证真实全链；G09–G12 只能到 controlled fixture 级 | 待发布 |
| profile sessions | 会话身份映射 | canonical SessionRef 的服务端映射证据（data-model.md §1：Server/连接归属、Harness、native session） | 旧 session_id→canonical ref 迁移只能用 legacy 映射（realm='local'），跨连接真实映射待会话所有者 | 待发布 |
| profile frontend chat glue | 发送准入门互斥 | 下一轮提交的配置应用准入门（与消息发送同一互斥点） | 无法证明“apply 与 send 不重叠”（G09 服务端半边） | 待发布 |

## 对 Z2 `chat-api`（分支 codex/011-chat-api-ready，未发布）

| 调用者 | 目标操作 | 需要的符号 | 失败反例 | 状态 |
| --- | --- | --- | --- | --- |
| profile integrations/chat（PV-10） | 输入工具栏选择器贡献 | ChatContributions 公开注册面（输入工具栏 selector 槽位）、草稿/会话 Harness 分组数据 | Chat 选择器 glue 无法挂载；无 Chat 时本线其余不受影响（R07） | 待发布 |

## 消费记录

- **foundation**：publication SHA `8844c475bc02a185ab194c69eed873122aa48349`
  （producer c0，READY，impl `8229e20824` 已核祖先），2026-09-28 merge 至本线
  commit 10e6dd7965。消费后复跑：Python 130 passed、boundary 0 violations、
  12/12 反例、profile-api tsc 0 错、glue 10/10。适配点：pacthold 资源契约
  移至 `pacthold_runtime_compat`（`agent-box.profile@1` id 不变）；loader 要求
  provider 声明 contracts。`@ordessa/ui`、`@ordessa/ui-components`、C7/C8 已可导入。
- **chat-api**：publication SHA `54ad26c15d8480823374d85590919ba6bcca60d2`
  （producer z2，READY，impl `a3ec20c046`），2026-09-28 merge 至本线。其检查点
  基于预 foundation 快照（limitations 已声明修订计划）；本线通过 carrier
  specifier `@extensions/ordessa.chat-api/contract.js` 消费（vitest 本地 alias，
  tooling/vitest-extensions.mjs 共享注册列 integration-request）。PV-10 glue
  已实现：tsc 0 错、10/10 测试（含 jsdom 渲染：即时所选名、无状态徽标、
  分组两级、disabled reason 透传）。
- **harness-api**：已发布。publication SHA `d3f026904e`（producer c0，READY，
  impl `61966e3118` 祖先已核，dependsOn foundation+permissions-api），按固定
  SHA 合并消费。消费后：`HarnessApiConfigPort` 对接真实
  `ConfigurationApplicationService`（产品 carrier + 受控 runtime/permit/journal
  注入，按检查点自身认证的可消费级别），5 项载体/真实服务测试覆盖
  confirmed/refused/unknown/reconcile/permit 缺席。
  **诚实边界（源自检查点 limitations）**：生产 ACP admission ready=False
  （Q5 authorizer/一次性 permit/生产 pre-effect 未接线）；操作绑定的 native
  receipt 缺失 → reconcile 只读、Unknown 无法升级；真实品牌矩阵另列。

### 根锁差异（本线生成，待 C0 最终生成）

`npm install` 为新 workspace 包（plugins/profile/api、integrations/chat）生成
根 package-lock.json 增量 42 行（/tmp/z1-lock-delta.patch 已留档，检查点导出前
还原本线锁改动，最终根锁由 C0 生成并提交）。
