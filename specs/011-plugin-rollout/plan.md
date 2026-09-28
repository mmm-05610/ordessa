# Plan：文件所有权、基线收口与集成顺序

## 固定输入（只读）
| 旧树 | 取材提交 | 状态/用途 |
| --- | --- | --- |
| platform-plan | `e406625d9a2c1803bd2d231cba3fbf4b555fd75b` | Spec Kit 工具、宪章、010 规格输入 |
| platform-pacthold | `9e33a4df5120645de0bb8c492a8b7610adf5a9bb` | 已报 REVIEW_READY；stop unknown 释放 OWN lease 有登记缺口 |
| platform-server | `903a67e9bec8ed55504c16fb6fd62af4e5d1f678` | 仍 IN_PROGRESS；只消费提交，未跟踪测试不复制 |
| platform-frontend | `82b7ef1fc3fc79037b7a6d4749b612d4f54865fd` | C7/C8 已报交付，需集成复验 |
| workbench-sidebar | `2b22e1608f934d1810f4a09f626f46e9e36b2d1e` | 已提交侧栏交付；6 PNG 与生成 lock 脏项保留原树 |
| plugin-profile-impl | `b77f9f23cba0073f968ade1b613d27c31ad13d0b` | Profile 旧实现，只读择取 |
| plugin-model-provider-impl | `9305563719d25e04076b9221a7284660bd8f8642` | 模型旧实现 PARTIAL，只读择取 |
| plugin-assets-skills-impl | `752f148b1b01f58c0d090e79728948127173f9fb` | Skills 旧实现，只读择取 |
| desktop-workbench | `36fefc50d348ec924f840a0118cf78093f51dba7` | 历史 Chat 成果，按符号/测试择取，不整支硬并 |

旧树后续新提交不是自动批准输入。C0 可复核其明确发布的完成检查点再择取并记录 SHA；不得读取未提交文件作为交付。**platform-server 仍由原会话收尾：本批仅只读观察其已提交报告，不改它的文件/任务/进程，不接管其未完成项。** 当前 B SHA 是研究快照，不能直接发布为最终 foundation。Server 已合入 Pacthold 实现 b47b6d7803；检查 ancestry，避免重复 cherry-pick。

## C0 的起步阶段
1. 在本树记录各冻结输入的 ancestry、diff、测试/数据迁移账。可先审核 A、前端 C、侧栏，准备 Harness 纯契约/能力探针/反例和迁移表。B 未发布最终检查点前，不接管其收尾、不为催进度修改原树；只读已提交报告识别依赖。B 明确发布完成提交后，记录新的完整 SHA，按 010 规格在 C0 本树集成 Server（已含 A）、A 后续必要提交、前端 C、侧栏；源码冲突派给对应单包子代理。不得丢弃 main 已有 Claude 官方 ACP 替换成果。
2. 核实 A 登记的 stop 抛错/未知后 OWN lease 释放。执行器仍可能运行时保留所需租约，待可证停止或安全对账后收尾；不能制造 cancelled。保留原失败原因与 cleanup 事实，补可抓到不安全释放的反例。若资源确可安全独立释放，须逐类证据，不能一律释放。
3. 在 B 收尾交接后核实其登记的旧库缺历史迁移 provider 仍打开并升级 marker 问题是否已修复。若仍有缺口，C0 在自己的树补反例并修复：对需要该迁移链的旧数据根，在任何 schema/marker 写入前类型化拒绝，负例断言原库字节/版本不变；完整 provider 装配保持兼容。只用合成数据库，实际用户数据迁移不在本轮。
4. 依据 B 最终交付验收 T016/T023/T024；只修交接后确认仍未满足的集成项。报告中 68→67 旧红变化按具名原因核对，不能套用历史固定数。C7/C8 与侧栏跑合成后的样式、键盘、根聚合、typecheck/build/smoke。B 未交接时继续本线可独立工作，不发布假 foundation。新树独立环境与隔离 wheel 门通过后发布 foundation。
5. 继续 Harness v2 API/注册/应用/生命周期与唯一 ACP owner；发布 harness-api，不等待所有业务提供者完成。品牌内容编译由业务域负责。本线提供真实目标句柄/动作、控制接缝和统一 conformance fixtures。
6. 各线交付后串行合入 C0 树，重算产品装配与生成锁，跑跨包生产链。这里的本地集成获得授权；合并 main/push 仍不执行。

## 每线所有者
| 线 | 可修改的业务面 | 说明 |
| --- | --- | --- |
| C0 | `plugins/harness/**`、`plugins/connectors/acp/**`、`plugins/connectors/ordessa/**`、`新增 Harness 领域 API 发行包（按 harness-v2 T03 冻结位置）` | 先审核 A/C 平台与侧栏，准备 Harness 独立工作；platform-server 由原会话收尾，等其提交交接后才集成 B 并验收剩余缺口。发布 foundation/harness-api，统一 ACP 配置、附件、命令、执行前授权与提交闸门，最后串行整合业务线。 |
| Z1 | `plugins/profile/**` | 只拥有 Profile 的轻量 API、配置面、存储、覆盖、管理 UI 和 Profile 自己的 Chat glue。复用旧 profile 实现；其他领域的 Profile glue 由该领域写。 |
| Z2 | `plugins/chat/**`、`经迁移表证明属于 Chat 的 plugins/agent/conversation/**`、`Chat 领域轻量 API（位置先对齐现有契约）` | 复用 ZCode 正文/思考/紧凑工具展示；项目弹窗、项目内草稿、共享 +/斜杠菜单、附件贯通。前端 ACP/Ordessa 会话服务由 C0 写，本线提 DTO 和反例。旧 plugins/agent/sessions 只读盘点，是否迁移由 C0 统一裁决。 |
| Z3 | `plugins/assets/model-provider/**`、`旧 plugins/model-provider/** 的本域保真迁移` | 优先复用旧部分实现与反例；Provider/Model 原子选择，下轮应用，双会话隔离，必要时重启并 resume 同一原生会话。拥有本域品牌 adapter 与 Profile/Chat glue。 |
| Q1 | `plugins/assets/skills/**` | 沿用旧 Skills 部分实现；内容版本、用户/项目/Harness/Profile 分配、固定批准版本、品牌装载、独立 Settings 与可选 glue。 |
| Q2 | `plugins/assets/prompts/**`、`plugins/assets/command-templates/**` | 两个独立域可派两个单包子代理。Prompts 默认跟随正文修订、提交时冻结；模板引用固定批准版本，展开到可编辑用户草稿且不自动发送；不要强行统一二者版本语义。 |
| Q3 | `plugins/assets/subagents/**` | 只拥有角色定义、版本、分配和配置 adapter；不迁入外层派工/通信/恢复。Pi 受审 extension-backed 入口由 C0 承载运行，只在有证据后开放。 |
| Q4 | `plugins/assets/mcp/**` | native/managed 唯一连接/关闭 owner，工具目录与授权分离。定义/目录可先做；实际工具调用必须等真实 Permissions 授权接线，不默认放行。Pi 桥的本域组件由本线写，runtime 装载由 C0 提供。 |
| Q5 | `plugins/permissions/**`、`plugins/assets/sandbox/**` | 两个业务所有者，分别派单包子代理。Permissions 管上限/审批/授权，Sandbox 只管 Harness 原生隔离。先发布 permissions-api；真实工具副作用前接缝由 C0 实现，本线用正反例验证。 |

C0 另独占：`products/**`、根 `package.json/package-lock.json`、`tooling/**` 的共享接线，以及 `server-compat` 的公共 composition/core_wire/plugin 注册表删除与所有领域迁移收尾。为完成既有 010 规格，C0 可通过单包子代理修 `packages/pacthold`、`packages/server-plugin-api`、`apps/server`、前端平台/Workbench 的集成缺陷；不追加未设计的核心能力。进入 foundation 后需新增中性接口时先给出明确需求和反例，不塞业务分支。

各业务线可读取 legacy 模块、在自己新包中保真迁入代码，但不要提交 shared compat 删除。在自己的 `integration-request.md` 列待删旧文件、旧 writer/路由、调用方、迁移与目标。C0 集成时完成唯一 owner 替换。领域分支可报“本域验证完成”，全产品完成必须等公共旧 writer 退出。

## 覆盖原包交叉写入条款
- Harness T10/T11 的模型/Skills 业务代码归 Z3/Q1；Profile glue 归 Z1/各提供者。C0 只做平台接缝与集成验证。
- Profile P3/P5 的 Harness/模型/Skills 写入分别归 C0/Z3/Q1；Z1 通过公开 API 消费。
- Chat S1 的 `connectors/acp`、`connectors/ordessa` 改动归 C0；Z2 先提供所需 DTO/协议反例，并使用 C0 的真实发布。
- MCP/Safety 的 ACP 控制接线归 C0；自家配置 adapter、服务与 glue 归 Q4/Q5。Q5 先发布权限接口，C0 接执行前门，Q4 再接受管 tools/call。
- 已完成 Workbench/UI 包由 C0 复验择取；不恢复撤销的统一 agent-ui 方案。

## 构建与 git
每树自己安装依赖。现有 `plugins/**` workspace glob 可发现业务包，各域只声明本包依赖。验证期间可由 npm 生成本树临时根锁变化，导出检查点前保存所需依赖增量到 integration-request 并仅清理本线确定生成的锁变化；用户或其他执行者的改动不可覆盖。最终根锁仅 C0 生成并提交。

公共设计/specs/010 为只读；各线只改自己 feature 的 tasks、reports、api-requests、integration-request 和 source package 文档。消费兄弟提交引入其代码是经授权的集成，不等于有权手改其业务。出现源码冲突先确认 owner；若无法机械解决，向对应 owner 留精确请求，不挑一边整文件覆盖。
