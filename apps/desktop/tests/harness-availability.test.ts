/**
 * PA-25 — C-08 缺席语义与渲染（core 侧，不改插件）。
 * 反例清单见 C-08 §6：未安装 / 未登录 / 超时 / 无提供者 / 不变量 / 边界（品牌名）。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  createAbsentHarnessAvailability, createFixtureHarnessAvailability, enforceReportInvariant, INSPECT_TIMEOUT_MS,
} from '@ordessa/extension-host/platform'
import type { HarnessReport, HarnessState } from '@extensions/ordessa.contracts/contract.js'
import { buildHostServices } from '../renderer/host-services'

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
const at = (state: HarnessState, extra: Partial<HarnessReport> = {}): HarnessReport =>
  ({ brand: 'fixture-a', state, observedAt: '2026-09-28T00:00:00.000Z', ...extra })

describe('C-08 §6.1/2 六态：每态都携带与 state 一致的 reason', () => {
  const six: [HarnessState, HarnessReport][] = [
    ['available', at('available', { version: '1.2.3' })],
    ['not-installed', at('not-installed', { reason: 'not-installed-on-this-machine' })],
    ['not-logged-in', at('not-logged-in', { reason: '未登录', remedy: '登录后重试' })],
    ['unsupported', at('unsupported', { reason: '缺少所需能力' })],
    ['failed', at('failed', { reason: '适配器启动失败' })],
    ['unknown', at('unknown', { reason: 'inspect-timeout' })],
  ]
  for (const [state, report] of six) {
    it(`${state}：通过不变量校验且不被降级`, () => {
      const { violated } = enforceReportInvariant(report)
      expect(violated).toBe(false)
    })
  }
  it('available 带 version 时不编造 reason，unknown 也必须有 reason', () => {
    const available = enforceReportInvariant(at('available', { version: '1.0.0' }))
    expect(available.violated).toBe(false)
    expect(available.report.reason).toBeUndefined()
    expect(enforceReportInvariant(at('failed')).violated).toBe(true)
  })
})

describe('C-08 §6.5 不变量反例：available 却带 reason → 降级为 unknown（不崩、不假绿）', () => {
  it('available + reason 被判违规并降级', () => {
    const { report, violated } = enforceReportInvariant(at('available', { reason: '矛盾' }))
    expect(violated).toBe(true)
    expect(report.state).toBe('unknown')
    expect(report.reason).toContain('invariant-violation')
  })
  it('非 available 缺 reason 被判违规并降级', () => {
    const { report, violated } = enforceReportInvariant(at('not-logged-in'))
    expect(violated).toBe(true)
    expect(report.state).toBe('unknown')
  })
  it('受控 fixture 提供者会把故意违规的条目降级', async () => {
    const provider = createFixtureHarnessAvailability({ brands: [{ brand: 'fixture-a', state: 'available', breakInvariant: true }] })
    const [report] = await provider.inspect()
    expect(report.state).toBe('unknown')
  })
})

describe('C-08 §2 有界探测：超时 → unknown + inspect-timeout', () => {
  it('超过上限的探测不冒充 available', async () => {
    const provider = createFixtureHarnessAvailability({
      brands: [{ brand: 'fixture-a', state: 'available', version: '9.9.9', delayMs: INSPECT_TIMEOUT_MS + 1 }],
    })
    const [report] = await provider.inspect()
    expect(report.state).toBe('unknown')
    expect(report.reason).toBe('inspect-timeout')
    expect(report.version).toBeUndefined()
  })
  it('未安装的品牌一律 not-installed，即使规格里写的是 available', async () => {
    const provider = createFixtureHarnessAvailability({
      brands: [{ brand: 'fixture-a', state: 'available', version: '1.0.0' }], installed: [],
    })
    const [report] = await provider.inspect()
    expect(report.state).toBe('not-installed')
  })
  it('未知品牌查询返回 unknown，不冒充 available', async () => {
    const provider = createFixtureHarnessAvailability({ brands: [{ brand: 'fixture-a', state: 'available' }] })
    const report = await provider.inspectOne('fixture-zzz')
    expect(report.state).toBe('unknown')
    expect(report.reason).toBe('unknown-brand')
  })
})

describe('C-08 §4 缺席：没有提供者时诚实缺席', () => {
  it('宿主默认注入缺席实现：provided=false + inspectOne 给 unknown/host-not-ready', async () => {
    const absent = createAbsentHarnessAvailability()
    expect(absent.provided).toBe(false)
    expect(await absent.inspect()).toEqual([])
    const one = await absent.inspectOne('fixture-a')
    expect(one.state).toBe('unknown')
    expect(one.reason).toBe('host-not-ready')
  })
  it('平台服务缺省就是缺席实现（插件线交付前不假绿）', () => {
    expect(buildHostServices().harness.provided).toBe(false)
  })
  it('缺席实现永不抛异常', async () => {
    const absent = createAbsentHarnessAvailability()
    expect(() => absent.subscribe(() => {})).not.toThrow()
    await expect(absent.inspect()).resolves.toEqual([])
  })
})

describe('C-08 §6.6 边界：宿主源码出现品牌名即判红', () => {
  it('C-08 相关的宿主/契约文件里没有品牌名', () => {
    const files = [
      'packages/desktop-platform/extension-host/src/services/harness-availability.ts',
      'packages/desktop-platform/contracts/foundation/src/product/harness-availability.ts',
      'apps/desktop/renderer/desktop-ui.tsx',
      'apps/desktop/renderer/host-services.ts',
      'apps/desktop/electron/main.ts',
    ]
    const brand = /\b(pi|codex|claude|gemini|copilot|openai|anthropic)\b/gi
    for (const file of files) {
      const hits = [...readFileSync(path.join(repoRoot, file), 'utf8').matchAll(brand)].map(match => match[0])
      expect(hits, `${file} 出现品牌名`).toEqual([])
    }
  })
})
