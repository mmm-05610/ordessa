# C-04 — 日志（Logger）🔌 插件 API

**面向**：🔌 插件公开契约　**定义方**：P-A（TS 实现）/ P-B（Python 实现）　**消费方**：插件 / P-C
**状态**：冻结

## 目的

统一日志机制与**强制脱敏**。不统一则插件各自 `console.log`，令牌泄漏无法防（FR-011 是安全要求）；不强制则依赖调用方自觉，必然漏。

## 1. 插件侧 API

```ts
import type { Logger } from '@ordessa/contracts'

interface Logger {
  debug(msg: string, fields?: Readonly<Record<string, unknown>>): void
  info(msg: string, fields?: Readonly<Record<string, unknown>>): void
  warn(msg: string, fields?: Readonly<Record<string, unknown>>): void
  error(msg: string, fields?: Readonly<Record<string, unknown>>): void
  /** 派生带 scope 的子 logger；scope 形如 "plugin.<id>" */
  child(scope: string): Logger
}
```

- `fields` **只**接受普通 JSON 值；`undefined` 被忽略。
- `child` 可嵌套，scope 用 `.` 连接。
- 调用**永不**抛异常（日志失败不影响主流程，见 §6）。

## 2. 记录格式（TS / Python 同构，JSON Lines）

```json
{"ts":"2026-09-28T12:34:56.789Z","level":"info","scope":"plugin.ordessa.chat","msg":"session started","sessionId":"..."}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ts` | string | ISO-8601 UTC，毫秒精度 |
| `level` | `debug\|info\|warn\|error` | |
| `scope` | string | 命名 scope，如 `host.desktop` / `host.server` / `plugin.<id>` |
| `msg` | string | 人话消息 |
| *其余* | any | 附加字段，**一律经 §4 脱敏** |

> 两侧格式**逐字一致**，以便诊断导出统一解析与时间线合并。

## 3. 落盘与轮转

```text
$DATA_ROOT/logs/
├── desktop.log      ← TS 侧（宿主 + 插件）
├── desktop.log.1 … N
├── server.log       ← Python 侧
└── server.log.1 … N
```

- 按**大小**轮转（默认 10 MiB），保留 **N = 5** 份（含当前）。
- 超出保留数的**删除**，磁盘不得无限增长（SC-004）。
- 由 C-01 定义路径常量；P-C 负责随包/权限。

## 4. 强制脱敏（在 sink 层，不在调用方）

写入前由 sink 统一处理，调用方无法绕过：

1. **字段名规则**：键名匹配（不区分大小写）`token|secret|password|credential|authorization|bearer|apikey|api_key` → 值替换为 `"[redacted]"`。
2. **哨兵规则**：任何字符串值**包含** `$DATA_ROOT/secrets/http-token` 内容即命中（**子串匹配，覆盖正文/消息/嵌入文本/堆栈/URL**）→ 令牌段替换为 `"[redacted]"`；整值等于令牌时整值替换。（同时防换名泄漏与**正文嵌入**泄漏）
3. **路径规则**：`secrets/` 下的文件内容**永不**进入日志或诊断。
4. **定位符规则**：路径型字段最多保留 `basename`。

> ⚠️ 脱敏**不**能只靠调用方注意。实现必须在 sink 统一入口强制，并有金丝雀反例（§8）。

## 5. 诊断收集（与 C-06 联动）

诊断导出收集 `$DATA_ROOT/logs/` 下全部文件，并按 C-04 §2 的 JSON Lines 解析成时间线；**解析失败的行不得原样入包**——必须先经 §4 脱敏再保留，并标记 `parse-failed`（既不丢证据，也不泄漏敏感原文）。

## 6. 失败语义

- 日志写失败（磁盘满/权限）→ **不得**影响主流程；丢弃该条并计数。
- **主流程失败时，日志失败不得覆盖主因**（constitution 2：「清理异常不覆盖主因」）。
- 若日志连续失败达到阈值 → 在 UI 显示"日志不可写"告警，**不**静默。

## 7. 级别与配置

- 默认级别 `info`；可在设置页（C-06）调整为 `debug|info|warn|error`。
- 级别变更**立即**生效，不需重启。
- `debug` 在发行版默认关闭（避免泄漏细节），但可由用户打开。

## 8. 反例清单（必须先红后绿）+ 金丝雀

1. **金丝雀（必须）**：写入 `log.info('x', { token: KNOWN })` → 文件中 `KNOWN` **零命中**，只见 `[redacted]`。
2. **金丝雀（必须）**：字段名改成 `myKey` 但值是令牌字节 → 仍被哨兵规则脱敏。
3. 消息正文含令牌字节 → 同样脱敏（哨兵规则覆盖 `msg`）。
4. 达到 10 MiB → 轮转；生成 `.1`；旧的 `.5` 被删除。
5. 磁盘满 → 主流程仍正常，失败计数递增。
6. 两侧格式一致性测试：同一条记录由 TS 与 Python 写出，字段集与顺序**一致**。
7. 诊断导出中令牌字节**零命中**。
