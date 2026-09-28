// C-05 主题服务的行为测试（PA-16）。全部为真实行为：模式切换、冻结、订阅、
// CSS 变量映射与文档写入，无桩件替代。
import { describe, expect, it, vi } from 'vitest'
import {
  applyThemeToDocument,
  completeThemeTokens,
  createNeutralThemeService,
  createThemeService,
  NEUTRAL_TOKENS,
  themeCssVariables,
} from '../src/services/theme'
import type { ThemeTokens } from '../src/services/theme'

/** 一个可编程的系统偏好，用于 C-05 §4 的 system 跟随。 */
function fakeSystem(initial: boolean) {
  const state = { dark: initial }
  return { state, prefersDark: () => state.dark }
}

describe('createThemeService：模式与解析（C-05 §1/§4）', () => {
  it('默认 system 跟随宿主偏好，解析为 light/dark', () => {
    const light = createThemeService({ mode: 'system', prefersDark: () => false })
    expect(light.mode).toBe('system')
    expect(light.resolved).toBe('light')

    const dark = createThemeService({ mode: 'system', prefersDark: () => true })
    expect(dark.resolved).toBe('dark')
  })

  it('setMode 切到 dark 后 mode 与 resolved 同时变化并通知订阅者', () => {
    const service = createThemeService({ mode: 'light', prefersDark: () => false })
    const seen: string[] = []
    service.subscribe((_tokens, resolved) => seen.push(resolved))

    service.setMode('dark')

    expect(service.mode).toBe('dark')
    expect(service.resolved).toBe('dark')
    expect(seen).toEqual(['dark'])
  })

  it('显式模式覆盖系统偏好', () => {
    const system = fakeSystem(true)
    const service = createThemeService({ mode: 'system', prefersDark: system.prefersDark })
    expect(service.resolved).toBe('dark')
    service.setMode('light')
    expect(service.resolved).toBe('light')
  })

  it('system 模式下系统变化实时生效，切回 system 立即生效', () => {
    const system = fakeSystem(false)
    const service = createThemeService({ mode: 'system', prefersDark: system.prefersDark })
    const seen: string[] = []
    service.subscribe((_tokens, resolved) => seen.push(resolved))
    expect(service.resolved).toBe('light')

    service.setMode('dark')
    expect(seen).toEqual(['dark'])

    // 切回 system 时系统已是暗色：解析结果不变，因此不产生多余通知。
    system.state.dark = true
    service.setMode('system')
    expect(service.mode).toBe('system')
    expect(service.resolved).toBe('dark')
    expect(seen).toEqual(['dark'])

    // 系统再切回亮色：跟随实时生效。
    system.state.dark = false
    service.setMode('system')
    expect(service.resolved).toBe('light')
    expect(seen).toEqual(['dark', 'light'])
  })

  it('setMode 经 persist 钩子持久化，onChange 在变化后被调用', () => {
    const persist = vi.fn()
    const onChange = vi.fn()
    const service = createThemeService({ mode: 'light', prefersDark: () => false, persist, onChange })
    service.setMode('dark')
    expect(persist).toHaveBeenCalledWith('dark')
    expect(onChange).toHaveBeenCalledWith(service.tokens, 'dark')
  })

  it('退订后不再收到通知', () => {
    const service = createThemeService({ mode: 'light', prefersDark: () => false })
    const listener = vi.fn()
    const off = service.subscribe(listener)
    off()
    service.setMode('dark')
    expect(listener).not.toHaveBeenCalled()
  })
})

describe('令牌不可变性（C-05 §1 不变量）', () => {
  it('每一层都被冻结，尝试修改不生效', () => {
    const service = createThemeService({ mode: 'light', prefersDark: () => false })
    const { tokens } = service
    expect(Object.isFrozen(tokens)).toBe(true)
    for (const group of ['color', 'space', 'radius', 'font', 'z'] as const) {
      expect(Object.isFrozen(tokens[group])).toBe(true)
    }
    expect(() => {
      ;(tokens.color as { bg: string }).bg = '#000000'
    }).toThrow(TypeError)
    expect(tokens.color.bg).not.toBe('#000000')
  })

  it('模式切换产生新对象，旧对象保持原样', () => {
    const service = createThemeService({ mode: 'light', prefersDark: () => false })
    const before = service.tokens
    const beforeBg = before.color.bg
    service.setMode('dark')
    const after = service.tokens
    expect(after).not.toBe(before)
    expect(after.color).not.toBe(before.color)
    expect(before.color.bg).toBe(beforeBg)
    expect(after.color.bg).not.toBe(beforeBg)
    expect(Object.isFrozen(before)).toBe(true)
  })

  it('令牌覆盖 C-05 全部字段（color 9 / space 4 / radius 3 / font 2 / z 3），亮暗两套取值不同', () => {
    const light = createThemeService({ mode: 'light', prefersDark: () => false }).tokens
    expect(Object.keys(light.color)).toHaveLength(9)
    expect(Object.keys(light.space)).toHaveLength(4)
    expect(Object.keys(light.radius)).toHaveLength(3)
    expect(Object.keys(light.font)).toHaveLength(2)
    expect(Object.keys(light.z)).toHaveLength(3)
    const service = createThemeService({ mode: 'light', prefersDark: () => false })
    service.setMode('dark')
    const darkTokens = service.tokens
    for (const field of Object.keys(light.color) as (keyof ThemeTokens['color'])[]) {
      expect(darkTokens.color[field]).not.toBe(light.color[field])
      expect(darkTokens.color[field]).toMatch(/^#|^rgb/)
    }
  })
})
describe('缺席与未就绪（C-05 §5）', () => {
  it('中性服务返回非空令牌且 resolved 为 light', () => {
    const service = createNeutralThemeService()
    expect(service.resolved).toBe('light')
    expect(service.tokens.color.bg).toBeTruthy()
    expect(Object.keys(service.tokens.color)).toHaveLength(9)
    expect(() => service.setMode('dark')).not.toThrow()
    expect(service.resolved).toBe('light')
  })

  it('NEUTRAL_TOKENS 可用、非空且被冻结', () => {
    expect(Object.isFrozen(NEUTRAL_TOKENS)).toBe(true)
    expect(NEUTRAL_TOKENS.color.surface).toBeTruthy()
    expect(NEUTRAL_TOKENS.space.md).toBeTruthy()
  })

  it('令牌字段缺失用默认值补齐，不抛异常', () => {
    const completed = completeThemeTokens({ color: { accent: '#123456' } })
    expect(completed.color.accent).toBe('#123456')
    expect(completed.color.bg).toBe(NEUTRAL_TOKENS.color.bg)
    expect(Object.keys(completed.z)).toHaveLength(3)
    expect(Object.isFrozen(completed.color)).toBe(true)
    expect(() => completeThemeTokens(undefined)).not.toThrow()
    expect(completeThemeTokens({} as never).color.text).toBe(NEUTRAL_TOKENS.color.text)
  })
})

describe('订阅者隔离（C-05 §6.4）', () => {
  it('抛异常的订阅者不影响其他订阅者与调用方', () => {
    const service = createThemeService({ mode: 'light', prefersDark: () => false })
    const after = vi.fn()
    service.subscribe(() => {
      throw new Error('订阅者炸了')
    })
    service.subscribe(after)
    expect(() => service.setMode('dark')).not.toThrow()
    expect(after).toHaveBeenCalledTimes(1)
    expect(service.resolved).toBe('dark')
  })
})

describe('CSS 变量映射与文档写入（C-05 §2 消费方式 1）', () => {
  it('每个令牌字段映射为一个 --ordessa-* 自定义属性', () => {
    const service = createThemeService({ mode: 'light', prefersDark: () => false })
    const vars = themeCssVariables(service.tokens)
    expect(vars['--ordessa-color-bg']).toBe(service.tokens.color.bg)
    expect(vars['--ordessa-color-danger']).toBe(service.tokens.color.danger)
    expect(vars['--ordessa-space-md']).toBe(service.tokens.space.md)
    expect(vars['--ordessa-radius-lg']).toBe(service.tokens.radius.lg)
    expect(vars['--ordessa-font-mono']).toBe(service.tokens.font.mono)
    expect(vars['--ordessa-z-toast']).toBe(service.tokens.z.toast)
    expect(Object.keys(vars)).toHaveLength(9 + 4 + 3 + 2 + 3)
    for (const key of Object.keys(vars)) expect(key.startsWith('--ordessa-')).toBe(true)
  })

  it('applyThemeToDocument 写入目标 style，随模式更新，disposer 移除并退订', () => {
    const service = createThemeService({ mode: 'light', prefersDark: () => false })
    const written = new Map<string, string>()
    const target = {
      style: {
        setProperty: (key: string, value: string) => {
          written.set(key, value)
        },
        removeProperty: (key: string) => {
          written.delete(key)
        },
      },
    }

    const dispose = applyThemeToDocument(service, target)
    expect(written.get('--ordessa-color-bg')).toBe(service.tokens.color.bg)

    service.setMode('dark')
    expect(written.get('--ordessa-color-bg')).toBe(service.tokens.color.bg)
    expect(written.get('--ordessa-color-bg')).not.toBe(NEUTRAL_TOKENS.color.bg)

    dispose()
    expect(written.size).toBe(0)
    service.setMode('light')
    expect(written.size).toBe(0)
  })
})
