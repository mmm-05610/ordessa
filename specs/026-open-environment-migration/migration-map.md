# 迁移去向与具体消费者

本表是001/002需重新核实的实施映射，不宣称P已经集成。物理移动保持发行名；新包的名称在002冻结。

| 当前路径/机制 | 目标 | 工单 / 具体消费者 |
| --- | --- | --- |
| packages/desktop-platform/extension-api | packages/frontend/extension-api | 008；所有extension与app imports/exports |
| extension-loader + extension-host | frontend/extension-runtime | 008；apps/desktop renderer/main protocol、enabled discovery |
| contracts/foundation | frontend/contracts | 008；tooling/vitest-extensions.mjs、products token guards、shared import map |
| foundation内HarnessAvailability | plugins/harness/contracts公开域carrier；混合逻辑会话字段拆到Agent | 002/008；逐字段所有者、旧消费者/Token兼容映射，不平台重导出业务 |
| packages/workbench | frontend/workbench | 008；API、tests/token-scan、product-bundles和contract-ownership引用 |
| ui/ui-components/connections/native-bridge/server-bridge | frontend对应包 | 008/009；package exports、app main/preload、所有connector |
| packages/pacthold | backend/pacthold | 006；pyproject、editable installs、PYTHONPATH、test roots、deb wheel |
| packages/server-plugin-api | backend/server-plugin-api | 006；Server/plugin imports保持server_plugin_api名 |
| CoreStore具体SQLite | backend/persistence-sqlite | 005；products/server注入、旧构造消费者兼容桥 |
| ServerPluginHost通用state | backend/pacthold | 004/006；stage/commit/holds、CoreBinding、extensions bootstrap |
| bootstrap/core_binding/global core_db | apps/server薄入口 | 006；全部入口只同Environment，无module singleton |
| apps/desktop host settings/overlay | frontend/workbench | 008；设置值owner不迁，窗口frame controls不受overlay阻挡 |
| ACP host导入apps/desktop/renderer/agent-native | frontend公开bridge contract | 008；plugins/connectors/acp/src/host.ts禁止private app import |
| Profile selection/glue | Profile操作源 + Agent domain owner | 010；现private selections/bindings/retained/clickQueues退出主写 |
| model next-turn-client/chat-api-entry | model操作源 + Agent domain owner | 010；queued/current/pending/route不独立writer |
| Chat DraftStore/send页面 | stable DraftOwner + SubmissionOwner | 010/011；精确revision消费、view外收尾 |
| native-session history M/P | Harness历史owner/decoder | 007/011；启动list、点击load，不把native locator当invoke权 |
| plugins/assets各资源及品牌adapters | 顶层领域插件；品牌实现→Harness内部 | R4 plugin-architecture.md映射；007/010逐所有者，保所有现支持品牌与资产 |
| plugins/server-compat与runtime-compat | legacy-compat/server与runtime的有界兼容入口 | 006/012保持两套既有发行ID但不保持两核心；业务迁owner |
| plugins/commands通用registry | frontend/extension-runtime | 008；旧extension入口forward同服务，handler不迁平台 |
| 插件裸data_root/database与自拼目录 | E4 DataAreaPort，领域Repository留插件 | 005/007；稳定namespace映射、许可/兼容迁移，真实数据未授权不动 |
| ProfileViewReferencePort深扫Profile | E5持久资源关联声明 | 004/005/007；源owner登记版本关联，完整性未知拒破坏性操作 |
| SecretStore OS实现与注入 | backend/platform-services + 环境受管理SecretPort | 005/006；MAC合同保留，不把Provider/登录业务搬核心 |
| globalThis.projectDirectory/window.confirm | Workbench公开dialog + native-bridge受限选择能力 | 009；撤销/late/取消与访问授权分离 |
| 日志/诊断sink与provider注入 | E4/F4受管理平台能力 | 008/009；复用013，不新建执行结果账 |

完整插件结构及逐路径拆分以plugin-architecture.md为R4权威；001/002重新核实实际消费者和身份，不能只搬package.json。目录变化不自动授权实体重命名、用户数据迁移或新资源业务。

## 构建与交付路径（不可漏）

002建立合同构建与测试接线，008/006迁路径时更新：root package.json/package-lock/workspace patterns；每包package.json/pyproject/exports；products/desktop extensions.json/extensions.lock；app包build/typecheck脚本；tooling/build-all.mjs扫描根；tooling/test-all.mjs发现；tooling/vitest-extensions.mjs shared carrier alias；packaging/build-deb.mjs wheel列表；scripts/start-server.sh的PYTHONPATH；scripts/verify-clean.sh editable/test roots；.github/workflows/ci.yml安装/JS/Python suite列表；文档命令引用。

必须从源码检查以上文件与所有rg命中，不能只改显式表。守卫扫描根也要迁移，并保minimum scanned sources与故意注入反向import/第二Token的正命中；迁后零发现不能绿。

## 资源适配清单（007逐项登记，不无限新增功能）

| 现有域 | 应检查的接缝 | 成功范围 |
| --- | --- | --- |
| model-provider | server、desktop、chat/profile contribution、adapters | 模型/供应商域与品牌应用归Harness，不复制business |
| skills | contracts、desktop、backend、native来源 | 系统/项目作用域与启用资源声明保语义 |
| mcp | backend、frontend、adapters/pi | owned/borrowed服务绑定与动态目录 |
| prompts / memory / runtime-preferences | 资源与facet、原生应用 | 内容/偏好域；Harness声明支持，否则unsupported |
| lsp | api/adapters | 服务归属与使用关系，不核心理解LSP |
| sandbox / permissions | api/backend/frontend/adapters | 原生内置审批不改；已有外部策略仍独立注入 |
| subagents / command-templates / extensions | 目录/定义/执行资源 | 不把本轮变成协作业务或新marketplace |
| workspace / server-compat / runtime-compat | 历史/资源与旧入口 | 旧数据只读或有限forwarder，无复活worker |

每项需 capability-migration row：来源、当前实际可用状态、public descriptor、Harness负责的适配、所有者、退出责任、迁后受控case、缺能力行为。未接线功能保持明确未支持，不为“完整迁移”发明新业务；已经接线行为不得丢。清空某域测试或清单不算迁移完成。
