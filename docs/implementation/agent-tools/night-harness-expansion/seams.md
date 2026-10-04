# N001 冻结接缝与目录 owner（家族单元并行边界）

冻结时间：2026-10-04。冻结人：主执行者。本文件是 N002–N011 家族单元的唯一写权边界依据；冲突以本文件为准。

## 1. 家族 id 盘点（不删原8、不改历史身份）

| catalog familyId | harness模块目录 | 本批角色 | 备注 |
| --- | --- | --- | --- |
| claude-code | `plugins/harness/src/ordessa_harness/claude/` | N005 目标（已存在） | 原8家族身份保留 |
| codex | `.../codex/` | N002 目标（已存在） | 原8家族身份保留 |
| dsh | `.../dsh/` | 保留不动 | 原8家族，非本批目标 |
| hermes | `.../hermes/` | 保留不动 | 原8家族，非本批目标 |
| kilo | `.../kilo/` | 保留不动 | 原8家族，非本批目标 |
| opencode | `.../opencode/` | N004 目标（已存在） | 原8家族身份保留 |
| pi | `.../pi/` | N003 目标（已存在） | 原8家族身份保留 |
| qwen | `.../qwen/` | N007 目标（已存在） | 原8家族身份保留 |
| kimi | `.../kimi/`（新建） | N006 | 新目录，归plugins/harness |
| gemini-cli | `.../gemini_cli/`（新建） | N008 | id带连字符、模块下划线 |
| copilot | `.../copilot/`（新建） | N009 | 新目录 |
| goose | `.../goose/`（新建） | N010 | 新目录 |
| vibe | `.../vibe/`（新建） | N011 | Mistral Vibe |

命令目录权威仍是 Harness 公开面 `ordessa_harness_api.command_discovery`（新增家族id由主执行者在 N012 统一登记并重生成 `harness_commands.json` 镜像；家族单元只提交登记请求，不改共享文件）。

## 2. 共享接缝（主执行者独占；家族单元只读消费）

| 接缝 | 位置 | 状态 | 说明 |
| --- | --- | --- | --- |
| stdio/JSON-RPC传输 | `products/agent-tools/src/ordessa_agent_tools/native_clients/_transport.py` | **已冻结** | FrameReader（G5：字节换行、增量UTF-8、帧上限、截断typed失败）、ProcessChannel（owned进程清理G8、LostReceipt/RequestTimeout不重发G11、on_request反向请求保身份G4）、isolated_env/LaunchSpec（G12：钉定HOME/XDG/LANG，token键剔除） |
| loopback HTTP/SSE | `.../native_clients/_http.py` | **已冻结** | LoopbackHttpChannel（仅环回G9/G12、无redirect、无自动重试G11）、SseEvent原生身份保留G4、SSE分帧与typed失败G5 |
| 客户端包面 | `.../native_clients/__init__.py` | **已冻结** | 只重导出上述接缝；**刻意无家族注册表**（避免平行注册器，catalog归Harness） |
| Harness命令目录 | `plugins/harness/api/src/ordessa_harness_api/command_discovery.py` | 只读（N012主执行者扩） | 家族单元不得改 |
| 命令/schema生成镜像 | `products/agent-tools/{packaging/generate_harness_catalog.py,packaging/generate_schema.py,src/ordessa_agent_tools/harness_commands.json,src/ordessa_agent_tools/schema.json}` | 只读 | 同上 |
| Harness家族注册 | `plugins/harness/src/ordessa_harness/harnesses.toml`、`launch-descriptors.json`、`adapters/__init__.py` | 只读 | 新家族登记请求写家族报告，N012统一并入 |
| 配置公开点位 | `plugins/harness/src/ordessa_harness/contributions.py` | 只读 | 家族配置适配器经此点位发布，不得另建点位 |
| 共享传输收敛 | server_acp/server-compat/JS bridge/Go acp-adapter | 只读 | 「只有实际复用才抽取」；本批不新增global singleton |

## 3. 家族单元可写范围（每单并行单元）

```
plugins/harness/src/ordessa_harness/<family_dir>/          # 仅本家族目录
plugins/harness/tests/<family_id>/                          # 仅本家族测试
products/agent-tools/src/ordessa_agent_tools/native_clients/<family>.py   # 仅本家族客户端模块
products/agent-tools/tests/native_clients/test_<family>.py               # 仅本家族测试
docs/implementation/agent-tools/night-harness-expansion/evidence/<family_id>-*.md  # 仅本家族证据
```

禁止：共享接缝/registry/schema/CLI主入口/status/Git/其他家族目录；禁止开子代理；禁止git操作、共享editable安装、全集测试（主执行者亲自复跑）。

## 4. 每家族最小交付形状

**Harness侧** `plugins/harness/src/ordessa_harness/<family_dir>/native_channel.py`（家族自有；沿既有家族边界扩充，不造平行注册器）：

- `FAMILY_ID: str`（§1的catalog id）
- `channel_report() -> dict`：upstream/许可、固定release或完整SHA、artifact digest（本机实物则sha256）、协议schema来源、启动参数、隔离目录与状态位置、默认网络行为、认证引用方式、session创建/恢复、配置能力、双向回调、取消/结束、unknown扩展与升级边界
- `plan_launch(*, home, workspace, ...) -> dict`：受控argv/env/cwd计划（不执行）
- `compile_config(materials) -> dict`：配置编译owner（G3：unsupported发前拒，不静默吞）
- `capability_matrix() -> dict[str, dict]`：每能力 declared/implemented/observed 三态；unsupported给证据，未实测写unknown

**products侧** `products/agent-tools/src/ordessa_agent_tools/native_clients/<family>.py`：

- `FAMILY_ID: str`
- `class <Family>Client`：经冻结transport调用可执行原生入口——`connect/initialize`（真实握手）、`create_session`（原生会话未建立保留prepare中间态，**不伪造sessionId**）、`send`、`events`（未知method/event原样保留G4）、`cancel`、`close`（只释放自身连接G8）
- `describe() -> dict`：通道/协议/版本事实，不含runtimeReady断言

**测试**：定向正反例（陌生event、失回执、重放callback、两node交叉、缺必需配置→发前拒、framing反例）；fixture须标L1，不得冒L2。测试不得把不存在的命令硬编码为成功。

**证据**：`evidence/<family_id>-channel-report.md`（L0钉版+决策）＋矩阵行（acceptance.md §每家矩阵的列）；L2实测仅主执行者可做（见README本夜权限），家族单元只登记「未测」。

## 5. 运行接纳前置（依赖阻塞登记）

节点准备、原生session reservation、InputAttempt、transport fence、InvocationAuthority/CurrentState 生产接线、DirectoryBinding 生产注册均**未交付**（见 `evidence/N001-source-snapshot.md`）。因此：

- 家族交付终态上限＝CODE_READY（适配实现/协议验证）＋可选L0；
- 任何家族不得发布 runtimeReady=true，不得声称 NATIVE_VERIFIED/PRODUCT_VERIFIED；
- 管理绑定（节点/任务/持久attempt）标依赖阻塞（029 AT-009/010/011），不得另造core/ledger绕开。
