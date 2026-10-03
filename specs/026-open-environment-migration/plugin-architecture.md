# L1 插件目标格局 — 领域完整、入口按需、单一权威

R4设计：替换026旧“插件路径完全不动”的约束；用户已接受领域归属方向，本轮完善方案而非执行迁移。路径可改，发行名/import名/extension ID、数据namespace与存储标识不改。品牌差异集中Harness。分类仅是文档/导航标签，不提供权限或依赖特权。

## 1. 目标目录

```text
plugins/
  harness/                 原生运行实例、协议、品牌适配与原生证据
  agent/                   逻辑会话与统一配置/提交/运行/交互领域
  chat/                    消息视图、输入框、草稿与Chat专属贡献
  profile/                 配置清单、预设编辑、解析与操作入口
  model-provider/          供应商/模型目录、认证引用和选择入口
  workspace/               项目/工作区资源与验证
  skills/                  Skill目录、内容与作用域分配
  prompts/                 指令/人格等内容资源
  command-templates/       命令模板资源；不是平台命令注册表
  subagents/               子代理定义资源；不实现新协作调度
  memory/                  记忆资源与配置
  runtime-preferences/     运行偏好定义与资源
  mcp/                     服务定义/分配/业务控制，协议仍域内
  lsp/                     LSP资源与服务能力
  sandbox/                 外部环境隔离策略/实现
  permissions/             外部权限规则；不接管原生内部审批
  extensions/              Hooks/原生扩展资源；不是Ordessa插件loader
  # 不设legacy-compat领域插件；必要旧发行薄壳另列兼容清单
```

OpenShell等独立外部环境插件以后以自己的领域目录接入；本轮不新建占位实现、不增加022/023的功能开发范围。无Agent/Chat/Profile也可以接入普通资源/服务/终端插件。

## 2. 一个领域插件的内部组织

以下是能力较完整插件的参考结构，仅创建真实需要的包/目录，不要求所有插件都有前后端。

```text
plugins/<domain>/
  plugin.manifest.json             逻辑插件与发行入口的装配元数据
  README.md                       所有者/公开能力/缺席行为/生命周期
  contracts/
    schemas/                      wire schema/纯DTO来源
    typescript/                   公共TS类型、token carrier、codec
    python/                       公共Python协议/DTO（有消费者才独立发行）
  backend/
    pyproject.toml                保持现有Python发行/import名
    src/<existing_module>/
      domain/                     资源或领域规则、状态唯一owner
      capabilities/               公共能力适配；只通过Environment访问别域
      persistence/                业务schema/Repository；借DataAreaPort
      entry.py                    注册/生命周期声明，不混产品装配
    tests/
  frontend/
    api/                          公共界面贡献/领域客户端合同
    services/                     本地域owner或后端能力代理，二选一权威
    views/                        页面及只读投影
    settings/                     编辑草稿和字段贡献
    contributions/                命令、导航、输入区、设置注册
    entries/                      多个按需启用的既有extension入口
    package.json                  可按现有发行单元继续拆子workspace
    tests/
  adapters/                       自身资源/协议边界，非其他Harness品牌适配
  integrations/<other-domain>/    可选的真正两域协作，不藏基础业务
  packaging/                     本插件资产锁、构建与安装声明
  tests/                          跨入口集成/公开合同/缺席/退出测试
```

contracts允许共享业务schema但不建运行状态；同进程Token仍一个carrier，不能TS/Python各自产生一个“跨进程Token对象”。backend/front多入口保现有npm/wheel单元，逻辑插件不等于只能有一个package.json。源码一处、发行入口可多个，不能copy出多套实现。

插件公开export只含合同、构造/注册入口或受管理客户端，不暴露可变store。消费者允许依赖其他插件的公开契约，不能import私有服务/业务实现。imports/API依赖与运行required/optional能力分开声明，不以安装某wheel就代表provider已经活跃。

## 3. 装配元数据不是第三个宿主

plugin.manifest.json是构建时逻辑目录：schemaVersion、logicalPluginId、displayName、categories、versionSource、artifacts[]、entries[]（引用既有ID、package/entrypoint、frontend/backend执行域）。可引用契约/资源空间声明供校验。没有独立enable flag、启动函数、动态注册表或父插件调度器。

已有运行manifest是各入口声明，products是选择/版本锁权威；构建校验logical元数据与它们一致、生成路径锁，但不再求一遍依赖/在运行时二次resolve。前端Lumino与后端Environment各管理自己的执行域；前后端通信是代理关系，不是两个后端业务核心。

用户extensions.json完整覆盖（含空覆盖）保持。关闭前端入口不自动关后端对象，关闭后端入口按Environment drain；产品可预先选择一组入口，但本轮不新增“逻辑插件一键全生命周期”业务。契约版本、sourceDigest、required构建闭包以及动态能力可用性不同，不能互相替代。

## 4. Harness / Agent / Chat 的边界

| 领域 | 唯一负责 | 明确不负责 |
| --- | --- | --- |
| Harness | 原生实例、品牌配置机制、协议会话/运行证据、native load/resume、原生surface | Provider目录/预设业务、UI状态；不重做原生推理/工具/workflow |
| Agent | 产品逻辑会话、配置操作与证据投影、提交捕获、运行/交互领域关联 | 原生执行引擎、品牌配置格式；不成为所有插件必需父层 |
| Chat | Chat页面、消息展示、编辑草稿、输入贡献和触发操作 | 第二currentConfig/session/send-result权威；不编排品牌 |
| Profile | 保存资源配置清单、字段编辑器注册、解析清单、提交patch | 会话配置owner、provider业务、品牌应用 |
| Model-provider | 供应商/模型目录、配置资源与秘密引用、模型选择操作 | 第二份会话配置、原生账号刷新、对各品牌落盘 |

Agent详细公共合同见contracts/agent-domain.md。Agent通过Harness公开能力完成原生操作，调用/绑定/订阅由Environment管理。Native实际配置仍原生所有；Agent拥有意图及可信确认投影，不声称取代原生事实。

## 5. Harness内部的品牌与资源组织

```text
harness/
  contracts/                       中性Harness能力、ResourceEnvelope、证据
  backend/src/ordessa_harness/
    instances/                     原生启动/停止/目录/owned范围证据
    sessions/                      native ID、load/resume、history解码
    surfaces/                      协议无关边界描述
    protocols/                     acp/app-server等实际协议适配
    brands/
      codex/{launch,configuration,resources,auth,evidence}.py
      pi/{launch,configuration,resources,auth,evidence}.py
      claude/{launch,configuration,resources,auth,evidence}.py
    resources/
      registry.py                  中性输入合同到内部品牌handler的接线
      contracts.py                 通用注册/支持与缺席规则，无资源业务store
    entry.py
  frontend/
    adapters/                      原生/Server Agent数据到领域合同的解码
    contributions/                 原生surface入口/设置
  packaging/brands/                各品牌可验证原生资产，保既有标识
```

每个品牌目录内允许resource子模块（skills/mcp/provider/prompt等），共享代码放Harness内部，不强制笛卡尔积创建空文件。Brand/resource支持矩阵由Harness声明supported/unsupported/unknown，不由资源插件据品牌名猜。可组合公开资源协议，核心不新增facet枚举。

资源插件负责ResourceEnvelope的身份/版本/内容解析和领域校验；Harness负责怎么给品牌用。新增资源：资源插件公开中性资源合同/能力，Profile注册它的可选编辑/解析贡献，Harness按需接内部实现或明确unsupported。新增品牌：仅Harness新增brand模块/资产及矩阵，各资源插件不用改品牌条件。均不改Pacthold。

Harness内部注册不是第二Environment：只保存本插件的适配函数/支持描述，不能管理外部插件激活、权限或跨插件生命周期。加载外部适配代码必须作为受管理贡献接入，不能私自动态import未知模块。

## 6. 前后端交互与可选协作

资源插件注册公共后端能力，前端通过Environment桥接代理访问；UI注册到Workbench/Chat等公开贡献点。默认Profile/model选择控件是各插件的contribution，可通过Chat公共输入栏出口展示，调用Agent公共配置操作，不能读取Profile glue私有serializer/binding。

Profile对外开放可选配置字段贡献：资源contractId/version、字段schema/editorKey、解析能力Ref、敏感性与缺席描述。Profile只组织清单；缺资源provider时该字段未可解析，保数据不自动替默认；字段原生应用只有Harness解释。

必须双域协调才保integrations：例如既有model-provider与Profile的facet桥可以改为公开贡献客户端；通用持久引用查询迁E5，不再深扫Profile内容。任何资源管理基础功能在无Chat/Profile时仍可用；可选integration缺席只撤附加入口。

## 7. 现目录去向（不得整体搬错）

| 来源 | 目标及拆分 |
| --- | --- |
| plugins/assets/model-provider | plugins/model-provider；server→backend，desktop/chat贡献→frontend，Profile贡献→公开facet协作；品牌adapters→harness内部 |
| plugins/assets/{skills,prompts,command-templates,subagents,memory,runtime-preferences,mcp,lsp,sandbox,extensions} | 各同名顶层领域；品牌适配归Harness，资源业务/API留本域 |
| plugins/permissions、workspace | 同领域路径，内部统一公开契约/入口布局，策略不吞核心 |
| plugins/agent/{contracts,sessions,connections} | contracts保公共域carrier；sessions中的UI/逻辑分开；connections通用handle生命周期→frontend/connections，Agent客户端/会话投影→Agent |
| plugins/connectors/acp | 原生协议/品牌相关→Harness adapters；通用传输handle→frontend/connections/native-bridge；Agent投影→Agent适配，禁止整包塞Harness |
| plugins/connectors/ordessa | 通用Ordessa wire/认证关联→frontend/server-bridge；Agent消息解码→Agent adapters；API/extension ID原样映射 |
| plugins/chat | Chat专属API/视图/草稿保留；通用注册/组件/scope复用平台，不新建Chat核心 |
| plugins/profile | frontend/settings+清单业务保留，选择glue仅贡献，配置owner迁Agent |
| plugins/commands | generic registry/execute→frontend/extension-runtime，快捷键/面板组织→Workbench，业务handlers→所属插件；旧ID仅forward入口 |
| plugins/server-compat、runtime-compat | 按compat-retirement.md逐模块/符号迁所属owner；取消整体收拢legacy-compat，旧发行/入口ID必要时仅留同实现薄壳及封存历史迁移 |

适配品牌以外的数据库/内容import/parser属于资源域的adapters，不因目录名一样都搬Harness。旧server-compat认证/资源业务不可仅换到legacy文件夹便算完成；逐项公开能力迁移，compat消费者/退出条件登记后退役。主树AGENTS关于外仓Profile的冲突仍由001获确认，不擅自改指令。

## 8. 实施级别与验收

1. 002先冻结目录映射、发行/入口身份、所有者、公开contracts和构建依赖；不先全仓移动。
2. 004/005落实共享基础设施；006/007先在旧路径完成后端权威/能力接线，再按领域迁backend。
3. 008迁frontend和通用命令；009完成桥/surface/宿主交互；010完成Agent单owner与资源贡献；011受控/原生链。
4. 012删除旧主写、检查所有package/pyproject/build/test/CI/manifest/lock、独立发行/无Profile/无Chat/异协议插件回归。

命名迁移附旧路径→新路径→旧发行ID→新入口→具体消费者→替代测试→退役条件表；实体持久身份不随目录变动。业务原生能力未实现可保持明确unsupported，但不把已经可用链路丢掉。

必须证明：一个逻辑插件可仅启backend/仅启frontend可用部分；无Profile模型切换可用；新资源/异品牌不改核心；两个选择控件读同owner；资源自身业务不依赖Chat；旧ID导入无第二Token/实现；legacy桥不持新账；默认产物包含真实选中入口而非源码路径偷补。
