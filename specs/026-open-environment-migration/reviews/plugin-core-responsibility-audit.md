# 插件与核心职责审计：已设计迁移项与真正遗漏

日期：2026-10-03。只读源码分析，不是生产回归，不修改既有产品语义或自动批准下列补充提案。

源码：M main `b4bf7cd90951d0fa9bcf3a3de2e66b7db6a62aa0`；P 产品树 `7951bf06a258d2dc41402556eb61319b8bab5cbe` + 工作内容。两树HEAD本轮核对；主要逐文件证据来自M。025/024对P的旧盘点仅作定位，不代替当前运行证据。本轮重点覆盖Agent/Chat/connector/Profile/model-provider/Skills/Subagents/Prompts/MCP/extensions/compat以及对应前后端平台；不宣称逐行穷尽所有插件。

对照设计：024 V3、025 V4、026 E1/F1/C1/C2/E2/E3/F3及工单；并检查013已有日志、诊断、数据根、命令合同，避免把已有设计重报为遗漏。

## 第一性原理判据

1. 核心存在的理由是给不同参与者提供稳定的共同环境，不是汇总所有业务。
2. 不理解某个资源的字段仍能定义的机制，且涉及跨参与者一致性/安全/生命周期，才是核心基础设施候选。
3. 公共实现可复用，不等于必须有一个中央权威。排序、JSON编码、原子文件写等通常是无状态库；模型选择、配置合成、内容保留规则是业务。
4. 去掉Agent/Chat/Profile，环境仍须能成立。必须出现这些名词才能解释的责任不进内核。
5. “核心”区分治理内核和平台服务。Pacthold管理准入与关系；OS存取、数据库引擎和UI呈现由适配底座提供。端口由同Environment管理，不另建生命周期核心。
6. 有框架名词不等于合同完整：必须能回答所有者、身份、版本、撤销、竞态、未知和缺席行为。

## A. 已设计：只应迁移/落实，不再次扩张核心

| 当前机制 | 应归哪里 | 已有设计证据 | 结论 |
| --- | --- | --- | --- |
| Server宿主激活、依赖、贡献事务、hold；旧/new Core及compat注册 | 同一Pacthold Environment | 024 inventory；026 E1/E2、004/006、E3 | 已设计未迁，不新建管理器 |
| 插件互相通过ports/裸服务、自己收订阅与卸载引用 | Environment受管理Binding/Usage；前端本地scope由F1 | E3/F3 §2/4/5/6 | R3已补，不重复报遗漏 |
| Profile selection/glue与model next-turn保存pending/confirmed/route | Agent唯一领域owner | 025 V4/state-ownership；026010/C1/E2 | 属业务收束，不进Pacthold |
| connector的sessionList/runs/interactions/firstSend | Agent Session/Run/Interaction/Submission owner；connector保传输关联 | E2状态迁移表；010 | 已设计；不能把整connector搬进核心 |
| `plugins/agent/connections`内连接句柄、退役订阅与release跟踪 | 通用连接事实归connections/runtime，Agent事实归Agent | 025 I17/V4、026008/009及E3 | 已设计分层，不可整体提升 |
| 各资源的品牌配置适配 | Harness内部 | M08、007与migration-map | 领域适配迁移，不是核心能力遗漏 |
| Chat/API的通用注册、scope撤销、组件绑定 | extension-api/runtime/ui-components的通用原语 | F1、现Contributions、ui-components；E3 | 基础设施已设计；Chat slots/queryKey仍业务 |
| 设置/导航/浮层/焦点注册与宿主第二设置数组 | Workbench唯一组织入口 | 025 I13/I14、026008/F1 | 已设计，设置值仍资源插件持有 |
| `plugins/commands`注册与调用 | 可使用前端平台通用命令服务；handlers归插件 | 013 C07、025 V4、026架构 | 非遗漏；026当前允许旧命令插件入口，最新组织提案需另同步决定，不靠挪目录制造新命令引擎 |
| 请求占位、重复调用、未知结果与恢复 | Environment投递事实；业务结果归owner | C1/C2/E1及005/011 | 已设计；资源CRUD事务回执不必全部吞入环境execution账 |
| authenticated principal、调用scope与代次检查 | 统一CallContext/Policy入口 | 024 V3、E1/E3 | Skills当前常量/路径身份须迁移，是设计已有，不再造身份系统 |
| 日志sink、脱敏、诊断导出 | 前后端平台适配服务 | 013 C04/C06、025 V4§流/错误；extension-host已有实现 | 不算整体漏设计；迁后注入/公开合同映射仍须细化 |

源码锚点：`plugins/commands/src/entry.ts:4`、`plugins/chat/api/src/registry.ts:23,129,193`、`plugins/agent/connections/src/workspace.ts:20–47,114–136`、`packages/desktop-platform/extension-api/src/contributions.ts:5`、`extension-host/src/services/commands.ts:1`、`logging.ts:1`、`diagnostics.ts:1`。它们证明机制存在，不证明所有消费者已接线。

## B. 真正遗漏1：插件持久数据空间的公开合同

证据：Skills build从共享data_root拼`skills-v2`，并把物理路径当server_scope（`plugins/assets/skills/src/ordessa_skills/plugin.py:144–159`）；Profile自行创建连接/迁移（`plugins/profile/src/ordessa_profile/storage.py:172–235`）；Subagents自拼定义/版本/receipt路径（`plugins/assets/subagents/src/ordessa_assets_subagents/store.py:36–112`）。

已有C01规定产品数据根，005规定环境StorePort；两者均没有完整定义“一个外部插件如何取得自己的持久数据空间”。业务领域库独立合理，但裸全局data_root/database并不是清晰的外部SDK边界。

应补：公开的受管理数据空间能力，包含稳定插件/领域namespace、数据归属、访问范围、兼容版本、运行句柄与关闭/停用关系；迁移由资源owner提供方案，平台组织排他准入、备份/许可与失败记录。卸载插件默认保留数据，不等于purge；数据空间的删除需要显式授权。默认路径与现有磁盘标识不变，使用映射而非自动重命名。

核心不补：通用业务ORM、所有插件共用一张业务表、统一归档规则、把插件schema迁移当内核schema。SQLite/文件/外部存储是适配实现，可选；独立插件不能因此强依赖SQLite。文件目录授予对受信插件只是边界合同，不是恶意同进程代码隔离。

反例：插件A写B的数据；A卸载删数据；重装换目录导致“数据丢失”；旧二进制打开更新schema继续写；缺存储端口仍宣称持久成功。应拒绝对应保证/操作，不影响纯内存能力。

额外发现：Subagents `replace_definition`读row_version后原子替换文件（81–99），原子替换本身不能证明跨进程CAS。此处是需验证的实现风险，不凭此断言当前产品有并发故障，也不因此要求将该业务整体搬到内核。

## C. 真正遗漏2：持久资源引用关系的登记与完整性

证据：`plugins/assets/model-provider/profile-contribution/src/ordessa_model_provider_profile/reference_port.py:29–54`递归扫描Profile payload中的providerId/modelId；`server/.../catalog.py:119–130`先查引用、再archive。其设计天然偏向“Profile是引用者”，新引用方需新的扫描/聚合。

已有ObjectRef/Usage/资源dependency提到了被使用资源不能破坏性删除，但没有完整冻结“保存的资源引用”与“运行中借用”的差别。E3主要管activation、UI、Activity关系；Profile保存的引用即使两个插件停用仍存在，不能随scope释放。因此这是关系合同的遗漏，不是再造引用核心。

应补：在同一Environment关系体系内声明持久关联（sourceRef+sourceRevision、targetRef+可选固定targetRevision、来源owner、关系性质与完整性证据），公开反查与变更准入。核心不深扫JSON，不理解providerId/modelId；源插件报告关联，目标插件决定它的删除/归档语义。

必须补竞态：不能先query“无引用”再无保护delete。需在同一关系准入下取得删除/变更reservation并拒新冲突关联，或声明仅观察保证并拒需要强保证的操作。跨插件业务库与关系Store不假装同事务：用提交意图/确认/恢复合同；写业务成功但登记未知时标完整性未知，不能宣称无引用。

静态持久引用、运行Usage和纯历史关联不同；核心不能自动认定某条引用应阻归档。归档可只禁新使用还是会破坏解析由资源owner定义；是否阻塞由明确合同决定。插件卸载不擦持久引用；索引不完整时不能空列表假安全。

反例：停Profile后Provider误判无引用；新资源插件引用Provider但不在扫描名单；query和archive之间保存新Profile；关系登记失败却显示“可安全删除”。

## D. 真正遗漏3：宿主交互的类型化能力与生命周期

证据：Chat目录选择使用`globalThis.projectDirectory`（`plugins/chat/frontend/src/views/project-dialog.tsx:77–83`），入口由preload/main硬编码`projects:choose-directory`；Profile用`window.confirm`（`plugins/profile/frontend/src/settings-view.tsx:67`）。它们绕公开PluginContext取得宿主交互。

已有F1提供overlay/settings，009提供native broker与能力检查；但“文件/目录选择、普通确认、复制/打开”的公共交互合同尚未明确。这是现有broker/Workbench设计中的遗漏，不意味着新增全局UI核心。

应补：由Workbench/前端API暴露普通dialog/confirmation，用同UI scope与来源信息管理；OS选择器/clipboard/外链由native-bridge受限能力实现。请求带调用插件、作用域、操作ID；取消/缺席/撤销/失败分别返回。停用期间晚到选择结果不得触发业务写入。用户选路径仅证明选择，不自动授权所有插件或Agent访问；后续资源导入/项目注册走领域能力。

业务不迁：项目目录列表、资源导入规则、提示文案与Profile影响判断。普通确认不是Harness原生审批，也不能充当权限提升凭证。宿主原生窗口API留Electron实现，不进Pacthold。

反例：插件卸载后系统对话框返回仍注册项目；依赖全局变量使无Chat的插件无法选择目录；取消当失败或触发后端写；普通confirm结果变工具审批/访问授权。

## E. 部分已设计但合同不完整：秘密与诊断，不算从零遗漏

### E1 秘密存取

SecretStore已存在（`packages/pacthold/src/pacthold/storage/secrets.py:19–22`），model-provider显式注入secret_store，C2/024声明可信secret/fingerprint port；不能说没有设计。缺口是跨插件公开的owner/access/revision/revoke/删除责任，以及OS实现该归哪层。裸locator read不是最终外部SDK合同。

建议补齐同Environment授权的秘密能力合同，资源插件管理用途与引用，OS keyring/DPAPI具体实现归平台适配，Pacthold不实现账号登录/刷新/token格式。凭据被哪些持久对象引用，可复用C类关系。此为既有port合同细化，不新增账号或vault内核。P树本轮相关文件定位并未发现可据此宣称完整Linux密钥环闭环的证据，不沿用历史聊天证明现能力。

### E2 错误与诊断

013已设计C04/C06、extension-host已实现日志/诊断服务，025有有界错误与脱敏。Prompts自己的日志门（`plugins/assets/prompts/src/ordessa_prompts/backend/service.py:49–61`）是业务内容敏感规则，不应原样抽进核心。平台可以统一事件关联/来源/脱敏sink，业务仍声明敏感内容。

需在迁移清单明确Logger/DiagnosticProvider经scope公开注入、跨前后端关联ID以及不能把错误字符串当未知投递证据；目前不能列成“缺一整套诊断系统”。不新建另一个结果/审计主账。

## F. 应保留在插件或无状态库，不能误收进核心

- Profile预设、字段覆盖及资源facet的业务描述；会话配置合成归Agent，不归Pacthold。
- Provider目录、模型资格、协议兼容、原生登录/刷新；品牌差异归Harness。
- Skill/Prompt/Subagent/命令模板的内容版本、选择、赋值、克隆与归档规则。
- Hooks/原生插件安全扫描与批准规则；`ordessa_extensions.HookLoader`是Hook业务加载，不是平台extension loader。
- Sandbox/Permissions策略规则；核心只调用PolicyPort、管理通用准入，不能重建原生审批。
- Chat特定slots、输入搜索queryKey、消息/工具renderer；平台只提供通用贡献/组件/surface。
- 全部React state不必中央化；dirty表单、弹层开关、搜索词是合法UI局部状态。
- 原子文件写、排序、受限JSON读取、纯codec可以复用库；复用不代表持有中央状态或强制所有插件用同存储引擎。

## 建议下一步（尚未执行）

只补B/C/D三个真实缺口；E只细化已有合同与迁移清单。不要新建包/总线/管理器来“承接”：B沿现持久端口与平台适配，C扩充E3同关系模型，D扩充F1与native-bridge。新增场景须进入工单/验收，再做针对边界和竞态的审查。

本轮仅本审计报告写入，未修订上述候选为批准的实现合同、未改产品源码、未跑产品测试、未读凭据/数据根、未重启服务或调用真实模型。

## 后续设计记录：R4

上述“尚未执行”描述审计时点，不代表当前方案包状态。用户随后要求全部补齐：B/D/E细化进入contracts/platform-services.md，C扩展同Environment关系合同contracts/resource-references.md；Agent单一状态权威进入contracts/agent-domain.md，领域插件布局进入plugin-architecture.md。新增18项任务和20项验收场景，未执行产品迁移。

R4提出的backend/platform-services只封装可替换的文件/OS秘密/诊断适配，不接管Environment、插件激活或持久业务主账；这不是本审计禁止的新管理核心。004的关系准入是005持久关系实现的明确前置条件。R4通过结构校验，尚未经过独立攻击复审或生产验证。
