# R6 — 兼容实现拆解与本轮退役要求

## 结论与证据边界

用户2026-10-03确认：不将legacy-compat列为永久业务插件，本轮仔细梳理并处理。依据准备实施树固定提交 `8d4bc64bb747ee5ab000038ad31bb2c5d8b41b36`，不是主树较旧源码；只修订方案，未修改产品实现。
静态扫描1349个受控Python文件，两包99个Python模块、9份封存SQL，179个包外静态引用文件（包含测试，不等于179个生产消费者）。
逐文件路径/顶层符号/直接绝对import消费者见[扫描清单](evidence/compat-inventory.json)。这是AST盘点＋承重文件源码核查，不声称每个函数语义或运行路径均已验证。
AST不能穷尽相对import、字符串/dynamic import、entrypoint、HTTP方法、npm调用、脚本/安装/文档消费者；002必须补齐这些并签署完整消费者清单，零静态import不是可删除证明。

## 1. 哪些已确定，不应再交给执行者自由发挥

1. compatibility是迁移边界，不是领域。最终插件目标树取消legacy-compat；不将两包整体搬入它。
2. 中性机制只进同Pacthold/后端底座；有品牌、Profile、模型、Agent会话语义的实现回所属领域。包名带runtime不代表内核。
3. 发行/import/extension/旧route ID按M07保持。必要旧模块可留原发行单元中的薄alias/forwarder，但没有自有数据库、进程、注册器、配置store、队列或终态主写。
4. 活跃源码、默认products装配、构建依赖切至新公开合同；旧发行留壳不是允许新代码继续依赖旧业务包。外部兼容期限未有证据不强删公开ID。
5. 已有可用行为不能用typed unavailable掩盖删除；unsupported只用于原本未支持范围或真实provider缺席。碰到无法同时保行为/单owner的语义冲突，报告具体决定，不能复制第二套。
6. 旧运行闭包按C2退出，不复活legacy worker处理新请求；历史未知记录保持未知，不重发、不批量改完成。
7. 旧数据和迁移链不是旧业务核心。封存SQL保字节、顺序、namespace、版本表和表标识；本轮只在fixture测试，不授权真实库迁移。

## 2. 必须拆开的承重接缝

| 接缝 | 源码事实 | 本轮具体处理 |
| --- | --- | --- |
| ServerCompatPlugin | 创建Profile/Provider/Session、资产、Hooks、账号、队列等并发布大量ports；启动创建native Profile，seal interrupted turns | 各域创建自己服务；产品仅注入；native启动不得以自动Profile作为必选基础；seal只能按C2事实处理，不能重启即写终态 |
| composition.py | 同模块装配原生、sidecar、保护目录、runtime资产等 | 产品选择入口留products；原生配置/目录/进程资产入Harness；中性访问和生命周期进Pacthold，不复制装配根 |
| core_wire.py/http.py | 汇集Profile、模型、账号、资产、会话等处理 | transport与auth/origin保持；业务方法由领域公开能力发布，旧wire只映射同能力、revision和错误；无第二CoreWireHandlers业务实例 |
| storage/database.py | 一个Database文件内嵌server_profiles/server_sessions/server_provider_models等产品schema，PRODUCT_SCHEMA_VERSION=21 | 通用事务/连接机制与领域schema拆开；历史链显式产品装配，禁止把整段业务DDL搬进Pacthold；保旧库标识及跨表fixture一致性 |
| runtime API/catalog/bootstrap | ProfileEnvelope及业务PluginRegistration扩展；四类业务贡献kind；seed业务合同 | 中性扩展机制进Environment；业务合同由对应域公开注册；同类型对象/同Env，不另建ProductCatalog生命周期 |
| capability/* | SandboxRequirement/Grant、授权匹配及sidecar需求/slots | 环境隔离/权限业务归sandbox/permissions；通用访问机制用核心，不能把业务capability枚举写进核心 |
| execution_contract/first_run_lock | 现已从pacthold.execution重导出同对象 | 不重复迁实现；旧导入identity测试继续保留；002核查目标execution语义，不把存在alias判成旧核心在运行 |
| profiles/subagents与execution/delegation | 既有父子会话、限制、执行编排 | 保已存在的用户可用行为，拆Agent逻辑/Harness原生/权限资源；022/023新协作机制不在本轮，不因此把旧通用调度升格核心 |

## 3. 逐模块目标归属

表中“拆分”意味着逐符号迁，不得整个文件copy。消费者数量为扫描到的直接绝对Python引用文件数，包含包内与测试；聚合入口和动态引用另查。没有引用不能直接删除。

| 源模块 | 目标处理 | 直接引用文件数 |
| --- | --- | --- |
| `plugins/server-compat/src/ordessa_server_compat/accounts/__init__.py` (13行) | Harness：账号/原生登录/认证资产；秘密仅引用平台SecretPort | 0 |
| `plugins/server-compat/src/ordessa_server_compat/accounts/assets.py` (218行) | Harness：账号/原生登录/认证资产；秘密仅引用平台SecretPort | 3 |
| `plugins/server-compat/src/ordessa_server_compat/accounts/login_engine.py` (204行) | Harness：账号/原生登录/认证资产；秘密仅引用平台SecretPort | 1 |
| `plugins/server-compat/src/ordessa_server_compat/accounts/records.py` (111行) | Harness：账号/原生登录/认证资产；秘密仅引用平台SecretPort | 4 |
| `plugins/server-compat/src/ordessa_server_compat/approvals/__init__.py` (4行) | Agent交互记录；外部权限规则归permissions，原生审批只转交Harness | 2 |
| `plugins/server-compat/src/ordessa_server_compat/approvals/records.py` (206行) | Agent交互记录；外部权限规则归permissions，原生审批只转交Harness | 3 |
| `plugins/server-compat/src/ordessa_server_compat/assets/__init__.py` (7行) | 按资源域拆目录/记录/内容；公共IO用DataArea，不设总资产业务owner | 6 |
| `plugins/server-compat/src/ordessa_server_compat/assets/catalog.py` (223行) | 按资源域拆目录/记录/内容；公共IO用DataArea，不设总资产业务owner | 2 |
| `plugins/server-compat/src/ordessa_server_compat/assets/mcp.py` (172行) | MCP资源/探测归mcp；品牌应用归Harness | 11 |
| `plugins/server-compat/src/ordessa_server_compat/assets/mcp_probe.py` (130行) | MCP资源/探测归mcp；品牌应用归Harness | 3 |
| `plugins/server-compat/src/ordessa_server_compat/assets/plugins.py` (108行) | extensions原生扩展资源（不是Ordessa插件loader） | 2 |
| `plugins/server-compat/src/ordessa_server_compat/assets/records.py` (230行) | 按资源域拆目录/记录/内容；公共IO用DataArea，不设总资产业务owner | 4 |
| `plugins/server-compat/src/ordessa_server_compat/assets/rendering.py` (126行) | Harness品牌资源渲染；不留在MCP资源业务 | 2 |
| `plugins/server-compat/src/ordessa_server_compat/assets/skills.py` (173行) | skills资源管理；品牌应用归Harness | 2 |
| `plugins/server-compat/src/ordessa_server_compat/composition.py` (1488行) | 拆装配至products/server与各领域entry；旧入口仅转发同Environment | 22 |
| `plugins/server-compat/src/ordessa_server_compat/core_wire.py` (1865行) | 通用wire→Server；业务handler/DTO/校验/错误→对应领域；旧route仅薄映射 | 10 |
| `plugins/server-compat/src/ordessa_server_compat/credential_cli.py` (58行) | CLI入口保旧命令；秘密操作交公开SecretPort/所属资源业务 | 0 |
| `plugins/server-compat/src/ordessa_server_compat/error_families.py` (69行) | 通用wire→Server；业务handler/DTO/校验/错误→对应领域；旧route仅薄映射 | 5 |
| `plugins/server-compat/src/ordessa_server_compat/execution/__init__.py` (159行) | Harness原生实例/进程/原生目录/运行适配；治理准入/生命周期统一Pacthold | 45 |
| `plugins/server-compat/src/ordessa_server_compat/execution/artifact_store.py` (184行) | Harness可验证原生资产；底层文件IO复用平台，未确认通用化不进核心 | 3 |
| `plugins/server-compat/src/ordessa_server_compat/execution/change_set.py` (201行) | workspace变更资源；Harness仅提供原生运行关联 | 2 |
| `plugins/server-compat/src/ordessa_server_compat/execution/control_plane_sync.py` (233行) | Harness原生实例/进程/原生目录/运行适配；治理准入/生命周期统一Pacthold | 1 |
| `plugins/server-compat/src/ordessa_server_compat/execution/delegation.py` (591行) | 拆到Agent既有父子会话业务/Harness原生执行/permissions；不重启旧调度器 | 12 |
| `plugins/server-compat/src/ordessa_server_compat/execution/execution_contract.py` (23行) | 现已薄re-export：保同对象；检查旧API的目标语义，不复制实现 | 4 |
| `plugins/server-compat/src/ordessa_server_compat/execution/first_run_lock.py` (20行) | 现已薄re-export：保同对象；检查旧API的目标语义，不复制实现 | 2 |
| `plugins/server-compat/src/ordessa_server_compat/execution/inventory.py` (95行) | Harness原生解析/实例清单；逻辑会话运行投影归Agent | 2 |
| `plugins/server-compat/src/ordessa_server_compat/execution/local_channel.py` (777行) | Harness原生实例/进程/原生目录/运行适配；治理准入/生命周期统一Pacthold | 2 |
| `plugins/server-compat/src/ordessa_server_compat/execution/placement.py` (74行) | Harness原生实例/进程/原生目录/运行适配；治理准入/生命周期统一Pacthold | 4 |
| `plugins/server-compat/src/ordessa_server_compat/execution/protocols.py` (26行) | model-provider协议合同，Harness消费公开合同；非核心协议枚举 | 2 |
| `plugins/server-compat/src/ordessa_server_compat/execution/session_store_guard.py` (90行) | Harness原生实例/进程/原生目录/运行适配；治理准入/生命周期统一Pacthold | 3 |
| `plugins/server-compat/src/ordessa_server_compat/execution/sidecar.py` (1783行) | Harness原生实例/进程/原生目录/运行适配；治理准入/生命周期统一Pacthold | 20 |
| `plugins/server-compat/src/ordessa_server_compat/execution/sidecar_backend.py` (1183行) | Harness原生实例/进程/原生目录/运行适配；治理准入/生命周期统一Pacthold | 19 |
| `plugins/server-compat/src/ordessa_server_compat/execution/state_capture.py` (138行) | Harness原生实例/进程/原生目录/运行适配；治理准入/生命周期统一Pacthold | 0 |
| `plugins/server-compat/src/ordessa_server_compat/execution/usage.py` (399行) | Harness原生解析/实例清单；逻辑会话运行投影归Agent | 4 |
| `plugins/server-compat/src/ordessa_server_compat/facade.py` (110行) | 移除跨领域总Service/Repository；必要旧公开门面仅持受管理公开客户端 | 2 |
| `plugins/server-compat/src/ordessa_server_compat/hooks/__init__.py` (8行) | extensions资源/触发记录；原生触发执行归Harness | 0 |
| `plugins/server-compat/src/ordessa_server_compat/hooks/model.py` (220行) | extensions通用定义＋Harness品牌schema/渲染拆分 | 4 |
| `plugins/server-compat/src/ordessa_server_compat/hooks/records.py` (174行) | extensions资源/触发记录；原生触发执行归Harness | 3 |
| `plugins/server-compat/src/ordessa_server_compat/hooks/rendering.py` (98行) | extensions通用定义＋Harness品牌schema/渲染拆分 | 2 |
| `plugins/server-compat/src/ordessa_server_compat/hooks/triggers.py` (138行) | extensions资源/触发记录；原生触发执行归Harness | 3 |
| `plugins/server-compat/src/ordessa_server_compat/http.py` (211行) | 通用wire→Server；业务handler/DTO/校验/错误→对应领域；旧route仅薄映射 | 1 |
| `plugins/server-compat/src/ordessa_server_compat/model_configs/__init__.py` (6行) | model-provider目录/协议事实/探测/Repository；不持会话配置 | 3 |
| `plugins/server-compat/src/ordessa_server_compat/model_configs/probe.py` (227行) | model-provider目录/协议事实/探测/Repository；不持会话配置 | 4 |
| `plugins/server-compat/src/ordessa_server_compat/model_configs/provider_protocols.py` (262行) | model-provider目录/协议事实/探测/Repository；不持会话配置 | 2 |
| `plugins/server-compat/src/ordessa_server_compat/model_configs/reasoning_knobs.py` (104行) | model-provider通用模型参数＋Harness原生映射拆分 | 1 |
| `plugins/server-compat/src/ordessa_server_compat/model_configs/repository.py` (161行) | model-provider目录/协议事实/探测/Repository；不持会话配置 | 6 |
| `plugins/server-compat/src/ordessa_server_compat/model_configs/service.py` (360行) | model-provider目录/协议事实/探测/Repository；不持会话配置 | 6 |
| `plugins/server-compat/src/ordessa_server_compat/persistence.py` (108行) | 移除跨领域总Service/Repository；必要旧公开门面仅持受管理公开客户端 | 3 |
| `plugins/server-compat/src/ordessa_server_compat/plugin.py` (509行) | 拆装配至products/server与各领域entry；旧入口仅转发同Environment | 6 |
| `plugins/server-compat/src/ordessa_server_compat/profiles/__init__.py` (5行) | Profile清单业务；实例/原生generation迁Harness，会话配置迁Agent | 22 |
| `plugins/server-compat/src/ordessa_server_compat/profiles/clone.py` (146行) | Profile清单业务；实例/原生generation迁Harness，会话配置迁Agent | 2 |
| `plugins/server-compat/src/ordessa_server_compat/profiles/memory.py` (103行) | memory资源＋Harness原生记忆路径适配拆分 | 2 |
| `plugins/server-compat/src/ordessa_server_compat/profiles/permissions.py` (187行) | permissions规则资源；不接管Harness内部工具判断 | 12 |
| `plugins/server-compat/src/ordessa_server_compat/profiles/posture_config.py` (358行) | permissions外部规则＋Harness品牌配置适配拆分 | 1 |
| `plugins/server-compat/src/ordessa_server_compat/profiles/posture_translation.py` (142行) | permissions外部规则＋Harness品牌配置适配拆分 | 2 |
| `plugins/server-compat/src/ordessa_server_compat/profiles/repository.py` (270行) | Profile清单业务；实例/原生generation迁Harness，会话配置迁Agent | 2 |
| `plugins/server-compat/src/ordessa_server_compat/profiles/service.py` (133行) | Profile清单业务；实例/原生generation迁Harness，会话配置迁Agent | 1 |
| `plugins/server-compat/src/ordessa_server_compat/profiles/subagents.py` (284行) | subagents定义＋Agent已有父子会话业务；不新增协作调度 | 9 |
| `plugins/server-compat/src/ordessa_server_compat/sessions/__init__.py` (11行) | Agent逻辑会话/提交/队列/记录；native恢复与native ID证据归Harness | 23 |
| `plugins/server-compat/src/ordessa_server_compat/sessions/queue.py` (229行) | Agent逻辑会话/提交/队列/记录；native恢复与native ID证据归Harness | 4 |
| `plugins/server-compat/src/ordessa_server_compat/sessions/repository.py` (1293行) | Agent逻辑会话/提交/队列/记录；native恢复与native ID证据归Harness | 5 |
| `plugins/server-compat/src/ordessa_server_compat/sessions/service.py` (424行) | Agent逻辑会话/提交/队列/记录；native恢复与native ID证据归Harness | 2 |
| `plugins/server-compat/src/ordessa_server_compat/usage_aggregate.py` (126行) | Agent逻辑运行用量投影；不成为核心模型计费业务 | 3 |
| `plugins/server-compat/src/ordessa_server_compat/wire_projection.py` (332行) | 通用wire→Server；业务handler/DTO/校验/错误→对应领域；旧route仅薄映射 | 7 |
| `plugins/server-compat/src/ordessa_server_compat/wire_validators.py` (97行) | 通用wire→Server；业务handler/DTO/校验/错误→对应领域；旧route仅薄映射 | 3 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/__init__.py` (12行) | 聚合__init__：领域公开入口或旧对象重导出，禁注册副作用 | 6 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/api.py` (191行) | 逐符号拆：中性机制→environment-api；Profile→Profile；native control/continuation→Harness | 4 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/bootstrap.py` (91行) | products/server显式组装同Environment；业务contract集合不可内置Pacthold | 3 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/capability/__init__.py` (125行) | 外部sandbox/permissions声明匹配业务；中性访问准入复用Pacthold，不能整体升格核心 | 11 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/capability/documents.py` (177行) | 外部sandbox/permissions声明匹配业务；中性访问准入复用Pacthold，不能整体升格核心 | 0 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/capability/errors.py` (83行) | 外部sandbox/permissions声明匹配业务；中性访问准入复用Pacthold，不能整体升格核心 | 4 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/capability/ids.py` (27行) | 外部sandbox/permissions声明匹配业务；中性访问准入复用Pacthold，不能整体升格核心 | 0 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/capability/match.py` (388行) | 外部sandbox/permissions声明匹配业务；中性访问准入复用Pacthold，不能整体升格核心 | 4 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/capability/requirements.py` (119行) | 外部sandbox/permissions声明匹配业务；中性访问准入复用Pacthold，不能整体升格核心 | 1 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/capability/selection.py` (160行) | 外部sandbox/permissions声明匹配业务；中性访问准入复用Pacthold，不能整体升格核心 | 2 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/capability/slots.py` (71行) | 外部sandbox/permissions声明匹配业务；中性访问准入复用Pacthold，不能整体升格核心 | 0 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/catalog.py` (201行) | 通用登记/查询→Pacthold；四类业务贡献→领域；无第二目录/激活器 | 1 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/cli/__init__.py` (147行) | apps/server或产品CLI入口，保原命令；内核只中性CLI机制 | 0 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/credentials.py` (49行) | 秘密载体→SecretPort；原生挂载/materializer→Harness | 1 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/legacy_migrations.py` (53行) | products/server的封存历史迁移注册；namespace/版本表/SQL摘要不变 | 7 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/profile_envelope.py` (115行) | Profile公开数据＋Harness原生引用边界拆分；非第二配置owner | 1 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/resource_contracts/__init__.py` (87行) | 领域公开合同分散所有；旧聚合模块仅别名/重导出同对象 | 32 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/resource_contracts/agent_box_profile_v1.py` (27行) | Profile资源合同，保旧contract ID | 1 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/resource_contracts/agent_skill_v1.py` (49行) | skills资源合同，保旧contract ID | 1 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/resource_contracts/credential_v1.py` (28行) | model-provider认证资源公开引用；原生消费由Harness，秘密值不进入合同 | 0 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/resource_contracts/harness_capabilities.py` (313行) | Harness能力/原生目录/资产；中性hash可复用平台但不搬品牌保护路径 | 10 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/resource_contracts/home_projection.py` (183行) | Harness能力/原生目录/资产；中性hash可复用平台但不搬品牌保护路径 | 1 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/resource_contracts/prompt_fragment_v1.py` (23行) | prompts资源合同，保旧contract ID | 1 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/resource_contracts/runtime_artifacts.py` (270行) | Harness能力/原生目录/资产；中性hash可复用平台但不搬品牌保护路径 | 11 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/resource_contracts/workspace_v1.py` (20行) | workspace资源合同，保旧contract ID | 1 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/runtime_composition/__init__.py` (7行) | 按符号拆Harness原生运行/sandbox外部环境；对象管理统一Environment | 22 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/runtime_composition/assembler.py` (77行) | 按符号拆Harness原生运行/sandbox外部环境；对象管理统一Environment | 0 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/runtime_composition/coordinator.py` (199行) | 按符号拆Harness原生运行/sandbox外部环境；对象管理统一Environment | 1 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/runtime_composition/fake.py` (122行) | 测试夹具；生产发行不含Fake入口 | 0 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/runtime_composition/protocol.py` (605行) | 按符号拆Harness原生运行/sandbox外部环境；对象管理统一Environment | 3 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/runtime_composition/sandbox_port.py` (285行) | sandbox外部环境实现及公开合同；不保私有全局factory/未知模块绕过Environment | 7 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/sandbox/__init__.py` (35行) | sandbox外部环境实现及公开合同；不保私有全局factory/未知模块绕过Environment | 0 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/storage/__init__.py` (24行) | 连接/事务机制→persistence-sqlite；业务schema/迁移→领域/显式产品历史迁移装配 | 68 |
| `plugins/runtime-compat/src/pacthold_runtime_compat/storage/database.py` (792行) | 连接/事务机制→persistence-sqlite；业务schema/迁移→领域/显式产品历史迁移装配 | 4 |

封存SQL：
- `plugins/runtime-compat/src/pacthold_runtime_compat/migrations/001_init.sql`
- `plugins/runtime-compat/src/pacthold_runtime_compat/migrations/002_rename_claude_md_ref.sql`
- `plugins/runtime-compat/src/pacthold_runtime_compat/migrations/003_work_core.sql`
- `plugins/runtime-compat/src/pacthold_runtime_compat/migrations/004_minimal_work_core.sql`
- `plugins/runtime-compat/src/pacthold_runtime_compat/migrations/005_resource_contract_inputs.sql`
- `plugins/runtime-compat/src/pacthold_runtime_compat/migrations/006_resource_contract_inputs.sql`
- `plugins/runtime-compat/src/pacthold_runtime_compat/migrations/007_resource_observations.sql`
- `plugins/runtime-compat/src/pacthold_runtime_compat/migrations/008_resource_observation_evidence_metadata.sql`
- `plugins/runtime-compat/src/pacthold_runtime_compat/migrations/009_execution_finalization.sql`

## 4. 002必须提交的逐符号迁移台账

每个公开符号/注册入口/wire方法/表至少记录：
旧文件与符号 → 当前行为 → 生产/测试/脚本/发行消费者 → 目标唯一owner与公开contract → 保持的ID/数据语义 → 实施工单 → 替代测试 → 旧实现退役条件 → 保留壳的理由。
不能仅写“迁Harness”。混合模块列出每一部分；纯机制的核心归属须通过无产品依赖测试。
未证实不使用记UNKNOWN，列补查方法；不能提前标DELETE。确实无人调用的业务才删，历史DDL和公开合同不按死代码删。
九份SQL和内嵌21版schema分别建fixture：空库、支持旧版、当前版、未来版拒绝、迁移失败回滚；保版本账，不删除旧迁移来制造绿。
静态消费者清单生成与动态/发行/网络补查分开；旧测试是迁移证据，不可因为导入旧模块全部删掉。

## 5. 嵌入原12工单，不新增第二队列

- 001：确认扫描来源和消费者发现范围，原001门不改变；此盘点不替代受控基线。
- 002：上述台账纳入identity/authority/public-api清单；冻结分域合同，确定新包与旧薄壳的发行闭包。无法判定的符号不放行相关下游。
- 004/005：落实中性治理/存储机制；领域DDL不进核心。注册/秘密/数据空间共用既有目标基础设施。
- 006：旧Server入口转同Environment；移除compat创建跨领域服务与native Profile必选、独立CoreBinding；迁移注册显式装配。业务清空完成前不能叫compat退役。
- 007：迁Harness原生实现及资源业务/品牌适配，更新生产消费者；封存已有执行关闭路径，禁止新请求走旧sidecar根。
- 008/009：旧前端wire解码/接口别名切至新领域客户端；平台不新增Agent/品牌schema。
- 010：Agent唯一会话/提交/config owner，Profile/Provider只资源及操作入口；拆旧SessionService、队列和交互记录，不带走旧总ProductService。
- 011：现有配置/发送/恢复用户路径回归；不得以“兼容清理”裁掉已可用行为。
- 012：逐项关闭台账。允许有理由的薄发行壳和历史读取/迁移资产，禁止默认产品依赖旧业务；未关闭项必须PARTIAL，不以移动目录数报DONE。

## 6. A95附加必需验收（不减少原95个case）

| 编号 | 正例要求 | 必须抓住的反例 | 缺条件行为 |
| --- | --- | --- | --- |
| C95-1 | 每个公开旧符号都有目标/消费者/保留或删除判据 | 新旧ProfileRecords同时创建，旧入口另开Database | FAIL，缺台账不可退役 |
| C95-2 | 旧import与新公开类型为同对象；方法通过同Environment/owner | copy类定义、import执行注册、第二ProductCatalog | FAIL，不用共用库证明单owner |
| C95-3 | 默认真实产物依赖新业务包，不依靠repo editable | wheel漏领域包、npm缺入口、旧compat装配兜底 | FAIL，未构建/安装受控产物不能报通过 |
| C95-4 | 原已支持Profile可选、model覆盖、发送/恢复路径保留 | 清理后旧route统一unavailable；强建native Profile才能发 | FAIL，provider确实缺席单独测拒绝 |
| C95-5 | supported旧库fixture可读且保ID/版本；失败不损坏原fixture | SQL改字节/改namespace、新建空库绕过恢复、unknown改成功 | FAIL，缺fixture或未跑不作迁移证据 |
| C95-6 | 白名单薄壳无store/process/queue/新增业务；业务内部不引用compat | 壳偷偷new SessionService、importlib加载旧worker | FAIL，动态引用未查完记缺口 |
| C95-7 | 删除项关联替代正反测试/旧消费者迁移证据 | 通过删旧测试/断言/skip消除红 | FAIL，对比逐ID结果与来源基线 |

已确认薄壳也要白名单，公开发行保留不等于永远保旧实现。默认目标架构图不画legacy-compat插件；迁移文档单列保留壳/封存资产。
