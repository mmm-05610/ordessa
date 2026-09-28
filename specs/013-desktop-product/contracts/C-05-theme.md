# C-05 — 主题（ThemeService）🔌 插件 API

**面向**：🔌 插件公开契约　**定义方**：P-A　**消费方**：插件
**状态**：冻结

## 目的

收敛现有**两套**主题实现（`packages/workbench/src/styles.ts` 与 `plugins/chat/frontend/src/theme.ts`），使宿主与全部插件贡献界面一致生效。不统一则每次切主题必有局部残留旧色。

## 1. API

```ts
import type { ThemeService, ThemeMode, ThemeTokens } from '@ordessa/contracts'

type ThemeMode = 'light' | 'dark' | 'system'

interface ThemeService {
  /** 当前解析后的实际模式（system 已解析为 light/dark） */
  readonly resolved: 'light' | 'dark'
  /** 用户选择（可能是 system） */
  readonly mode: ThemeMode
  /** 只读设计令牌：颜色/间距/圆角/字体/层级 */
  readonly tokens: ThemeTokens
  /** 订阅变化；返回退订函数 */
  subscribe(listener: (tokens: ThemeTokens, resolved: 'light' | 'dark') => void): () => void
}

interface ThemeTokens {
  readonly color: Readonly<{ bg: string; surface: string; text: string; muted: string;
    border: string; accent: string; danger: string; warn: string; ok: string }>
  readonly space: Readonly<{ xs: string; sm: string; md: string; lg: string }>
  readonly radius: Readonly<{ sm: string; md: string; lg: string }>
  readonly font: Readonly<{ body: string; mono: string }>
  readonly z: Readonly<{ dropdown: string; modal: string; toast: string }>
}
```

**不变量**：`ThemeTokens` 全部 `readonly` 深层不可变；变更产生**新对象**（不原地改）。

## 2. 消费方式（三选一，禁止第四种）

1. **CSS 变量**（推荐）：宿主把 tokens 写入 `:root` 的 CSS 自定义属性；插件样式只引用变量名。
2. **`subscribe`**：需要计算样式时订阅。
3. **设计令牌直接读**：静态取值。

**禁止**：插件自带 `prefers-color-scheme` 分支、自带硬编码色板、自带暗色开关状态。

## 3. 迁移既有两套

- `packages/workbench/src/styles.ts` → 改为**消费** C-05（P-A 负责）。
- `plugins/chat/frontend/src/theme.ts` → 改为**消费** C-05。**注意**：`plugins/chat/**` 属 Z2 写入面，本期由 P-A 提供契约与迁移指引，实际改动**须申报**（见 plan.md §写入面纪律）。
- 迁移后必须有**对照测试**：同一页面在两模式下的关键色值来自 tokens，而非插件常量。

## 4. 系统模式

- `mode === 'system'` 时跟随 `prefers-color-scheme`，系统变化实时生效。
- 显式 `light`/`dark` 覆盖系统。
- 设置项持久化（C-06），重启后保持。

## 5. 缺席与未就绪

- ThemeService 未就绪 → 返回**中性默认令牌**（可用、非空），并 `resolved = 'light'`；**不**崩、**不**让界面无色。
- 令牌字段缺失 → 用默认值补齐，**不**抛异常。

## 6. 反例清单（必须先红后绿）

1. 切 `dark` → 宿主 + 受控第三方 fixture 插件界面**同时**变色（无残留）。
2. `system` 模式下系统切暗 → 实时跟随。
3. 插件硬编码色值（注入反例）→ 对照测试判别为违规。
4. 订阅者抛异常 → **不**影响其他订阅者与主流程。
5. tokens 被尝试修改 → 运行时冻结，修改不生效（Object.isFrozen 断言）。
