# Q4 T05（受管 client）：限定替代 stdio client 的实际可达 L2 证据 + D5 双 Protocol 统一

日期：2026-09-28（深夜批）。线：Q4 `codex/011-q4-mcp` 受管子代理（T05-client）。
基线 HEAD：`9d6c89e273`。运行环境：`.venv/bin/python` = Python 3.12.14。
无任何 git 写操作；改动面见 §6。

## 0. 证据级别（先说死）

**本批 = L2，品牌无关的 SDK client 层**：受管 client 由注入式
`ManagedClientPort` 驱动，对**自带受控 fake MCP server**（`fake_mcp_server.py`，
loopback stdio 子进程，非真实产品 server）完成
initialize/tools-list/tools-call/close 全回合与全部反例。
**Pi 格不在此**：Pi extension 装载仍等 harness-api（G4）依赖批，本批
**不声称 Pi L3**；client 层品牌无关，任何“已连真实品牌 server”的读法都是误读。
真实产品 MCP server 的一次连接：仍然为零。

## 1. 路线裁定（勘察先行，命令输出为据）

首选 A（树内钉死 TS SDK `@modelcontextprotocol/sdk` 1.29.0）**不可行**，依据：

```
$ node -e "console.log(require.resolve('@modelcontextprotocol/sdk/client/index.js'))"   # 工作树根
Error: Cannot find module '@modelcontextprotocol/sdk/client/index.js'  (code: MODULE_NOT_FOUND, exit=1)
$ ls node_modules/@modelcontextprotocol
ls-exit=2   # 根无 node_modules/该作用域
$ grep -c -i modelcontextprotocol package-lock.json package.json
package-lock.json:0
package.json:0     # 1.29.0 不在根锁闭包内；npm ci 也无法产出该包，故未执行安装
$ grep -rn -i modelcontextprotocol --include=package.json --include=package-lock.json . | grep -v node_modules
（仅命中）plugins/harness/packaging/pi/package-lock.json:47  "@modelcontextprotocol/sdk": "1.29.0"
plugins/harness/packaging/pi/package-lock.json:2397  resolved .../sdk-1.29.0.tgz（harness 工件锁，带 integrity；
根锁零命中；全树无任何已安装的 @modelcontextprotocol 目录）
```

1.29.0 只钉在 **harness 的 packaging 锁**里——那是 harness/C0 的锁面，不在 dispatch
规定的"根 package-lock 闭包"内；引入或跨锁使用均属 C0 裁定（AGENTS.md：不得引入新依赖版本）。
按 dispatch 判据「1.29.0 不在闭包可解析位置→A 不可行，转 B」，本批落
**B：限定替代（limited substitute）**，依据
`docs/design/mcp/research-and-reuse.md`「若与 ACP/Python 进程边界不符…记录限定替代，
禁止临时写全协议」：仅实现 stdio JSON-RPC 的 **initialize 协商 / tools/list /
tools/call / close-cancel** 最小子集，不碰 resources/sampling/elicitation/completions/tasks。
已按批准在 `integration-request.md` 追加条目 10，请 C0 裁定引入官方 Python `mcp`
SDK 或本线复用 TS SDK。

## 2. 落盘物与关键符号（file:line，前缀 `plugins/assets/mcp/`）

| 文件 | 内容 |
| --- | --- |
| `backend/managed/client_stdio.py`（新） | 限定替代 stdio client：`StdioManagedClient`（:128）、`StdioClientPolicy`（:102）、`ClientRequestUnconfirmed`（:92，**非** McpError——写帧后的失败必须映射为 UNKNOWN_OUTCOME）、`stdio_environment`（:514）、`make_stdio_client_factory`（:541，lease→全新 client，零池化）；client 本地码族 `MCP_CLIENT_*`（:80-85）在此登记 |
| `backend/managed/session_manager.py`（改，D5） | 权限缝统一：删除本地 bool 形 `PermissionAuthority` Protocol；改 `from ..permissions import PermissionAuthority, ToolCallDecision, check_tool_callable, STATUS_ALLOWED`（:62）；`call_tool` 缝（:498-516）改为构造 managed lane 门快照（frozen 批准集=gate1 名单、`enforcement: proven`）后走**同一个** `check_tool_callable` 双门，非 allowed 一律 `decision.as_error()` 先 raise——client 从未见帧；新增 `preauthorizations` 注入口（:226，走 permissions 的精确绑定复核路径） |
| `tests/managed/managed_helpers.py`（改，最小） | `AllowingAuthority/DenyingAuthority` 返回 `ToolCallDecision`（D5 断言允许的最小更新；接口记录 `seen` 不变） |
| `tests/managed/test_call_gate.py`（改，最小） | authority 缺席码断言 `PERMISSION_REFUSED` → `PERMISSION_AUTHORITY_ABSENT`（permissions 统一语义），消息断言随统一门文案 |
| `tests/managed_client/`（新） | `conftest.py`（照 tests/probe 显式解禁 autouse 封锁，仅重绑真实 Popen/socket）、`fake_mcp_server.py`（受控对端，7 模式）、`client_helpers.py`（`RealClientFactory`、statefile 见证读取、`/proc` 存活判定）、6 个测试文件 17 ID |

`permissions.py`、`service.py` 零改动：统一方向是 session_manager 消费 permissions
的既有形状，`service.py` 未引用该缝（已核：其 PERMISSION_* 引用全在 probe 权柄面）。
`backend/managed/__init__.py` 未动（越界风险最小化）：`PermissionAuthority` 经
session_manager 名字仍再导出可用，新 client 由直接模块路径导入。既有
`lease.py`/`catalog.py`/`errors.py` 语义零改动。

## 3. L2 测试格（17 ID，全部真跑到 fake server 侧见证）

见证 = fake 自己的 statefile（每个收到帧/拒绝/执行 tools/call 都入账）＋
`/proc/<pid>/stat`（psutil 缺位，同 tests/probe 口径；Zombie=已杀未收尸=不运行）。

- **正控制**（防空洞零计数）：`test_gate_zero_side_effect.py::test_positive_control_granted_call_reaches_the_server`
  ——授权通过时 server 端 `call` 计数**确实变 1**；其余拒绝格的"零"由此才有意义。
- **全回合**：`test_roundtrip.py::test_full_roundtrip_through_the_manager`——
  connect 记录实际协商版本（lease 事实 `negotiatedProtocolVersion=2025-11-25` +
  catalog.protocolVersion）、catalog 产 names+`sha256:` schema digests、批准→调用
  （server 侧真执行、参数哨兵 `s3cr3t-arg-body` 只上线路不落 lease 事实/审计）、
  close 后 `/proc` 无残留、二次 close 幂等 replay 且调用不重放。
- **两会话两进程**：`test_two_sessions_two_processes_no_pooling`——factory 每 lease
  一个新实例、pid 互异、关 A 不碰 B（无池化的 OS 级证据）。
- **协商反例**：`test_negotiation.py` 5 ID——
  fake 固定降级应答 2024-11-05 时记录的是**实际答案**非客户端所请；
  不受支持的 offer（1999-01-01）被 fake 拒绝→client 上抛 `PROTOCOL_MISMATCH`
  且先收尸（statefile pid 死透）；manager 驱动 mismatch 模式→lease 诚实 park
  `unknown`、进程零残留；未协商时本地门先拒（**零帧上线**，server 见证无 request 行）；
  **不对称验证 fake 自身**：绕过 client 门直推 tools/list 帧，fake 确实回
  `un-negotiated protocol version` 错误并记账（证明对端守卫是真的，不是 client 自说）。
- **门拒零副作用**：`test_gate_zero_side_effect.py` 4 ID——拒绝权威 / 无权威
  （`PERMISSION_AUTHORITY_ABSENT`）/ 未批准工具（authority 都未被问）三格，
  server 侧 `tools/call` 帧计数为 0。
- **漂移**：`test_catalog_drift.py`——第二次 tools/list 变集→digest 变、
  `catalog-changed` 事实、陈旧批准失效（`CATALOG_CHANGED`），期间 server 调用计数
  停在 1；新工具不自动可调用，重批准后才执行（计数 2，名字对上）。
- **关闭/清理**：`test_close_cleanup.py` 4 ID——close 幂等；tree 模式（孙进程同组）
  **整组回收 `/proc` 断言**（此格抓到并修复了真 bug：leader 协作式 EOF 先退时
  旧收尾逻辑跳过 killpg 致孙进程残留；现在 close 无条件对保存的 pgid 走
  stdin-close→wait→TERM→KILL 升级，client_stdio.py:323）；stubborn（抗 SIGTERM+EOF）
  靠升级 SIGKILL 收净且 close 成功零 cleanup-error；超时慢调用如实落
  `UNKNOWN_OUTCOME`+`call-outcome-unknown` 事实、租约不假成功。
- **在途 drain**：`test_inflight_drain.py`——真在途调用使 close 先 `MCP_LEASE_BUSY`
  （pending manifest 落账），调用落地后重试 close 干净、无重放。

## 4. 变异验证（不对称探针，按 dispatch 要求做到"门失效则红"）

方法：临时把 session_manager.py 的 `if decision.status != STATUS_ALLOWED:` 改为
`if False and ...`（旁路统一权限门），其余门保留。

- 变异体运行（`--tb=no -rf`，真实退出码单列）：`real-exit=1`，
  `4 failed, 64 passed`，红 ID：
  - `tests/managed/test_call_gate.py::test_no_permission_authority_means_no_call_reaches_the_client`
  - `tests/managed/test_call_gate.py::test_denying_authority_blocks_before_any_side_effect`
  - `tests/managed_client/test_gate_zero_side_effect.py::test_denying_authority_means_the_server_never_sees_a_call`
  - `tests/managed_client/test_gate_zero_side_effect.py::test_absent_authority_fails_closed_with_zero_server_calls`
  其中 managed_client 两格是**服务端计数断言**变红（拒绝被旁路后 fake server 真收了
  tools/call），证明 L2 见证不是摆设。
- 恢复：改回原条件，`grep -n MUTATION` 零命中；复跑
  `tests/managed + tests/managed_client` → `real-exit=0`，`68 passed in 5.16s`。

## 5. 真实退出码 / 收集数 / 红账

| 命令 | 结果（真实退出码） |
| --- | --- |
| 基线（改动前）`pytest tests/managed -q` | 51 passed，exit 0 |
| dispatch 命令 `pytest tests/managed tests/managed_client -q`（D5 后复跑 managed） | **68 passed**（51+17），exit 0 |
| `pytest tests/managed_client -q --collect-only` | 17 ID |
| 变异体（旁路门）`pytest tests/managed tests/managed_client -q` | 4 failed 64 passed，exit 1 |
| 恢复后复跑同命令 | 68 passed，exit 0 |
| 全量（本代理面）`pytest plugins/assets/mcp/tests -q` | **263 passed**（原 246 + 新 17），exit 0，18.82s |
| TS 侧 `npx --no-install vitest run` | 未跑：本批零 TS 新增（路线 B，无 node_client 目录） |

红账：无未解释红。tests/permission_adapter、tests/service、tests/probe、tests/permissions
均零改动，由全量 263 覆盖复证。

## 6. 改动面（git status --short 实录）

```
 M plugins/assets/mcp/backend/managed/session_manager.py
 M plugins/assets/mcp/tests/managed/managed_helpers.py
 M plugins/assets/mcp/tests/managed/test_call_gate.py
?? plugins/assets/mcp/backend/managed/client_stdio.py
?? plugins/assets/mcp/tests/managed_client/
```
（另：`specs/011-q4-mcp/reports/t05-client.md` 本报告、`specs/011-q4-mcp/integration-request.md`
末尾追加条目 10。根 package.json/package-lock/products 未触。）

## 7. 限定替代的边界与缺口（如实）

- 仅 stdio 传输的受管连接；remote(Streamable-HTTP) lease 走到 factory 时
  `MCP_TRANSPORT_UNSUPPORTED` 显式拒（client_stdio.py:541 内），不伪装支持。
- 不实现 resources/sampling/elicitation/completion/tasks；协议面停在
  initialize+tools 子集（首版 ManagedClientPort 形状本来如此）。
- 未对任何真实产品 server 取证；L3（真对端）与 Pi 格（harness-api 装载）仍开放。
- `service.py`/plugin 装配点未把 `make_stdio_client_factory` 设为默认注入——装配归
  T09/C0 线（本批 client_factory 仍由调用方注入，测试外默认为 None 的 fail-closed
  语义未动）。
- 生产 secret 注入：factory 接受 `secret_resolver`（T07 端口形状）；未注入时含
  `secretRef` 的 env 是 `SECRET_UNRESOLVED` 拒启（fail-closed，client_stdio.py:514）。
