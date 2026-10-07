# 目标目录与职责

这是目标组织，不是声称现有代码已经如此。每个可发布子包保留独立构建清单；目录组不得新增一份总入口承载子包实现。

```text
ordessa/
├── apps/
│   ├── desktop/                 Electron 启动、窗口、系统集成
│   └── server/                  网络协议、宿主启动与插件托管
├── packages/
│   ├── backend/
│   │   ├── environment-api/     环境公共契约
│   │   ├── pacthold/
│   │   │   └── src/pacthold/
│   │   │       ├── core/        通用治理、关系、索引及运行边界
│   │   │       ├── agents/
│   │   │       │   ├── profiles/       清单、版本、解析与持久端口
│   │   │       │   ├── assembly/       准备步骤、材料与组装记录
│   │   │       │   ├── nodes/          节点身份、目录及发布
│   │   │       │   ├── configuration/  配置唯一权威、修改与观察
│   │   │       │   ├── access/         使用/管理入口的公共契约
│   │   │       │   └── lifecycle/      节点生命周期及释放规则
│   │   │       └── …                  现有通用模块按职责保留
│   │   ├── persistence-sqlite/  公共持久化实现，不拥有领域权威
│   │   ├── platform-services/   数据区、密钥引用等系统机制
│   │   ├── harness-transport/   不含品牌规则的通道工具
│   │   ├── server-plugin-api/   后端宿主接入契约
│   │   └── decision/           已有决策模块，读事实、返回提案
│   └── frontend/
│       ├── contracts/
│       ├── extension-api/
│       ├── extension-runtime/
│       ├── extension-loader/
│       ├── extension-host/
│       ├── workbench/
│       ├── ui/
│       ├── ui-components/
│       ├── connections/
│       ├── server-bridge/
│       └── native-bridge/
├── plugins/
│   ├── harness/                 只有品牌目录与组说明
│   │   ├── codex/
│   │   │   ├── pyproject.toml
│   │   │   ├── src/ordessa_harness_codex/
│   │   │   │   ├── provider.py
│   │   │   │   ├── configuration/
│   │   │   │   ├── native/
│   │   │   │   └── server_plugin.py
│   │   │   ├── packaging/
│   │   │   └── tests/
│   │   ├── pi/                 同等独立包，不通过 Harness 总包注册
│   │   ├── claude-code/        同等独立包
│   │   └── <其他已有品牌>/     各自保留已有知识，不新增适配工作
│   ├── assets/
│   │   ├── skills/
│   │   ├── prompts/
│   │   ├── mcp/
│   │   ├── model-provider/
│   │   └── sandbox/            区分内置配置与外部环境，不合并语义
│   ├── agent-ui/               会话、连接、节点界面消费者
│   ├── profile-ui/             清单编辑及选择界面消费者
│   ├── chat/
│   ├── workspace/
│   ├── permissions/
│   ├── commands/
│   ├── connectors/
│   └── <其他已有领域插件>/     非本轮退役目标，不为图整齐而删除
├── products/
│   ├── desktop/                桌面启用清单与装配
│   ├── server/                 明确选择核心、持久化与独立插件
│   └── agent-tools/
│       ├── src/ordessa_agent_tools/  薄 CLI 客户端
│       ├── skills/
│       ├── deployment/         使用 Server 产品，不自带第二个后端
│       ├── packaging/
│       └── tests/
├── tests/
│   ├── boundaries/
│   └── integration/
├── specs/
├── docs/
└── scripts/
```

`decision/` 是独立工作树已有成果的保留位置，不是本轮新增核心执行者。它只能通过公开读端口观察并返回提案，不能维护另一套节点/Profile 权威。

## 依赖边界

| 组件 | 可以依赖 | 不可以做 |
| --- | --- | --- |
| Pacthold | 公开契约、通过注入获得的持久化/能力端口 | import 品牌插件、Server、产品；知道品牌配置字段 |
| 独立 Harness 插件 | Pacthold 注册契约、通道工具、系统服务端口 | 相互导入；依赖 `ordessa_harness` 总包；充当 Profile 总权威 |
| Assets 插件 | 公共资源/配置贡献契约 | 直接维护 Agent 运行配置副本 |
| Server | 宿主契约、内核公开入口 | 包含品牌工厂、直接打开插件领域数据库 |
| 产品 | 选择并连接上述公开入口 | 私自实现节点/配置状态机；拼品牌内部路径 |
| Agent/Profile UI | 核心事实投影、操作入口、公共前端机制 | 保存第二份“已应用配置”；直接修改后端领域存储 |
| Agent Tools | 服务 API、客户端交互 | 自带品牌运行器或另一套 Profile/节点权威 |

## 内部拆分约束

Pacthold 的 `agents/` 拆目录只整理现有职责，不引入新的环境层级或第二套组装模型。现有同名 `assembly.py` 等模块迁移时不可同时留文件和包。公共导出随消费者一起切换，不设置旧 import 的转发模块。

前端公共 Agent/Profile wire 类型、只读事实投影契约迁入 `frontend/contracts/` 的明确领域命名空间。表单、选择器、消息和图标仍是 UI 插件内容；不得把所有 Agent UI 逻辑塞入通用 Workbench。
