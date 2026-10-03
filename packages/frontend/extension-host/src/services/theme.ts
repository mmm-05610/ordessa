/**
 * C-05 主题服务实现（PA-16）。契约文本：
 * `specs/013-desktop-product/contracts/C-05-theme.md`（冻结，只读）。
 *
 * 这里只做三件事：解析模式（light/dark/system）、产出**深层冻结**的令牌、
 * 把令牌映射成 CSS 自定义属性（C-05 §2 推荐的消费方式）。插件只拿公开契约类型，
 * 不 import 宿主内部模块。
 */

import type {
  ResolvedTheme,
  ThemeMode,
  ThemeService,
  ThemeTokens,
} from '@extensions/ordessa.contracts/contract.js'

export type { ResolvedTheme, ThemeMode, ThemeService, ThemeTokens }

/** 两套调色板：颜色随模式变化，度量（间距/圆角/字体/层级）与模式无关。 */
const PALETTES: Readonly<Record<ResolvedTheme, ThemeTokens>> = {
  light: {
    color: {
      bg: '#f6f7f8',
      surface: '#ffffff',
      text: '#202123',
      muted: '#6b6e73',
      border: '#e2e3e5',
      accent: '#3b82f6',
      danger: '#b3261e',
      warn: '#b26a00',
      ok: '#2e7d46',
    },
    space: { xs: '4px', sm: '8px', md: '14px', lg: '24px' },
    radius: { sm: '6px', md: '8px', lg: '14px' },
    font: {
      body: '13px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif',
      mono: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    },
    z: { dropdown: '1000', modal: '1100', toast: '1200' },
  },
  dark: {
    color: {
      bg: '#151618',
      surface: '#1b1c1e',
      text: '#e6e7e8',
      muted: '#a4a7ac',
      border: '#2c2d31',
      accent: '#60a5fa',
      danger: '#f0776c',
      warn: '#d9a441',
      ok: '#4cc075',
    },
    space: { xs: '4px', sm: '8px', md: '14px', lg: '24px' },
    radius: { sm: '6px', md: '8px', lg: '14px' },
    font: {
      body: '13px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif',
      mono: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    },
    z: { dropdown: '1000', modal: '1100', toast: '1200' },
  },
}

/** 递归冻结：C-05 §1 要求令牌在运行时不可变（Object.isFrozen 逐层成立）。 */
function deepFreeze<T>(value: T): T {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) {
    for (const inner of Object.values(value as Record<string, unknown>)) deepFreeze(inner)
    Object.freeze(value)
  }
  return value
}

/** 令牌被补齐后统一冻结：一次构造、一份不可变快照。 */
function tokensFor(resolved: ResolvedTheme): ThemeTokens {
  const source = PALETTES[resolved] ?? PALETTES.light
  return deepFreeze({
    color: { ...source.color },
    space: { ...source.space },
    radius: { ...source.radius },
    font: { ...source.font },
    z: { ...source.z },
  })
}

/** 缺席/未就绪时的中性默认令牌（C-05 §5）：非空可用。 */
export const NEUTRAL_TOKENS: ThemeTokens = tokensFor('light')

/** 容许令牌被部分提供，用于补齐场景。 */
export type PartialThemeTokens = {
  [K in keyof ThemeTokens]?: Partial<ThemeTokens[K]>
}

/**
 * C-05 §5：令牌字段缺失时用默认值补齐，**不**抛异常。
 * 缺整组走该组默认，缺单字段走单字段默认。
 */
export function completeThemeTokens(
  partial: PartialThemeTokens | null | undefined,
  base: ThemeTokens = NEUTRAL_TOKENS,
): ThemeTokens {
  const pick = <K extends keyof ThemeTokens>(group: K) => ({
    ...(base[group] as Record<string, string>),
    ...((partial?.[group] ?? {}) as Record<string, string>),
  })
  return deepFreeze({
    color: pick('color'),
    space: pick('space'),
    radius: pick('radius'),
    font: pick('font'),
    z: pick('z'),
  } as ThemeTokens)
}

export interface ThemeServiceOptions {
  /** 用户选择，默认 'system'。 */
  mode?: ThemeMode
  /** 宿主提供的系统偏好；默认在可用时读 window.matchMedia。 */
  prefersDark?: () => boolean
  /** 持久化钩子（C-05 §4 设置项持久化），默认空实现。 */
  persist?: (mode: ThemeMode) => void
  /** 每次被接受的变化之后调用，默认空实现。 */
  onChange?: (tokens: ThemeTokens, resolved: ResolvedTheme) => void
}

type Listener = (tokens: ThemeTokens, resolved: ResolvedTheme) => void

/** 默认系统偏好：SSR/测试环境下无 matchMedia 时按亮色处理。 */
function defaultPrefersDark(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  try {
    return window.matchMedia('(prefers-color-scheme: dark)').matches
  } catch {
    return false
  }
}

export function createThemeService(options: ThemeServiceOptions = {}): ThemeService {
  const prefersDark = options.prefersDark ?? defaultPrefersDark
  const persist = options.persist ?? (() => {})
  const onChange = options.onChange ?? (() => {})
  const listeners = new Set<Listener>()

  let mode: ThemeMode = options.mode ?? 'system'
  let resolved: ResolvedTheme = mode === 'system' ? (prefersDark() ? 'dark' : 'light') : mode
  let tokens: ThemeTokens = tokensFor(resolved)

  // C-05 §6.4：单个订阅者抛异常不得影响其他订阅者，也不得影响主流程。
  const notify = (): void => {
    for (const listener of [...listeners]) {
      try {
        listener(tokens, resolved)
      } catch {
        /* 隔离：订阅者的问题由订阅者自己负责 */
      }
    }
    try {
      onChange(tokens, resolved)
    } catch {
      /* 同上，宿主钩子不阻断切换 */
    }
  }

  // 产生新对象而非原地修改（C-05 §1 不变量）。
  const commit = (next: ResolvedTheme): void => {
    if (next === resolved) return
    resolved = next
    tokens = tokensFor(next)
    notify()
  }

  const setMode = (next: ThemeMode): void => {
    if (next !== 'light' && next !== 'dark' && next !== 'system') return
    mode = next
    try {
      persist(mode)
    } catch {
      /* 持久化失败不阻断本次切换 */
    }
    // 显式 light/dark 覆盖系统；system 重新读取当前偏好。
    commit(mode === 'system' ? (prefersDark() ? 'dark' : 'light') : mode)
    if (mode === 'system') syncSystemListener()
  }

  // C-05 §4：system 模式下系统变化实时生效。
  let mediaQuery: MediaQueryList | null = null
  const onSystemChange = (): void => {
    if (mode === 'system') commit(prefersDark() ? 'dark' : 'light')
  }
  const syncSystemListener = (): void => {
    const shouldListen = mode === 'system' && !options.prefersDark
    if (!shouldListen) {
      mediaQuery?.removeEventListener?.('change', onSystemChange)
      mediaQuery = null
      return
    }
    if (mediaQuery || typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
    mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    mediaQuery.addEventListener?.('change', onSystemChange)
  }

  const service: ThemeService = {
    get mode() {
      return mode
    },
    get resolved() {
      return resolved
    },
    get tokens() {
      return tokens
    },
    subscribe(listener: Listener) {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    },
    setMode,
  }

  syncSystemListener()
  return service
}

/**
 * C-05 §5：ThemeService 缺席/未就绪时给中性默认（`resolved = 'light'`），
 * 界面不崩也不无色。
 */
export function createNeutralThemeService(): ThemeService {
  const noop = (): void => {}
  return {
    mode: 'light',
    resolved: 'light',
    tokens: NEUTRAL_TOKENS,
    subscribe: () => noop,
    setMode: noop,
  }
}

/** 令牌字段 → `--ordessa-*` 自定义属性名（C-05 §2 消费方式 1）。 */
export const THEME_CSS_VARIABLE_PREFIX = '--ordessa'

/** 把每个令牌字段映射为一个 `--ordessa-*` CSS 自定义属性。 */
export function themeCssVariables(tokens: ThemeTokens): Record<string, string> {
  const vars: Record<string, string> = {}
  for (const [group, values] of Object.entries(tokens)) {
    for (const [field, value] of Object.entries(values as Record<string, string>)) {
      vars[`${THEME_CSS_VARIABLE_PREFIX}-${group}-${field}`] = value
    }
  }
  return vars
}

/** `style` 上写入/移除自定义属性所需的最小面，便于测试注入。 */
export interface ThemeStyleTarget {
  style: {
    setProperty(key: string, value: string): void
    removeProperty(key: string): void
  }
}

/**
 * 把当前令牌写进目标元素的 `style`，并订阅后续变化。
 * 返回退订兼清理函数：停止订阅并移除全部写入过的自定义属性。
 */
export function applyThemeToDocument(
  service: ThemeService,
  target: ThemeStyleTarget = globalThis.document?.documentElement as ThemeStyleTarget,
): () => void {
  const write = (tokens: ThemeTokens): void => {
    const vars = themeCssVariables(tokens)
    for (const [key, value] of Object.entries(vars)) target.style.setProperty(key, value)
  }
  if (!target?.style) return () => {}
  write(service.tokens)
  const unsubscribe = service.subscribe((tokens) => {
    write(tokens)
  })
  return () => {
    unsubscribe()
    for (const key of Object.keys(themeCssVariables(service.tokens))) target.style.removeProperty(key)
  }
}
