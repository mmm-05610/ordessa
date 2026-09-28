# C-03 — wire 传输口（WirePort）🔌 插件 API

**面向**：🔌 插件公开契约　**定义方**：P-B　**消费方**：插件 / P-A
**状态**：冻结

## 目的

插件需要调 Server 的 wire 方法（如 `modelProvider.*`、`profile.*`）。若每个插件自建传输就会各自持令牌（违反 FR-031）。本契约提供**唯一**的 wire 通道：令牌只在主进程/Server 侧，插件只拿类型化结果。

> **REQ-Z3-5 的落地**：Z3 报告登记「桌面 Server wire 传输口——production 绑定归装配」。本契约即该绑定面。

## 1. 传输面（Server 侧，已有）

```text
POST $ORDESSA_SERVER_ORIGIN/wire/v1/{method}
Authorization: Bearer <token>          ← 只由宿主注入，插件不可见
Content-Type: application/json
Body: { "requestId": string, ...params }

Response 200: { requestId, ...result }
Response 200: { requestId, error: { code, message, status, retryable } }
```

- 只接受 loopback（既有中间件 `loopback_policy`）。
- 保持既有 wire 方法名/错误族/ID 语义（`docs/naming.md` 与数据兼容规则）。

## 2. 插件侧 API（宿主提供）

```ts
// 只从公开契约导入，永不 import 宿主内部
import type { WirePort, WireResult } from '@ordessa/contracts'

interface WirePort {
  /** 调用一个 wire 方法。结果是类型化三态，绝不抛裸异常。 */
  call(method: string, params: Readonly<Record<string, unknown>>): Promise<WireResult>
  /** 宿主是否就绪（Server 未起 / 令牌缺席时为 false）。只读事实。 */
  readonly ready: boolean
  /** 只读的 Server 实例范围（origin|serverId），用于项目选择稳定作用域。不含令牌。 */
  readonly scope: string | null
}

type WireResult =
  | { kind: 'Accepted'; requestId: string; result: Readonly<Record<string, unknown>> }
  | { kind: 'Refused';  requestId: string; reason: string; retryable: boolean }
  | { kind: 'Unknown';  requestId: string; reason: string }
```

**不变量**：
- `WireResult` 及其嵌套结构**不可变**。
- `WirePort` **不**暴露 `token`、`tokenFile`、`origin` 之外的任何定位符；`scope` 用 `serverInstanceId(origin, serverId)` 形态（既有实现）。
- 方法名/参数由调用方给出，宿主**不**枚举业务方法（宿主不得出现 `modelProvider`/`profile` 等业务词）。

## 3. 三态语义（全局规则见 README §1）

| 情形 | 返回 |
| --- | --- |
| 正常返回 | `Accepted` |
| Server 明确拒绝（4xx/业务拒绝） | `Refused` + `reason` + `retryable` |
| Server 未就绪 / 令牌缺席 / 网络不可达 / 结果无法确定 | `Unknown` + `reason` |
| 传输中途断开且结果未知 | `Unknown`（**不**重发、**不**冒充成功） |

> **禁止**：把 `Unknown` 折叠成 `Refused`；把 Refused 静默当作成功；重试导致重复副作用（调用方负责幂等键，宿主**不**自动重试）。

## 4. 凭据边界（FR-031，硬门）

- 令牌字节**只**存在于主进程与 Server。
- 插件拿到的 `WirePort` **无法**读取令牌（类型上不暴露，运行时也不注入）。
- 渲染进程通过 IPC 走主进程代理，**不**接触令牌。
- **金丝雀**：注入已知令牌字节，断言插件可见对象、日志、诊断包**零命中**。

## 5. 宿主未就绪

`ready === false` 时 `call()` 返回 `Unknown` + `reason: "host-not-ready"`；**不**排队、**不**阻塞 UI（全局规则 §2）。

## 6. 缺席与卸载

- 宿主未提供 `WirePort`（如裸 Server / 无产品装配）→ 插件侧获得 `AbsentWirePort`，`call()` 恒返回 `Unknown` + `reason: "port-absent"`；**不**崩、**不**假绿。
- 卸载消费者 → 不影响 Port；Port 是宿主单例，不随插件生灭。

## 7. 类型化原因（reason 枚举，可扩展）

```text
host-not-ready      宿主未就绪
port-absent         未提供传输口
transport-unreachable  无法连接 Server
server-refused      Server 明确拒绝（附业务 reason）
result-unknown      传输中断，结果未知
invalid-method      方法名非法（空/含非法字符）
```

## 8. 反例清单（必须先红后绿）

1. 宿主未起 Server → `Unknown/host-not-ready`，**不**抛异常、**不**崩。
2. 令牌文件被删 → `Unknown/transport-unreachable`，且错误信息**不**含完整路径（只 basename）。
3. Server 返回业务拒绝 → `Refused`，`retryable` 正确。
4. 传输中途断开 → `Unknown/result-unknown`，且**不**自动重发。
5. 插件尝试读取令牌 → 类型层不可达 + 运行时断言（金丝雀零命中）。
6. 宿主无产品装配 → `AbsentWirePort`，`call()` 恒 `Unknown/port-absent`。
7. 边界反例：插件 import 宿主内部模块 → 边界测试判别为违规。
