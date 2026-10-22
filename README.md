# Ordessa

**把 AI 编程中的设计、任务执行和审核验收连起来。**

Ordessa 是面向编程 Agent 的软件工程任务执行与管理系统。项目的目标是：开发者在熟悉的 Codex、Claude Code 等工具中讨论方案，由主 Agent 调用 Ordessa，将确定的设计变更组织成可执行、可检查的开发任务，并关联设计版本、执行过程与审核验收结果。

围绕一项开发工作，Ordessa 希望让这些问题都有明确答案：

- **依据是什么？** 任务对应哪份设计、哪个版本和哪些要求。
- **由谁执行？** 使用哪个编程 Agent、哪份配置，在什么环境中运行。
- **执行到了哪里？** 请求是否已受理、是否仍在运行，结果或异常是什么。
- **凭什么接受？** 哪些检查和审查已经完成，是否满足方法规定的验收条件。

## 一项开发工作的目标流程

以修改一个已有功能为例：开发者与主 Agent 讨论变更，主 Agent 提交设计；设计通过审核后形成规格说明、实施计划和任务清单；系统组织执行，再将产出交给独立审查和验收。

```mermaid
flowchart LR
    A[讨论方案] --> B[提交设计变更]
    B --> C[设计审核]
    C --> D[实施计划与任务]
    D --> E[Agent 执行]
    E --> F[独立审查]
    F --> G[验收与记录]
```

这是项目的完整目标流程；具体步骤、所需报告和通过条件由工程方法定义。设计、任务和检查结果之间的关联，使一次修改可以追溯到它的依据和接受理由。当前实现进度见下方“当前阶段”。

## 核心能力如何分工

| 能力 | 负责的事情 | 具体内容 |
| --- | --- | --- |
| 工程管理与方法 | 组织工程对象及设计、实施、审查和验收之间的关系 | 设计变更、实施包、任务、评审记录；方法声明步骤、报告与验收要求 |
| Agents | 管理编程 Agent 的配置与交互 | Profile 修订、Harness 选择、实例启动、发送任务、查询结果和生命周期管理 |
| Environments | 提供任务使用的运行资源 | 环境资源、使用句柄、进程和文件操作；具体实现包括 Local 与 OpenShell |
| Decision | 执行规则检查或调用判断能力，并记录结果依据 | CEL 规则、JeV 判断、结果摘要与证据引用 |

Agents、Environments 和 Decision 可以独立使用，也可以由上层组合。一次 Agent 调用不必经过完整工程流程；Decision 也不是所有执行的必经步骤。工程方法决定何时需要检查，以及如何使用检查结果。

不同编程工具通过 Harness 插件接入，并保留各自的原生协议：例如 Kilo 使用 ACP，Codex 使用 app-server 协议，Claude Code 和 Pi 使用各自的原生交互格式。环境实现则负责具体的进程与文件能力；Local 在本机运行并明确报告无安全隔离，OpenShell 对接沙箱及其策略。

执行状态和工程结论分别记录：发送停止指令不等于进程已经退出，Agent 返回结果也不等于工程验收通过。对于结果未知的请求，系统保留未知状态，避免把重发当作默认恢复方式。

## 当前阶段

截至 2026-10-21，项目处于开发与联调阶段。当前落地主线是 **Agents、Environments、Decision，以及调用它们的 CLI 和 Server**。工程管理上层已有实现，但其装配处于冻结、待重设计状态，完整的设计到验收流程尚未完成闭环验收。

仓库中已有以下具体场景的验证记录：

| 场景 | 记录中的结果 | 证据与范围 |
| --- | --- | --- |
| CLI 调用正式 Server 装配 | 一个 Server 进程同时提供 `agents`、`environments`、`decisions` 三组能力：列 Harness、建 Profile、在环境里执行命令、跑真实 CEL 决策 | [正式装配冒烟记录](docs/verification/agent-cli-server-20261020/full-stack-smoke.md) |
| 编程 Agent 执行一次修复任务 | Codex 在一个有失败测试的迷你仓库里自行读代码、改 `calc.py`、跑测试；宿主再独立跑 `pytest` 验证通过 | [单次修复任务记录](docs/verification/agent-cli-server-20261020/p0-swe-task.md)，采用同步等待 |
| 真实模型单轮回合 | Kilo（`deepseek-v4.1-flash`）与 Claude 各自返回真实答案 `391`；Codex 同链路同样通过 | [kilo 记录](docs/verification/agent-cli-server-20261020/t08-kilo.md)、[claude/pi 记录](docs/verification/agent-cli-server-20261020/t08-claude-pi-3rdparty.md) |
| 多轮同一原生会话 | 同一个 session 连发两问，回答 `391`、`144`；同 sessionId、不同 turnId；查询不重放 | [多轮记录](docs/verification/agent-cli-server-20261020/t05-multiturn.md) |
| 工具写入与成果取回 | 模型在环境里写文件；Server 侧通过 `environments.files` 独立读回并核对 sha256 | [工具与取回记录](docs/verification/agent-cli-server-20261020/t06-tools-and-retrieval.md) |
| 实例生命周期 | `agents.start` / `get` / `reconcile` / `stop` 在 Local 环境上完成；四个品牌启动成功；原生交互面为 `agents.native.describe/request/notify/query/events/respond` | [实例接入记录](docs/verification/agent-cli-server-20261020/t04b-agent-instances.md)（历史记录中的 `native.freeze` 入口已退役） |
| 默认 Server 安装范围 | 独立安装环境启动 Server、调用 Profile，并验证不依赖旧上层装配 | [安装验证记录](docs/verification/agent-cli-server-20261020/s09-installed-closure.md) |
| 本机沙箱创建 | Server 通过本机 OpenShell 网关创建真实沙箱环境（create 完成，后续 exec/files 见下方边界） | [OpenShell 记录](docs/verification/agent-cli-server-20261020/t09-openshell-wiring.md) |

这些记录分别说明具体场景的结果。完整产品验收、长任务的异步提交与恢复、旧 Units 链清理，以及上层工程流程重设计，仍是后续工作。桌面端和独立 MCP 应用的状态也不能由上述 CLI／Server 场景推导。

## 仓库结构与责任边界

Ordessa 使用单仓库组织源码，主要实现语言是 Python 和 TypeScript。

```text
apps/                         可运行入口与最终装配
  cli/                        ordessa 命令行
  server/                     Server 进程与服务装配
  desktop/                    Electron 桌面入口
  product/ordessa/             产品安装元包
  mcp/                        独立 MCP 应用预留
  status-board/               独立状态应用预留
packages/
  engineering/                工程对象、方法解释与工程用例
  execution/
    agents/                   Profile、Harness 与 Agent 执行机制
    environments/             环境资源、使用句柄及进程／文件接口
    decision/                 决策任务、规则／判断调用与结果证据
    units/                    仍保留的历史执行单元实现
  interfaces/                 渠道、传输、公开契约和能力注册／派发
  infrastructure/             通用技术机制
plugins/                      具体 Harness、环境、Decision 及界面插件
methods/                      工程方法、策略与所需资源
tests/                        跨模块集成与端到端测试
docs/                         设计、规范、验证记录与迁移资料
```

`apps` 负责把实现连接起来；各能力模块拥有自己的语义和状态；跨模块通过公开接口或端口协作。具体工程政策位于根目录 `methods/`，由 `engineering` 中的方法机制解释和应用。依赖规则见[工程组织与模块边界规范](docs/standards/engineering-standard.md)。

源码目录与安装包是两个维度。例如 Harness 源码仍在 `plugins/harness/`，当前随 `ordessa-agents` 发行；Local／OpenShell 随 `ordessa-environments` 发行，CEL／JeV 随 `ordessa-decision` 发行。具体选择以各包的 `pyproject.toml` 为准。

`units` 和旧上层装配仍保留在源码中，尚未完成全仓退役；它们不是当前默认下层安装的必需依赖。范围见[上层保留清单](docs/migration/server-lower-closure-20261020.md)；该文中的阶段性待验项结合较后的安装验证记录阅读。

## 使用与开发入口

当前产品元包定义在 [apps/product/ordessa](apps/product/ordessa/pyproject.toml)，Python 要求为 **3.12 及以上**。它选择 Server、CLI、Agent、环境和 Decision 实现；上层历史装配不属于默认依赖。源码树安装使用单一安装器（它同时校验 [Python 工作区清单](python-workspace.json)）：

```sh
python -m pip install -r tooling/workspace/nightly-python-requirements.txt
python tooling/workspace/python_workspace.py --install
```

### 零配置启动 Server

Server 不需要配置文件：数据根缺省为 `$HOME/.ordessa`，也可用 `--data-root` 指定；实例 token 在首次启动时自动生成（0600），`instance.lock` 防止同一数据根被两个进程持有。

```sh
ordessa-server --data-root /tmp/ordessa-demo/root --port 48765
# 启动横幅会打印 listening 事件、生成的 token 路径和能力组：agents, environments, decisions
```

另一个终端里，CLI 默认连接该实例（`--data-root` 指向同一个数据根即可，默认端口 48765）：

```sh
ordessa --data-root /tmp/ordessa-demo/root --json list
ordessa --data-root /tmp/ordessa-demo/root agents harness list
ordessa --data-root /tmp/ordessa-demo/root agents profiles create demo --name Demo --manifest manifest.json
```

常用能力示例（全部走同一个 Server 与同一套能力发现契约）：

```sh
# 环境：创建 Local 环境、在 Server 进程内执行命令
ordessa --data-root …/root environments create local --root /tmp/ordessa-demo/work --json
ordessa --data-root …/root call environments.exec --input exec.json   # {"reference": "...", "argv": ["echo","hi"]}

# 决策：真实 CEL 规则 + 落盘证据
ordessa --data-root …/root decisions run --job job.json --request-id demo-1 --json

# 能力是机器可读的：先发现再调用
ordessa --data-root …/root describe agents.start --json
```

`--state` 仍是纯本地一次性模式（没有 Server）；`--data-root` 用于对接 Server，`--config`／`--service` 用于显式多服务配置。CLI 支持结构化 JSON 输出、请求标识和结果引用，便于编程 Agent 调用。

命令和操作示例见 [CLI 说明](apps/cli/README.md)。该页的旧插件独立构建命令及部分状态备注尚待同步，安装结构应以当前包声明、[Python 工作区清单](python-workspace.json)与[工作区安装工具](tooling/workspace/python_workspace.py)为准。JavaScript／TypeScript 使用根 npm workspaces 和锁文件。

开发约束见 [AGENTS.md](AGENTS.md)；凭据、用户数据及原始私有运行输出不进入源码仓库。真实模型验证需要明确的调用范围和预算授权。

## 验证与 CI

CI（`.github/workflows/ci.yml`）按当前收敛结构运行两条必需检查 `backend`／`frontend`：

- `backend`：用上面的安装器安装全部同源发行，然后跑**当前为绿**的切片——CLI、Environments/Local、Pi、CEL 规则，
  以及 Server 组合（含全栈冒烟与安装闭包门）；其余已知红套件保留在非阻塞的 `ledger` 步骤里继续可见，不删除断言。
- `frontend`：`npm ci` 后运行在当前 checkout 下通过的 workspace 套件，其余套件同样进入 `ledger` 步骤。

本地等价命令：

```sh
python tooling/workspace/python_workspace.py
pytest -q apps/cli/tests packages/execution/environments/tests plugins/environments/local/tests \
         plugins/harness/pi/tests plugins/decision/rules-cel/tests
```

本轮验收与真实证据边界见 [Foundation 1.0 验收报告](docs/verification/foundation-1.0-20261022/README.md)。

### 原生交互面（正式 CLI 示例）

以已启动的实例和已导出环境端点为例，异步提交后由独立进程查询/读游标，不阻塞 CLI：

```sh
ordessa call agents.native.describe --input describe.json --json      # 实例→原生协议与能力
ordessa call agents.native.request  --input request.json  --json      # 持久受理，返回 operationRef
ordessa call agents.native.query    --input query.json    --json      # 独立进程读取事实
ordessa call agents.native.events   --input events.json   --json      # cursor 分页读取协议事件
ordessa call agents.native.respond  --input respond.json  --json      # 反向请求只接受一次有效回复
```

`agents.native.request` 的 `nativeMessage` 是提供方原生消息（如 Codex 的 `turn/start`），
平台不再为每个细碎命令增加专用包装；`query` 的 `state` 为 `accepted/completed/failed/refused/unknown`，
进程消失或重启后未决操作只会读成 `unknown`，不会被当成仍存活。

## 当前边界（明确未完成）

以下缺口都有登记与负责人，不用演示替代结论（详见[已知问题](docs/reference/known-issues.md)）：

- **长任务的异步提交与轮询**：`agents.native.request` 已按"持久受理 + 独立进程查询/游标事件"实现，
  CLI 断开后工作仍由 Server owner 持有；真实 Codex 回合已测到 103 秒、提交 0.36 秒返回、93 条事件可游标读回，
  同一 thread 的第二回合不重放；`agents.prompt` 便利入口仍是同步等待（有活动原生运行时时明确拒绝，避免第二个 reader）。
  运行中取消与强制停止已实测：cancel 通知≠停止，进程停止后未决回合显式记为 `unknown`。
- **工具权限回传**：原生反向请求会被记录、可查询并只接受一次有效回复（受控测试通过）；
  真实品牌回合中尚未触发审批请求通道，因此真实分支未验证。
- **沙箱内 exec/files**：OpenShell 沙箱已通过正式 Server/CLI 完成真实 create/exec/files/策略允许与拒绝/按身份清理；
  沙箱内 Codex、Pi 的**真实修复任务**也已完成（`codex-app-server/1`、`pi-rpc/1`：改源码→跑测试→宿主 6 passed）。
  注意：沙箱网络策略必须包含二进制白名单（如 `binaries: [{path: /usr/local/bin/node}]`），
  否则 gateway 会拒绝所有出站连接；Codex 在沙箱内需 `sandbox: danger-full-access`（外层为共享宿主内核的容器；best-effort 策略的有效隔离能力以验收报告为准）。
- **品牌覆盖**：Codex 与 Pi 已在 Local 环境通过正式 Server/CLI 完成同一冻结修复任务并由宿主独立验证；
  Kilo／Claude 有历史真实回合记录；Hermes 需要 reviewed 配置与 runtime 投放；其他品牌未跑真实任务。
- **Units 退役**：`packages/execution/units` 及旧上层装配仍在源码中，默认安装不依赖，但全仓退役未完成。

## 继续阅读

- [产品定位与方法背景](docs/reference/engineering-platform-positioning.md)：完整目标、DID 与 Spec Kit 文档组织方式的关系；其中实现状态表保留了较早阶段的记录。
- [工程组织与模块边界规范](docs/standards/engineering-standard.md)：职责归属、依赖方向与迁移要求。
- [进展与交付规范](docs/standards/progress-and-delivery-standard.md)：如何区分实现、联调、验收与交付。
- [已知问题](docs/reference/known-issues.md)：已有问题及未验证范围。
- [迁移资料](docs/migration/README.md)与[历史参考索引](docs/reference/index.md)：历史标识、来源及恢复说明。

方法资源采用了 GitHub Spec Kit 的部分文档组织方式和模板；相关复用说明见[定位文档](docs/reference/engineering-platform-positioning.md#复用与许可证声明)。各第三方实现与资源遵循其自身许可证和来源声明。
