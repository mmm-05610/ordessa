# Agent Tools · 目录与组件架构

## 1. 三个部分，不是三个系统

1. Pacthold的Agent小模块：Profile清单、装配协调、节点绑定/公开管理面。
2. 叶子插件：Harness原生知识、Skills/MCP/Prompt/Model等独立领域。
3. 工具产品：CLI、Skill与后续MCP，是公开服务的消费者。

调用者与被调用对象是两回事：CLI面向任何有相应执行权限的调用者，不检查调用者是不是Codex或任何其他Agent。Skill提供使用说明，不是准入条件；不支持Skill的脚本和人也可以直接使用CLI。被调用节点使用哪个Harness，由Profile与已安装的provider决定，不由调用者品牌决定。

核心小模块设计沿用已审阅028修订；此文不新增环境层级、DAG或Agent团队。外部Sandbox/Worktree组合不在本产品第一版；项目工作目录来自现有项目服务的授权绑定。

## 2. Agent Tools 产品目标目录（不是当前已经生成的源码）

这里只展开本产品的宿主、公共依赖、叶子插件和工具入口，不是整个 Ordessa 仓库的目录。Desktop、前端包组及其他产品不纳入这棵树；它们仍保留在原仓库，不需要为本产品迁移或删除。

```text
apps/
  server/                                现有网络宿主，承载公开服务

packages/backend/                        026的目标包组
  environment-api/                       通用身份、授权、活动、占用
  pacthold/
    src/pacthold/agents/
      public.py                          核心Agent公开入口
      contracts.py                       Profile、节点、provider端口
      profiles.py                        清单catalog与不可变配置版本
      contributions.py                   同Environment已授权贡献视图
      resolution.py                      组织材料与版本取得
      assembly.py                        有界准备流程及节点发布
      nodes.py                           节点查询与使用/管理门面
      configuration.py                   Profile应用协调，不是配置owner
      recovery.py                        同节点恢复与历史接纳
      persistence.py                     同一持久机制的领域记录
  platform-services/                     安装/数据区/秘密引用
  persistence-sqlite/                     既有持久端口实现
  server-plugin-api/                      宿主贡献/公开route契约

plugins/
  harness/                               实际单元、原生配置owner、入口与历史
  assets/
    skills/                              现有发行名以源码盘点为准
    mcp/
    prompts/
    model-provider/                      各自资源目录与配置适配

products/
  agent-tools/                           独立CLI＋Skill产品，不注册为插件
    pyproject.toml                       独立Python包/CLI入口
    src/ordessa_agent_tools/
      __init__.py
      cli/
        main.py                          参数入口与退出码
        profiles.py                      清单命令
        agents.py                        准备/检查/配置/停止/恢复
        tasks.py                         托管任务提交/观察/结果
        projects.py                      项目与受控目录绑定
      client/
        transport.py                     连接既有Ordessa服务
        negotiation.py                   API版本、支持面与保证检查
        profiles.py                      ProfileCatalog客户端
        nodes.py                         AgentAssembly/Nodes客户端
        operations.py                    操作查询/订阅、不是本地调度账
        input_capture.py                 既有持久输入端口的消费者
      native_clients/
        registry.py                      已支持协议客户端选择
        <protocol>.py                    按被调用节点的原生协议适配，不按调用者品牌
        ...                              第二家族非首个产品闭环前置
      operations/
        prepare.py                       单次服务调用的客户端检查
        configure.py                     同一owner应用请求
        run_task.py                      任务消费；不主持Agent装配
        inspect.py                       安全投影与结果显示
      output/
        envelopes.py                     稳定JSON、错误、输出脱敏
        render.py                        人类可读输出
      mcp/
        server.py                        后续薄工具入口，复用operations
    skills/
      configure-agent-profile/
        SKILL.md                         配置定义，不偷偷启动/应用
        references/profile-values.md     kind/schema/原子组动态发现规则
      use-external-agent/
        SKILL.md                         准备、任务、观察、结果
        references/task-outcomes.md       unknown/cancelled/completed边界
      manage-external-agent/
        SKILL.md                         重配置、停止、恢复与核实
    packaging/
      bundle-manifest.json               wheel与Skill目录的分发清单
      build_bundle.py                    从唯一源码生成安装包
    tests/
      test_cli_contract.py               解析、JSON、退出码
      test_skill_bundle.py               Skill与命令版本一致
      test_transport_failures.py         离线/版本/授权/未知
      test_native_client.py              协议保持与消费者边界
      test_managed_input.py              输入关联/未知不重发
      integration/                       真实服务与原生进程，不默认模型调用
      test_assembly_manifest.py          可选服务装配的唯一Environment/owner
    deployment/                          可选服务端配套，不进入客户端wheel
      composition.py                     使用既有Server，选择core与叶子
      configuration.py                   服务bind/data root/策略的产品配置

specs/
  028-profile-harness-native-units/       核心修订，尚需正式同步旧工单
  029-agent-tools-product/               本客户端产品设计
```

不按目录创建空实现占位，实际需要什么才实现什么。`native_clients`属于消费者协议知识，不能import Harness私有适配器；复用公开客户端SDK/协议入口。MCP目录是目标第二阶段，第一版不先建空server冒称提供MCP。

第一版CLI是Python，和后端公共契约/测试工具保持同语言；不新增npm CLI及第二套发布流程。Skill是Markdown资产，不要求Node服务常驻。

## 3. 依赖方向

```text
products/agent-tools 客户端 → Ordessa公开wire + 原生公开协议/SDK
可选deployment装配         → apps/server + core公开入口 + 选中的叶子插件
apps/server         → core/宿主公开契约（不主持Profile步骤）
叶子插件            → core定义的provider端口
agent-tools CLI     → Ordessa公开wire + 原生公开协议/SDK
Skills              → 已分发CLI命令（无数据库和运行状态）
MCP入口             → agent-tools operations（无另一服务端权威）
```

CLI不依赖`pacthold`运行时、`ordessa_server`内部或Harness私有模块；必要DTO由核心维护的协议schema生成客户端视图，schema是唯一权威，不手写第二份可独立演进的语义。工具wheel不携带core数据库/服务器实现；完整headless产品安装可另选server组件。

项目服务需补DirectoryBinding公开接缝；CLI不能用`--cwd=/任意路径`直接绕过它。profile引用和node引用必须带environment/service范围，不能用裸名称跨多个服务猜路由。

## 4. CLI是否需要自己的daemon

第一版不需要。CLI命令是短生命周期客户端，节点和未决操作活在Ordessa服务及原生单元中。断开CLI并不停止节点。长任务默认取得operationRef后返回，`watch`只是观察连接。

原生协议需要持续客户端/callback持有时，必须由已注册的Harness受控原生连接服务或明确的前台客户端持有；不能在CLI临时fork一个无账后台守护进程。若只能由前台客户端持有，第一版明确`run --wait`需要保持该进程，掉线后的任务状态由证据核实，不能宣称daemonless自动托管所有callback。

只有真实持有者与fencing能力验证后才启用detach。detach产品能力不是仅返回operationRef：原生连接、反向请求的应答权和未决状态必须有受控持有者，审批不能被自动批准。

## 5. 三个Skill

| Skill | 服务能力 | 严格边界 |
| --- | --- | --- |
| configure-agent-profile | 列Harness/schema/资源、读/创建/编辑/clone/preview Profile | 编辑产生版本，不prepare、不自动apply、不写凭据 |
| use-external-agent | 选择Profile、项目绑定、prepare、run/watch/result | 不自动改模板，不把prepare完成当输入接受 |
| manage-external-agent | inspect、apply-profile、局部configure、stop/recover/reconcile | 写操作显式授权；disconnect不等于stop；unknown不重发 |

Skill自动发现描述应分别对应真实任务，避免三个都触发全部工作。一个任务可以先配置再使用，但必须先得到明确manifestRevision，再准备节点。Skill没有自己的Agent模板缓存或模型真值；命令查询的权威状态说了算。

支持文档只有需要时读取，SKILL.md保持短且可执行，不依赖某个Agent专属工具名称或指令语法。工具包安装不擅自更改任何调用者的全局配置；Skill安装需明确选择宿主及项目级/用户级作用范围。MCP注册也不是随wheel自动修改用户账号设置。

## 6. 两条典型链路

配置链路：发现实际Harness和配置kind→取得资源列表→读取Profile双revision→创建/编辑清单→preview→返回固定ProfileRef。核心验证结构，叶子解释字段，Harness判断原生适用性；unknown预览不显示已应用。

使用链路：选择服务/项目→授权DirectoryBinding→prepare固定Profile→query取得node→取得使用lease和真实nativeSession绑定→持久捕获任务→原生客户端提交→查询证据/结果→按授权管理节点。

同节点重新apply-profile走core解析协调、同Harnessowner及材料Usage换代。模型控件/CLI局部配置都不能直接写文件或另算currentModel。跨Harness家族必须新节点。

## 7. 分发与产品边界

两种安装对象明确分开：工具包（wheel＋Skill资产；连接已有服务）与headless产品（既有server＋core＋选中叶子＋工具包）。一个安装包可以包含两者，但用户明确选择是否运行服务及数据位置；不悄悄启动本机后台服务。

CLI、Skill、测试与打包的唯一源码都在`products/agent-tools`，不设对应的`plugins/agent-tools`，不需要插件注册、激活或Ordessa界面才能调用。Skill唯一源码在`products/agent-tools/skills`，打包复制到产物不产生第二维护位置。CLI entrypoint暂命名`ordessa-agent`，不抢占已有`ordessa`命令。MCP后续入口可用`ordessa-agent mcp serve --stdio`，复用同一客户端库；具体SDK与协议版本在那阶段固定。

独立产品指独立入口、安装包、版本和验收，不是复制一份后端。客户端wheel只包含客户端代码；可选`deployment`负责配套服务装配并使用既有Server，不能反向成为CLI导入的宿主内部依赖。

第一版支持面：一个实际验证的Harness家族，完整Profile/节点/输入/停止/恢复闭环；CLI+三Skill；不做桌面、插件市场、DAG、自动团队或外部环境编排。首个被调用Harness按实际资产/API接缝选择并记录；这只限制首轮验证覆盖面，不限制调用者，也不是将插件与该Harness绑定。
