// @vitest-environment jsdom
// C-05 对照测试（PA-17）：工作台样式表只引用令牌派生的自定义属性，亮暗两套
// 产物不同，且切换令牌后宿主元素上不再残留另一模式的取值。
import { describe, expect, it } from 'vitest'
import {
  createWorkbenchStyles,
  styles,
  WORKBENCH_DARK_TOKENS,
  WORKBENCH_LIGHT_TOKENS,
  WORKBENCH_TOKENS,
} from '../src/styles'
import type { ResolvedTheme, ThemeTokens } from '../src/styles'

/** 迁移前 `.wb` 暴露的全部 `--ui-*` 属性，逐一登记，不允许漏项。 */
const LEGACY_UI_VARIABLES = [
  '--ui-surface',
  '--ui-nav',
  '--ui-sunken',
  '--ui-hover',
  '--ui-selected',
  '--ui-line',
  '--ui-ink',
  '--ui-ink-secondary',
  '--ui-ink-faint',
  '--ui-accent',
  '--ui-ok',
  '--ui-warn',
  '--ui-error',
] as const

/** 任何形式的原始颜色字面量（hex / rgb / hsl）都不允许出现在产物 CSS 里。 */
const RAW_COLOR_RE = /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/

/** 令牌 → CSS 自定义属性，与宿主 `themeCssVariables` 的命名一致。 */
function cssVariables(tokens: ThemeTokens): Record<string, string> {
  const vars: Record<string, string> = {}
  for (const [group, values] of Object.entries(tokens)) {
    for (const [field, value] of Object.entries(values as Record<string, string>)) {
      vars[`--ordessa-${group}-${field}`] = value
    }
  }
  return vars
}

/** 宿主写入变量后的生效样式表：令牌块 + 工作台产物。 */
function effectiveStylesheet(resolved: ResolvedTheme): string {
  const declarations = Object.entries(cssVariables(WORKBENCH_TOKENS[resolved]))
    .map(([key, value]) => `${key}:${value};`)
    .join('')
  return `:root{${declarations}}${styles}`
}

function writeTheme(resolved: ResolvedTheme): ThemeTokens {
  const tokens = WORKBENCH_TOKENS[resolved]
  const root = document.documentElement
  for (const [key, value] of Object.entries(cssVariables(tokens))) root.style.setProperty(key, value)
  return tokens
}

describe('工作台样式是 C-05 消费方', () => {
  it('默认导出的 styles 仍是字符串，既有消费方无需改动', () => {
    expect(typeof styles).toBe('string')
    expect(styles).toContain('.wb ')
  })

  it('产物 CSS 中没有任何原始颜色字面量', () => {
    expect(RAW_COLOR_RE.test(styles)).toBe(false)
    expect(RAW_COLOR_RE.test(createWorkbenchStyles(WORKBENCH_DARK_TOKENS))).toBe(false)
  })

  it('旧样式表的每个 --ui-* 属性都映射到 --ordessa-* 令牌', () => {
    for (const name of LEGACY_UI_VARIABLES) {
      expect(styles).toContain(`${name}:`)
      const declaration = styles.slice(styles.indexOf(`${name}:`) + name.length + 1)
      const value = declaration.split(';')[0]
      expect(value).toMatch(/var\(--ordessa-/)
    }
  })

  it('不再自带 prefers-color-scheme 分支', () => {
    expect(styles).not.toContain('prefers-color-scheme')
    expect(createWorkbenchStyles(WORKBENCH_DARK_TOKENS)).not.toContain('prefers-color-scheme')
  })

  it('每个颜色令牌都被样式表用到（调色板唯一来源是令牌）', () => {
    for (const key of Object.keys(cssVariables(WORKBENCH_LIGHT_TOKENS)).filter((name) => name.startsWith('--ordessa-color-'))) {
      expect(styles).toContain(`var(${key}`)
    }
  })
})

describe('亮暗两套产物来自令牌', () => {
  it('工作台 CSS 本身与模式无关，颜色全部来自 --ordessa-* 变量', () => {
    // 模式是运行时事实：样式表只引用变量名，因此两种模式共用同一份产物，
    // 差异只能来自宿主写入的令牌值（下一个用例验证这一点）。
    expect(createWorkbenchStyles(WORKBENCH_LIGHT_TOKENS)).toBe(createWorkbenchStyles(WORKBENCH_DARK_TOKENS))
  })

  it('拼上宿主写入的令牌后，亮暗两套生效 CSS 不同且互不为对方取值', () => {
    const light = effectiveStylesheet('light')
    const dark = effectiveStylesheet('dark')
    expect(light).not.toBe(dark)
    for (const field of Object.keys(WORKBENCH_LIGHT_TOKENS.color) as (keyof ThemeTokens['color'])[]) {
      const value = WORKBENCH_DARK_TOKENS.color[field]
      expect(value).not.toBe(WORKBENCH_LIGHT_TOKENS.color[field])
      expect(dark).toContain(`--ordessa-color-${field}:${value}`)
      expect(light).not.toContain(`--ordessa-color-${field}:${value}`)
    }
  })
})

describe('jsdom：写入令牌后宿主元素读到新模式的值，无另一模式残留', () => {
  it('切到 dark 后 --ordessa-color-* 全部来自 dark 令牌', () => {
    writeTheme('light')
    const host = document.createElement('div')
    host.className = 'wb'
    document.body.append(host)
    expect(host.style.getPropertyValue('--ordessa-color-bg')).toBe('')

    const dark = writeTheme('dark')
    const root = document.documentElement
    for (const [key, value] of Object.entries(cssVariables(dark))) {
      expect(root.style.getPropertyValue(key)).toBe(value)
    }
    for (const [field, value] of Object.entries(dark.color)) {
      expect(root.style.getPropertyValue(`--ordessa-color-${field}`)).toBe(value)
      expect(value).not.toBe(WORKBENCH_LIGHT_TOKENS.color[field as keyof ThemeTokens['color']])
    }

    writeTheme('light')
    for (const [field, value] of Object.entries(WORKBENCH_LIGHT_TOKENS.color)) {
      expect(root.style.getPropertyValue(`--ordessa-color-${field}`)).toBe(value)
    }
    host.remove()
  })
})
