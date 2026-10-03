/**
 * T008-19 display gates: translation fallback is visible (key itself, never
 * silent empty), parameters interpolate, icon ids fall back to a stable
 * default and theme carries high-contrast semantics (F5 §7).
 */
import { describe, expect, it } from 'vitest'

import { createIconResolver, createTheme, createTranslator } from '../src/i18n'

describe('F5 translator', () => {
  it('resolves namespaced keys with parameter interpolation', () => {
    const t = createTranslator({
      chat: { greeting: 'hello {name}' },
    })
    expect(t.translate('chat', 'greeting', { name: 'ada' })).toBe('hello ada')
    expect(t.missingKeys()).toEqual([])
  })

  it('counterexample: missing keys fall back visibly and are recorded', () => {
    const t = createTranslator({ chat: {} })
    expect(t.translate('chat', 'unknown.key')).toBe('unknown.key') // never silent empty
    expect(t.missingKeys()).toEqual(['chat:unknown.key'])
  })

  it('a fallback translator catches misses before the visible-key fallback', () => {
    const base = createTranslator({ common: { ok: 'OK' } })
    const layered = createTranslator({ chat: {} }, base)
    expect(layered.translate('common', 'ok')).toBe('OK')
    expect(layered.translate('chat', 'gone')).toBe('gone')
    expect(layered.missingKeys()).toEqual(['chat:gone'])
  })
})

describe('F5 icons and theme', () => {
  it('unknown icon ids resolve to the stable fallback', () => {
    const icons = createIconResolver({ save: 'icon.save' })
    expect(icons.resolve('save')).toBe('icon.save')
    expect(icons.resolve('mystery')).toBe('icon.unknown')
    expect(icons.resolve('mystery')).toBe(icons.resolve('other-mystery')) // stable fallback
  })

  it('theme exposes high-contrast semantics, consumers never hardcode', () => {
    const normal = createTheme({ bg: '#fff' })
    const high = createTheme({ bg: '#000' }, true)
    expect(normal.highContrast).toBe(false)
    expect(high.highContrast).toBe(true)
    expect(high.tokens.contrast).toBe('high')
  })
})
