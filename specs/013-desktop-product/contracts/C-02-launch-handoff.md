# C-02 — 启动交接与进程生命周期（LaunchHandoff）

**面向**：对内（非插件 API）　**定义方**：P-B　**消费方**：P-A
**状态**：冻结

## 目的

规定 **Desktop 宿主**如何启动并监管 **Server**，以及两者之间传递哪些事实。既有连接器（`plugins/connectors/ordessa/src/target.ts`、`plugins/connectors/acp/src/native.ts`）已经用拒绝语义把接口写死，本契约照实冻结。

## 1. 责任划分（constitution 2「一个进程一个终止责任方」）

```text
Desktop 宿主（P-A 持有，P-B 提供模块）
├── 解析数据根（C-01）
├── 取得随机 loopback 端口
├── spawn Server 子进程
├── 等待就绪探针
├── 把 origin + token locator 交给扩展宿主
└── 退出时只终止自己 spawn 的 pid（进程组 + 孤儿防护）

Server（P-B）
├── 绑定 127.0.0.1:<随机>
├── 提供 /live 就绪探针
├── 提供 /wire/v1/{method}
└── 不负责自我守护、不负责发现宿主
```

**禁止**：宿主 kill 任何它没 spawn 的进程；Server 自行假设端口；任一侧在未就绪时假装成功。

## 2. 环境交接（既有命名，保持拼写）

宿主在启动扩展宿主前**必须**设置：

| 变量 | 值 | 语义 |
| --- | --- | --- |
| `ORDESSA_SERVER_ORIGIN` | `http://127.0.0.1:<port>` | 仅 origin：无 path/query/fragment/credentials；**必须** http + loopback + 带端口 |
| `ORDESSA_SERVER_TOKEN_FILE` | `$DATA_ROOT/secrets/http-token` | **绝对路径**；只传定位符，**不**传令牌字节 |
| `ORDESSA_DATA_ROOT` | 解析后的绝对路径 | C-01 结果 |

> 连接器的拒绝信息已经写明责任：`ORDESSA_SERVER_ORIGIN is not set` → *"the desktop host must pass the loopback origin of the Server it started"*；`ORDESSA_SERVER_TOKEN_FILE is not set` → *"the desktop host must pass the token locator for the same data-root"*。

**令牌字节只存在于主进程与 Server**；渲染进程与插件只能通过 C-03 拿结果，**不**拿令牌。

## 3. 端口交接与身份（不只是"取得 origin"）

### 3.1 实际端口如何可靠交给 Desktop

Server 绑定随机端口后，实际端口与进程身份必须**可靠**交给宿主。唯一交接机制：

```text
启动握手（Server → 宿主，经 spawn 的 stdout，单行 JSON）
{"event":"listening","origin":"http://127.0.0.1:<port>","serverId":"<id>","pid":<n>}
```

- Server 完成绑定后**只写这一行**到 stdout；其余日志走 C-04 → `server.log`，**不**混入 stdout。
- 宿主读到该行才进入 `probing`；超时未读到 → `SERVER_START_TIMEOUT`。
- 该行必须是**合法单行 JSON**；解析失败 → `SERVER_HANDSHAKE_MALFORMED`（附脱敏后的原始行）。
- **禁止**回退到"扫端口""读临时文件猜端口""假定 8732"。
- stdout 不可用的平台可改用 `$DATA_ROOT/instance.json`（0600，写临时文件后 rename 原子发布），字段同上；**两种机制只实现一种，不并存**。

### 3.2 端口 ≠ 身份（防止把临时端口变化误判为身份变化）

| 概念 | 含义 | 稳定性 |
| --- | --- | --- |
| `origin` | 本次进程的 loopback 地址 `http://127.0.0.1:<port>` | **每次启动可变**（随机端口） |
| `serverId` | 持久 Server 身份，由数据根派生并持久化 | **持久不变** |
| `scope` | `serverInstanceId(origin, serverId)` = `origin\|serverId` | 项目选择作用域 |

- **临时端口变化不得被当成持久身份变化**：项目/会话选择以 `serverId` 为持久身份；`origin` 只用于本次连接寻址。
- 重启后 `origin` 变而 `serverId` 不变 → 既有项目选择**继续有效**。
- 判同/判异一律比较 `serverId`；`scope` 中的 `origin` 部分允许随启动变化。
- **禁止**用 pid 或端口充当持久身份。

### 3.3 端口与失败

- Server **必须**绑定随机 loopback 端口（`127.0.0.1`，端口由系统分配）。
- 端口分配失败 → 类型化错误 `PORT_ALLOCATION_FAILED`，**不**退化为"固定端口硬试"。

## 4. 就绪探针

```text
GET $ORDESSA_SERVER_ORIGIN/live  →  200 {"status":"alive"}
```

- 无需鉴权（仅存活探针，不含数据）。
- 就绪判定 = 探针连续成功；超时默认 **15 秒**（对应 SC-002）。
- 超时/失败 → 进入故障 UI（C-06），**不**空白、**不**假绿（FR-024）。

## 5. 进程生命周期状态机

```text
idle → spawning → probing → ready
                 ↘ failed（可操作错误 + 日志入口）
ready → stopping → stopped
任意态 → crashed（记录 + 可重启）
```

- `stopping` 只针对**自己 spawn 的** pid；先 SIGTERM，超时再 SIGKILL；等待退出后再释放锁。
- 子进程异常退出（非本方发起）→ `crashed` + 记录；可自动重启**一次**，再失败则进故障 UI。
- `before-quit`（C-06）统一触发 `stopping`；清理异常**不**覆盖主因。

## 6. 运行时捆绑解析

宿主解析 Server 可执行入口的顺序（C-09 定义布局）：

```text
1. ORDESSA_BUNDLED_ROOT（开发覆盖）
2. 安装布局 /opt/ordessa/{python,bin,harnesses}
```

缺失（如 `bin/acp` 被误删）→ **启动早期**类型化拒绝 `BUNDLED_RUNTIME_MISSING` 并指名缺失物，**不**进入半可用状态。

## 7. 类型化错误

```text
PORT_ALLOCATION_FAILED     随机端口分配失败
SERVER_START_TIMEOUT       就绪探针超时
SERVER_EXITED_EARLY        子进程在就绪前退出（附退出码 + 日志尾部）
BUNDLED_RUNTIME_MISSING    随包运行时/桥缺失（指名缺失物）
SERVER_CRASHED             运行中崩溃
```

每条含 `reason` + `remedy` + `logRef`（日志定位），**不**含令牌字节。

## 8. 反例清单（必须先红后绿）

1. 端口被占 → 系统改配其他端口仍成功；若分配整体失败 → `PORT_ALLOCATION_FAILED`。
2. 缺 `bin/acp` → 启动早期 `BUNDLED_RUNTIME_MISSING`，**不**进入半可用。
3. 子进程 3 秒即退 → `SERVER_EXITED_EARLY`，含退出码与日志尾部。
4. 就绪探针超时 → 故障 UI，**不**空白窗口。
5. 宿主退出 → **只**杀自己 spawn 的 pid；同机另一无关进程存活。
6. 二次启动 → 聚焦既有窗口，**不** spawn 第二个 Server。
7. 金丝雀：整个启动链路日志中令牌字节**零命中**。
