# Q4 T011（受管 Streamable-HTTP client）：remote 格的 L2 补齐 + 变异审计

日期：2026-09-29。线：Q4 `codex/011-q4-mcp` 受管子代理（T011）。
基线 HEAD：`49dfa61522`（`git rev-parse --short=10 HEAD` 实取）。
运行环境：`.venv/bin/python` = Python 3.12.14（`-c` 内联，未新装任何包；openssl 在 PATH，TLS 格实跑非 skip）。
无任何 git 写操作；改动面见 §6。**本批 = L2**（受控 loopback fake，非真实产品 server）；Pi 格仍等 harness-api（G4/T013）；真实外部服务 = L4，不属本批。

## 0. 证据级别（先说死）

受管 HTTP client（`HttpManagedClient`）驱动对**自带进程内 fake Streamable-HTTP MCP server**
（`tests/managed_http/fake_http_mcp.py`，`127.0.0.1:0`，可 TLS 包裹）完成
initialize/tools-list/tools-call/close-cancel 全回合与全部反例；见证一律取 **server 侧账本**
（accepted connections、每 initialize 新发 session id、逐帧记录、执行 call 计数），
不是 client 自报。真实产品 MCP server 连接数：仍然为零。

## 1. 落盘物与关键符号（file:line，前缀 `plugins/assets/mcp/`）

| 文件 | 内容 |
| --- | --- |
| `backend/managed/client_http.py`（新，728 行） | `HttpClientPolicy`（:112，默认最严：https 强制+回环精确主机例外可关、`max_response_bytes=64KiB`、双超时、`ca_bundle` 是唯一信任锚参数、**无**关闭校验字段）；`evaluate_remote_url`（:150，probe.py:249 的精确主机判法，`127.0.0.1.evil.test` 在任何 socket 前类型化拒绝）；`HttpManagedClient`（:182）实现 `ManagedClientPort`：`start`（:257，先握手零应用字节）、`connect`（:279，记录**实际**协商版本+`Mcp-Session-Id` 仅存实例）、`list_tools`（:351）、`call_tool`（:366，唯一副作用路）、`close`（:391，幂等、只关本地、清 plan/port/session id，close 事实 `remoteServiceLifecycle:"not-owned"` :108）、`_hang_up`（:419，SHUT_RDWR 唤醒在途 reader=HTTP 侧取消）、`_request_headers`（:437，**瞬时解析**：明文只活在递交 http.client 的局部 dict，`resolve_for_launch` 每请求一次）、`_assert_origin`（:502，逐请求 origin/host 一致性）、`_post`（:580，写帧前=确认拒、写帧后=unconfirmed 的轴心分界）、`_read_bounded`（:654 区段，字节上限+wall-clock 双闸+SSE data 行提取）；`make_http_client_factory`（:693，每 lease 全新实例、零缓存）。client 本地码族 `MCP_HTTP_*`（:101-105）在此登记；`ClientRequestUnconfirmed`/`MCP_CLIENT_*`/版本表**复用** client_stdio 的同名件，taxonomy 单源 |
| `backend/managed/session_manager.py`（改，**仅文档串/注释**） | 模块 docstring：指明两个限定替代 driver（stdio + http）均存在；`ClientFactory` 注释（:88-91）：两 transport 工厂形状+零池化，钉 SDK 仍归 C0 裁定。`git diff` 全文只含注释/docstring 行，逻辑零改动（主代理审差可按 §6 diff 过滤验证） |
| `tests/managed_http/`（新） | `conftest.py`（autouse 解禁照 tests/probe 口径，仅重绑真实 socket/subprocess；`endpoint` 工厂 fixture 收敛所有 fake server；`self_signed_tls` session fixture，openssl 缺失即红不 skip）、`fake_http_mcp.py`（11 模式受控对端+server 侧账本）、`http_helpers.py`（`FakeCredentialPort`/`make_plan`/`HttpRealFactory`/`SENTINEL`/`plaintext_hits` 深扫）、6 个测试文件 **33 ID** |

授权缝（需求 2）：声明 `SecretRef` header 而无 plan/port → **构造即** `SECRET_UNRESOLVED`（fail-closed，
对齐 stdio :514 规则）；plan 缺槽绑定/轮换(`PLAN_STALE`)/撤销(`SECRET_UNRESOLVED`)/过期(`PLAN_STALE`)
全部发生在 `_request_headers`，**先于任何字节上线**（server 账本零请求为证）。与 probe 的分工：
受控 probe 永不带凭据（`credentialScope:"unproven"`），live 受管 client 才可带**瞬时解析**的授权 header——
两型各有独立测试锚。

## 2. L2 测试格（33 ID，均含 server 侧见证断言）

- **全回合**（test_http_roundtrip.py 6 ID）：manager 全程驱动下
  connected 事实 `negotiatedProtocolVersion=2025-11-25` 与降级格 `2024-11-05`（记录**实际答案**）、
  `MCP-Protocol-Version`/`Mcp-Session-Id` header 上线核验、initialized 通知到达、
  批准→调用→close 幂等且 `sessionIdDropped`；mismatch/`init_error` → `PROTOCOL_MISMATCH`
  且 server 只见 1 帧、本地会话已关；SSE 帧型 tools/list 接受；stdio lease 走 HTTP 工厂
  → `MCP_TRANSPORT_UNSUPPORTED` 显式拒。
- **两会话一 URL 零池化**（test_isolation_no_pooling.py 2 ID）：server 侧 connections==2、
  sessions_issued 两个互异且各自 call 帧只呈己方 session；A 关 B 继续（第三次 call 仍 B session）；
  工厂三连产三实例（含 `produced` 见证 + 产端零网络）。
- **双门前置**（test_http_gate_zero_side_effect.py 4 ID，含**正控制**）：授权放行时 server call 计数确实变 1；
  拒权(`PERMISSION_REFUSED`)/缺权(`PERMISSION_AUTHORITY_ABSENT`)/未批准工具（authority 都未被问）三格
  server 侧 `tools/call` 计数 0。门形沿用注入：真实 `ManagedSessionManager`+fake authority 组合。
- **瞬时授权**（test_auth_ephemeral.py 9 ID）：SENTINEL 逐请求上线（initialize/list/call 都带、
  `port.reads>=3` 证明确实每刻重解析）而事件/lease 事实/返回值/client 实例态/repr 深扫全净；
  无 plan 构造拒（server 零帧）、缺槽绑定拒（消息点名槽不点值）、轮换 stale 拒、撤销拒、过期计划
  **不触 store**（reads==0）、close 后 plan/port 引用清空且再取头 fail-closed、server 401 →
  `AUTH_REQUIRED` 确认拒（不重试、消息无明文）、无声明 header 的 client 不带任何 Authorization
  （绝不 ambient）。
- **安全策略**（test_http_policy.py 4 ID）：精确回环 vs 前缀伪造 vs 非回环明文 vs 未知 scheme
  四型；例外本身可关（`allow_loopback_http=False`）；302 → `MCP_HTTP_REDIRECT_REFUSED` 且
  `/moved` 从未被请求；运行中篡改 `_host` → 下一帧写前 `MCP_HTTP_HOST_ORIGIN_MISMATCH`，server 计数不动。
- **TLS**（test_tls.py 2 ID）：自签 fake 上注入 `ca_bundle` 完成真握手全回合；缺省信任库对同一
  证书在 `start()`（零应用字节）即 `CONNECTION_FAILED`，server 应用帧计数 0。
- **未知结局/取消**（test_failures_unknown_outcome.py 6 ID）：initialize 超时 → manager
  `UNKNOWN_OUTCOME`、lease 停 `unknown`、同 key 再开 lease 被 `MCP_RECONCILE_REQUIRED` 拦、
  reconcile(terminated) 出且 server 端 initialize 仍只 1 次（无自动重试）；超限帧/坏 JSON/
  JSON-RPC error 应答三格皆 `ClientRequestUnconfirmed`（不是伪确认）；在途 call 中 `close()`
  即时唤醒 reader 并以 unconfirmed 收束（≤3s 线程回收）；close 事实恰为
  `{localSessionClosed,sessionIdDropped,remoteServiceLifecycle:"not-owned"}` 且随后一个**新**
  裸 HTTP 连接仍被 fake 服务（远端未被本插件停机的不对称证据）。

## 3. 与 stdio client 的差异表

| 维度 | client_stdio（T05） | client_http（本批） |
| --- | --- | --- |
| 拥有的资源 | 子进程组（SIGTERM→grace→SIGKILL 整组收尸） | 仅本地 TCP/TLS 连接；远端服务 **not-owned**，close 不声称停机 |
| 会话 | 一 lease 一子进程 | 一实例一 HTTP 连接+服务器所发 session id（仅存实例，close 即弃） |
| 凭据注入 | spawn 时 `secret_resolver` 进子进程 env（allowlist） | 每请求瞬间 `resolve_for_launch` 进 header 局部 dict（plan/port 为 T07 形状） |
| 传输失败分界 | 写帧前/后 | 同一轴心：`request()` 起即视为已上线（partial write 也算），unconfirmed |
| HTTP 特有策略面 | — | https 强制+精确回环例外、拒 3xx、origin 一致性、`MCP-Protocol-Version` 协商后携带、TLS 校验无开关 |
| 状态码语义 | 无 | 401/403=确认拒(`AUTH_REQUIRED`)、其余 4xx=确认拒、5xx=unconfirmed、JSON-RPC error(call/list)=unconfirmed（与 stdio 对齐） |
| 取消 | close 唤醒 pending reader 线程 | close `SHUT_RDWR` 挂断唤醒阻塞 reader |
| 共用件 | — | `ClientRequestUnconfirmed`、`MCP_CLIENT_*`、版本表均 import 自 client_stdio，单一分类源 |

## 4. 变异审计（红 − control）

方法同 t05-client §4：临时改产品码，跑后即时恢复，`grep -rn MUTATION` 零命中为恢复凭据。

| # | 变异 | 运行 | 结果（真实退出码） | 归因 |
| --- | --- | --- | --- | --- |
| M1 | `_request_headers` 末尾缓存 `self._last_resolved=dict(out)`（旁路"瞬时清场"） | managed_http | **2 failed, 31 passed, exit 1**。红：`test_auth_ephemeral.py::test_secret_header_reaches_server_and_plaintext_stays_everywhere_else`、`::test_close_clears_every_credential_reference`（深扫实例态命中 SENTINEL） | 新增格，无 control 账 |
| M2 | session_manager `if decision.status != STATUS_ALLOWED:` → `if False and ...`（旁路统一权限门） | 三目录 | **6 failed, 95 passed, exit 1**。红 − control = managed_http 两格 `test_http_gate_zero_side_effect.py::test_denying_authority_means_the_server_never_sees_a_call`、`::test_absent_authority_fails_closed_with_zero_server_calls`（**server 侧计数断言**变红）。control（t05-client §4 已登记的 4 ID 原样复现）：tests/managed/test_call_gate.py 两格 + tests/managed_client/test_gate_zero_side_effect.py 两格 | 每 http 格独立成立：拒绝被旁路后 fake 真收了 tools/call |
| M3 | 工厂按 endpoint_fingerprint 缓存复用实例（引入池化） | managed_http | **3 failed, 30 passed, exit 1**。红：`test_isolation_no_pooling.py::test_two_sessions_one_url_get_two_independent_http_sessions`、`::test_factory_always_produces_a_fresh_instance`、`test_auth_ephemeral.py::test_unauthorized_plain_client_never_inherits_ambient_credentials`（第二格同指纹命中缓存） | 池化守卫非摆设 |

恢复后三目录复跑 → **101 passed, exit 0**（见 §5）。

## 5. 真实退出码 / 收集数（PIPESTATUS 实取，非 tail 状态）

| 命令（`.venv/bin/python -m pytest …`，工作树根） | 结果 |
| --- | --- |
| `tests/managed_http tests/managed tests/managed_client -q`（dispatch 命令，恢复变异后） | **101 passed**, exit **0**, 20.75s（33 新 + 既有 68 不破坏） |
| 同上（测试文件改名后终验复跑） | **101 passed**, exit **0**, 20.41s |
| `tests/managed_http -q --collect-only` | **33 ID**, exit 0 |
| `tests/managed_http -q`（独立复跑，稳度复核） | 33 passed, exit 0, 16.04s |
| 变异体 | 见 §4（exit 均 1） |

红账：无未解释红。全目录（tests/service、probe、permissions、permission_adapter、adapters、
migration、前端）由主代理跑；本批对既有目录的仅有触点为 session_manager 注释（零逻辑）与新文件，
无既有测试文件被改动。fake 端点全部 `127.0.0.1:0`，进程内线程 server 由 fixture 关闭。

## 6. 改动面（git status --short 实录）

```
 M plugins/assets/mcp/backend/managed/session_manager.py   （仅 docstring/注释，diff 可过滤验证）
?? plugins/assets/mcp/backend/managed/client_http.py
?? plugins/assets/mcp/tests/managed_http/
```
（另：本报告 `specs/011-q4-mcp/reports/t011-http-client.md`。tasks.md T011 勾选由主代理在全绿后处理。
根 package/package-lock、products、其他线文件未触。测试文件名 `test_roundtrip.py`/
`test_gate_zero_side_effect.py` 因与 managed_client 目录 basename 冲突（rootdir 无 `__init__.py`
收集器 import 互踩）改名为 `test_http_*`，属本目录自有件。）

## 7. 边界与如实缺口

- 仍是**限定替代**：仅 initialize/tools-list/tools-call/close-cancel 子集 + 协商后
  `MCP-Protocol-Version`/`Mcp-Session-Id` 头；无 server→client 通道（GET-SSE 流）、无断线重连
  （受限重连属 manager/port 后续）、无分页 cursor 语义（server 一次给全）。升格官方 SDK 路线
  归 C0（integration-request 条目 10）。
- "401/403=工具未执行"是对端行为假设（受控 fake 证实该型）；真实 server 若违约，最坏是本批把
  可确认拒当确认拒——L4 批次需以真对端复验，此假设已在码注释与本节登记。
- Pi 格（managed 面挂 Pi extension）不属本文件：升格 L3 需 harness-api 批（T013/G4）；
  真实产品 MCP server 取证 = L4，需用户单独授权，不属本批。
- 装配点未默认注入 http 工厂（与 stdio 同口径：`client_factory` 由调用方注入，
  service/plugin 组装默认 None 的 fail-closed 语义未动）；`LaunchPlan` 冻结面（principal/session/
  bindings）到 T09 装配的接线属 C2/T13 线。
- TLS 信任锚只支持单一 `ca_bundle` 文件（无 SSLKEYLOG/代理面）；`check_hostname` 恒开。
