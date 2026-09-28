# Technical plan

## 目标布局（新增目录只随真实实现创建）

```text
plugins/harness/
├── api/                         # 独立轻量 Python 发行包 ordessa-harness-api
│   ├── pyproject.toml
│   └── src/ordessa_harness_api/ # 注册描述、类型化 intent/result/errors；无宿主/品牌实现
├── src/ordessa_harness/
│   ├── runtime/                 # 实例/generation、协议控制权限、重启恢复
│   ├── configuration/           # registry、plan、apply、journal、reconcile
│   ├── materialization/         # 文件合并、原子发布、秘密注入、产物清理
│   ├── adapters/                # 品牌运行差异；不再放 Skill/model 业务转换
│   │   ├── codex/
│   │   ├── pi/
│   │   ├── claude/
│   │   └── …                   # 仅已有品牌真实实现，不创建空壳
│   ├── integration/             # Server/Pacthold 注册；不导入 host internals
│   └── server_acp/              # 现有通道与 relay 所有权保留，内部调用 runtime
├── harnesses/、runtime/         # 既有 JS 启动/传输资产；统一生成的品牌描述入口
├── adapters/acp-adapter/        # 现存 Go 上游适配资产，不恢复已删除 Claude 实现
├── packaging/                  # 固定上游版本、构建/探针，不跟踪二进制
└── tests/                      # 契约、生命周期、适配一致性、隔离与受控集成

plugins/assets/model-provider/
└── …/harness_adapters/          # 每品牌模型/供应商配置映射、验证/读回判据
plugins/assets/skills/
└── …/harness_adapters/          # 每品牌 Skill 格式、发现根、启用/移除语义
plugins/profile/                # preset、facet 贡献、覆盖、解析、确认后的绑定
plugins/connectors/acp/         # 唯一 ACP 会话客户端；同一提交闸门的消费侧
```

文件夹是业务域，api 是依赖边界，不是第四个核心。TS 消费既有 ACP/Server 领域 API，公开配置 DTO 在现有领域契约位置扩展，不另建 Harness UI 总平台。assets 路径是目标布局；从旧 plugins/model-provider 等搬迁必须与消费者和产品清单同批完成。

## 依赖与职责

| 所有者 | 负责 | 禁止 |
| --- | --- | --- |
| Profile | facet 注册、保存、有效值解析、会话覆盖与应用回执 | 品牌文件路径、直接 spawn、直接改原生配置 |
| 业务插件 | 业务实体、表单、业务 schema；品牌配置 adapter | 自己决定重启/杀进程、写用户全局配置 |
| Harness API | 领域 DTO/Protocol 与版本校验 | 导入任一业务实现、启动副作用 |
| Harness runtime adapter | 原生版本/能力、允许配置目标、控制动作、隔离、恢复身份 | Profile CRUD、模型目录、Skill 仓库管理 |
| Harness application | 合并 intent、串行应用、确认/恢复日志 | 执行工作策略、另建资源租约数据库 |
| ACP session owner | 提交闸门、唯一协议连接、先配置后发送 | 品牌 if/else、密钥处理 |
| Pacthold | 执行/资源依赖、租约、停止/回收事实 | provider/model/Skill/Profile 字段 |
| Server | 通用贡献承载、鉴权、传输 | Harness 注册表、品牌发现规则 |

依赖图：业务配置适配器 → Harness API ← Harness 实现；Profile 与会话服务通过公开应用端口消费 Harness。Harness 实现不 import 业务插件。产品选择要启用哪些贡献者；注册点所有者与贡献者生命周期交给既有宿主机制，领域只校验自己的 payload。

## 技术决策

1. 两个领域扩展点由 Harness 拥有，借 Server 已有 contribution carrier 注册。不是向 server-plugin-api 加业务常量，也不是让消费者直接修改 Harness 字典。
2. 品牌运行描述为单一真源，Python 与 JS 读取同一经校验的序列化 launch descriptor；品牌模块仍可语言内实现，不能维护两个互相漂移的“支持品牌清单”。外部 adapter 通过产品显式组合，不扫描任意系统目录自动执行。
3. 配置编译是业务插件内纯逻辑；原生文件落盘、秘密解析与动作执行统一由 Harness 完成。合并在副作用之前完成。
4. 优先原生 session-local API；其次实例私有配置+安全 reload；再次重启恢复。不自动选择全局写文件，不以私有 HOME 的存在推断全部依赖已隔离。
5. 默认插件可选接入 Profile/Chat/Harness：业务管理本体不强依赖三者。需要 Harness 的 glue 作为同一业务域的独立运行注册入口，缺失宿主不导致独立管理功能崩溃。
6. 应用器持有操作日志，不持有第二份 execution/lease 权威。每个操作关联实际资源租约与 execution；资源释放结果 unknown 不记 released。
7. API 包无第三方运行依赖；实现采用已锁定的解析库。文件不在原位置改写，生产原生快照落实例私有根；用户文档/内容仓只读引用或经策略复制，无全 HOME 复制。

## 实施次序

平台集成/接口冻结 → API 与负例 → 运行 adapter 收敛 → 应用引擎 → 模型/Skill 两真实适配迁移 → Profile/ACP 提交链 → 删除旧实现 → 隔离与集成门禁。可并行的是冻结 API 后两业务 adapter；会话接线必须等结果语义稳定。

允许改动：Harness、两业务插件及其接口、Profile 应用 glue、connectors/acp 提交/控制接缝、产品装配/依赖锁和对应测试文档。**这不是能只改 Harness 一个目录的任务**；若不迁消费方，就会留下两条旧链。禁止修改 Pacthold/Server/Desktop host/Workbench 生产代码来兜底。发现核心接缝确实缺失，记录 blocks B1，不私自扩展核心。

## 完成纪律

单一包内实现与测试一起交付；跨包契约先冻结。主协调者负责范围、集成和复核，不靠随手跨包补丁绕过所有者。每个阶段是可检查点，不是遇小错误即停止的授权门。不可解的版本能力缺口按 blockers.md 登记并继续独立任务，所有必需门未完成前不得报告完成或自行合并。
