# C-07 — 命令与快捷键（Commands & Keybindings）🔌 插件 API

**面向**：🔌 插件公开契约　**定义方**：P-A　**消费方**：插件
**状态**：冻结

## 目的

命令可被**发现、绑定、执行**。既有 `packages/desktop-platform/contracts` 已有 commands source 契约，本契约在其上补齐快捷键绑定层（快捷键只是命令的绑定，**不**另造执行机制）。

## 1. API（复用既有 commands source）

```ts
import type { CommandSource, Command, Keybinding } from '@ordessa/contracts'

interface Command {
  readonly id: string            // 稳定 id，如 "ordessa.chat.send"
  readonly title: string         // 人话标题（命令面板显示）
  readonly category?: string     // 分组，如 "Chat" / "View"
  readonly when?: string         // 可用条件（上下文表达式，缺省恒可用）
  readonly defaultKeybinding?: string  // 如 "Mod+Enter"
  run(args?: Readonly<Record<string, unknown>>): void | Promise<void>
}

interface Keybinding {
  readonly commandId: string
  readonly key: string           // "Mod+Enter" / "Ctrl+Shift+P"
  readonly when?: string
}
```

`CommandSource` 沿用既有注册/注销/查询契约；本节只定义**新增**的快捷键语义。

## 2. 快捷键语法

| 记号 | 含义 |
| --- | --- |
| `Mod` | 平台主键：Linux/Windows = `Ctrl`，macOS = `Cmd` |
| `Ctrl` / `Shift` / `Alt` | 显式修饰键 |
| `+` | 组合 |
| `,` | 顺序序列（如 `Ctrl+K, Ctrl+S`） |

- 解析失败 → **拒绝注册**并给类型化错误，**不**静默忽略。
- 冲突（同组合绑多个命令）→ 后注册者**拒绝**并报冲突，**不**静默覆盖。

## 3. 发现与执行

- **命令面板**（`Mod+Shift+P`）：列出全部可用命令（按 `when` 过滤），可搜索、可执行、显示绑定。
- **快捷键表**（设置页）：列出全部绑定，可查看、可改绑（本期：可改绑并持久化；改绑冲突同样拒绝）。
- `when` 求值为假 → 命令**隐藏/禁用**（不显示为可点但失败）。

## 4. 三态与失败

| 情形 | 行为 |
| --- | --- |
| 命令不存在 | `Refused` + `reason: "command-absent"` |
| `when` 为假 | `Refused` + `reason: "command-unavailable"` |
| 执行抛异常 | 捕获 + 记日志 + UI 显示错误；**不**崩、**不**静默 |
| 宿主未就绪 | `Unknown` + `reason: "host-not-ready"` |

**禁止**：执行失败静默回退；异常冒泡到窗口。

## 5. 卸载与缺席

- 提供者卸载 → 其命令**消失**，绑定**保留但标记 unbound**（重装后恢复）。
- 未知命令绑定（提供者缺席）→ **不**报错崩，标记 `unknown` 并保留配置。

## 6. 键盘可达（FR-044）

主要路径必须键盘可达：导航、发送、对话框、设置、命令面板、错误关闭。验收以**键盘全流程**走通为准，不以"有 tabIndex"为准。

## 7. 反例清单（必须先红后绿）

1. 注册 `Mod+Enter` 两次（不同命令）→ 后者被拒，报冲突。
2. 非法快捷键字符串 → 拒绝注册 + 类型化错误。
3. 命令执行抛异常 → UI 显示错误 + 日志留痕，应用继续可用。
4. 卸载提供者 → 命令从面板消失，绑定标记 unbound；重装后恢复。
5. `when` 为假 → 命令不可见/不可执行。
6. 键盘全流程：无鼠标完成"打开命令面板 → 执行命令 → 关闭对话框"。
