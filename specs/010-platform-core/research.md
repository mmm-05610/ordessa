# Research & Decisions

Date: 2026-09-27。来源为官方文档与 main 代码盘点，不代表运行过上游项目。

## R1 服务与贡献，而非业务门面总表

Decision: 插件消费公开服务、向所有者贡献。Server 不维护业务字段表。
Rationale: [Theia](https://theia-ide.org/docs/services_and_contributions/)区分服务与贡献；[Backstage](https://backstage.io/docs/backend-system/architecture/services/)使用显式服务引用/作用域。
Alternatives rejected: 万能 service locator、复制 Inversify、把所有业务放入 server-plugin-api。

## R2 保留 Lumino 与扩展式 Workbench

Decision: Workbench 迁平台包但继续扩展加载；公共 API 单实例。
Rationale: [JupyterLab](https://jupyterlab.readthedocs.io/en/stable/extension/extension_dev.html)的基础能力也通过扩展提供；Token 身份依赖共享模块。
Alternatives rejected: Electron 硬编码布局、第二套加载器、同名 Token 复制。

## R3 通用资源生命周期，品牌内部资源仍归驱动

Decision: Pacthold 管跨插件租约与执行证据，执行 provider 管自身运行，ACP 通道可为资源输出。
Rationale: [Nomad drivers](https://developer.hashicorp.com/nomad/plugins/author/task-driver)明确运行句柄、停止/销毁/恢复；[Caddy modules](https://caddyserver.com/docs/extending-caddy)明确初始化与清理责任。
Alternatives rejected: ACP channel 一律冒充执行；内核管每个驱动内部文件；Stop=Destroy；强制 sandbox。

## R4 外部副作用不假装事务

Decision: 意图先落账、稳定操作键、unknown 冻结依赖、明确对账能力。实例级 Store 替代全局 configure_database。
Rationale: 当前全局 _conn 会跨 runtime 影响；外部进程启动不能与 SQLite 原子提交。
Alternatives rejected: 超时自动重发、进程退出即失败、取消 ACK 即释放资源。

## R5 历史兼容外移，但不破坏数据

Decision: runtime-compat 只承接旧核心领域模块/封存迁移；B 负责业务消费者迁移；新裸核心采用独立中性 schema，旧产品原迁移资产/记录保持。
Alternatives rejected: 核心 re-export 业务、删旧表、重编号历史 SQL、静默吞缺失提供者。

## R6 三线而不是按每个插件开一棵树

Decision: A 核心/B Server/C 前端；A 公共契约先交，B 依赖集成固定 SHA。
Rationale: 同一个平台机制的改造必须在一条线内收敛；共享文件有单一所有者。
Alternatives rejected: 每个插件自行设计平台接口；A/B 同时改 server-compat。

## Spec Kit Provenance

C6 用户修正：通用 Connections 是前端平台机制，不是业务域。现场 entry 混 AgentClient、workspace 混 run/approval、status 含 Agent UI，因此选择分离而非整包上移；native-bridge 仅负责 IPC，不替代 renderer 侧连接注册。新增 C6 定义及 CN 反例，不引入统一网络协议或 Pacthold 依赖。

使用 github/spec-kit 官方源码 commit c00dc0551583428a10a94443c58c6a41e5e0138c（版本自报 1.0.13.dev0）的 CLI 生成 .specify 与 Qoder skills；使用官方 spec/plan/tasks 结构。非第三方封装。CLI 只在隔离目录运行，未对根 main 初始化。
参考：[官方流程](https://github.github.com/spec-kit/reference/agentic-sdd.html)、[官方集成](https://github.github.com/spec-kit/reference/integrations.html)。项目层 skills 随工作树提供，启动新 Qoder 会话后使用；不是系统全局安装。
本批未安装 git/auto-commit/外部工具 hook，不允许模板改变已冻结语义。SPECIFY_FEATURE_DIRECTORY=specs/010-platform-core 显式选择文档；当前官方版本不使用旧 SPECKIT_FEATURE 变量，预检已据实校正。
