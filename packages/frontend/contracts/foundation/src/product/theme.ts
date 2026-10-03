/**
 * C-05 — 主题（ThemeService）类型载体。定义方 P-A，消费方插件。
 * 契约文本：`specs/013-desktop-product/contracts/C-05-theme.md`（冻结，只读）。
 */

export type ThemeMode = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'

export interface ThemeColorTokens {
  readonly bg: string
  readonly surface: string
  readonly text: string
  readonly muted: string
  readonly border: string
  readonly accent: string
  readonly danger: string
  readonly warn: string
  readonly ok: string
}

export interface ThemeTokens {
  readonly color: Readonly<ThemeColorTokens>
  readonly space: Readonly<{ xs: string; sm: string; md: string; lg: string }>
  readonly radius: Readonly<{ sm: string; md: string; lg: string }>
  readonly font: Readonly<{ body: string; mono: string }>
  readonly z: Readonly<{ dropdown: string; modal: string; toast: string }>
}

export interface ThemeService {
  /** 用户选择（可能是 system）。 */
  readonly mode: ThemeMode
  /** 当前解析后的实际模式（system 已解析为 light/dark）。 */
  readonly resolved: ResolvedTheme
  /** 只读设计令牌：深层不可变。 */
  readonly tokens: ThemeTokens
  subscribe(listener: (tokens: ThemeTokens, resolved: ResolvedTheme) => void): () => void
  /** C-05 §4：设置项持久化由宿主设置页负责，服务只暴露切换。 */
  setMode(mode: ThemeMode): void
}

/** 缺席/未就绪时的中性默认令牌（C-05 §5：非空可用，`resolved = 'light'`）。 */
export interface NeutralThemeService extends ThemeService {
  readonly mode: 'light'
  readonly resolved: 'light'
}
