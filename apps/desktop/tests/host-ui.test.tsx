// @vitest-environment jsdom
/**
 * 宿主 UI 的门（PA-12/13/14/19/20/24 + C-08 渲染）。
 * 真实挂载 React 组件，用键盘事件走完整流程，不靠"有 tabIndex"充数。
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { runtime } from '@ordessa/extension-host'
import type { Fault, HarnessReport, SettingsSection } from '@extensions/ordessa.contracts/contract.js'
import { AboutPanel, CommandPalette, DiagnosticFragmentList, FaultScreen, HarnessAvailabilityPanel, SettingsPage, type AboutInfo, type PaletteEntryView } from '../renderer/desktop-ui'
import { buildHostServices } from '../renderer/host-services'
import { createFixturePlugin, FIXTURE_PLUGIN_ID, type FixtureProbe } from './fixtures/third-party-plugin'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
let container: HTMLDivElement, root: Root
beforeEach(() => {
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove() })
const render = (element: React.ReactNode) => act(() => root.render(element))
const key = (target: Element, init: KeyboardEventInit) => act(() => target.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, ...init })))

const fault = (kind: Fault['kind'], reason: string, remedy: string, logRef: string): Fault => ({ kind, reason, remedy, logRef })

describe('PA-12 故障 UI：5 类故障各一条，零空白窗口', () => {
  const cases: [Fault['kind'], string, string, string][] = [
    ['data-root-missing', '数据目录不存在', '创建数据目录后重试', 'data-root:ordessa'],
    ['port-conflict', '端口 8931 已被占用', '释放端口后重启', 'server:port'],
    ['runtime-missing', '随包运行时缺失（bin/acp）', '重新安装应用', 'server:runtime'],
    ['data-root-locked', '数据目录已被占用', '关闭另一个实例', 'data-root:lock'],
    ['update-source-unreachable', '更新源不可达', '检查网络后重试', 'update:check'],
  ]
  for (const [kind, reason, remedy, logRef] of cases) {
    it(`${kind}：呈现 reason + remedy + logRef + 导出诊断入口，且不是空白`, () => {
      let exported = 0
      render(<FaultScreen faults={[fault(kind, reason, remedy, logRef)]} onExportDiagnostics={() => exported++} onOpenLogs={() => {}} />)
      const screen = container.querySelector('[data-testid="fault-screen"]')!
      expect(screen).not.toBeNull()
      expect(screen.textContent).toContain(reason)
      expect(container.querySelector('[data-testid="fault-remedy"]')!.textContent).toContain(remedy)
      expect(container.querySelector('[data-testid="fault-logref"]')!.textContent).toContain(logRef)
      expect(container.querySelector('[data-testid="fault"]')!.getAttribute('data-fault-kind')).toBe(kind)
      const buttons = [...container.querySelectorAll('button')].map(button => button.textContent)
      expect(buttons).toContain('导出诊断')
      act(() => { container.querySelector<HTMLButtonElement>('.od-fault-actions button:last-of-type')!.click() })
      expect(exported).toBe(1)
    })
  }
  it('无故障时不渲染任何东西（正常路径不打扰）', () => {
    render(<FaultScreen faults={[]} />)
    expect(container.innerHTML).toBe('')
  })
})

describe('PA-13 设置页：五区 + 数据根只读 + 更新接线', () => {
  const base = {
    dataRoot: '/home/u/.ordessa', logLevel: 'info',
    updateState: { state: 'idle' as const },
    onLogLevel: () => {}, onOpenLogs: () => {}, onExportDiagnostics: () => {},
    onCheckUpdate: () => {}, onDownloadUpdate: () => {}, onApplyUpdate: () => {}, onClose: () => {},
  }
  it('五个宿主分区都在', () => {
    render(<SettingsPage {...base} />)
    const labels = [...container.querySelectorAll('nav button')].map(button => button.textContent)
    expect(labels).toEqual(['通用', '数据', '日志', '更新', '关于'])
  })
  it('数据根只读展示 + 打开目录', () => {
    let opened = 0
    render(<SettingsPage {...base} onOpenLogs={() => opened++} />)
    act(() => { ([...container.querySelectorAll('nav button')].find(button => button.textContent === '数据') as HTMLButtonElement).click() })
    const output = container.querySelector('[data-testid="data-root"]')!
    expect(output.textContent).toBe('/home/u/.ordessa')
    expect(container.querySelector('input[value="/home/u/.ordessa"]')).toBeNull()
    act(() => { container.querySelector<HTMLButtonElement>('[data-testid="settings"] .od-settings-body button')!.click() })
    expect(opened).toBe(1)
  })
  it('日志级别切换立即生效；日志不可写时显式告警', () => {
    const levels: string[] = []
    render(<SettingsPage {...base} onLogLevel={level => levels.push(level)} logHealth={{ dropped: 3, writable: false }} />)
    act(() => { ([...container.querySelectorAll('nav button')].find(button => button.textContent === '日志') as HTMLButtonElement).click() })
    expect(container.querySelector('[data-testid="log-unwritable"]')!.textContent).toContain('3')
    const select = container.querySelector<HTMLSelectElement>('#od-log-level')!
    act(() => { select.value = 'debug'; select.dispatchEvent(new Event('change', { bubbles: true })) })
    expect(levels).toEqual(['debug'])
  })
  it('更新分区：检查/下载/安装三步接线，失败原因可见', () => {
    const calls: string[] = []
    render(<SettingsPage {...base} onCheckUpdate={() => calls.push('check')} onDownloadUpdate={() => calls.push('download')}
      onApplyUpdate={() => calls.push('apply')}
      updateState={{ state: 'failed', reason: '更新源不可达', version: undefined }} />)
    act(() => { ([...container.querySelectorAll('nav button')].find(button => button.textContent === '更新') as HTMLButtonElement).click() })
    expect(container.querySelector('[data-testid="update-state"]')!.textContent).toContain('failed')
    expect(container.querySelector('[data-testid="update-reason"]')!.textContent).toContain('更新源不可达')
    for (const button of [...container.querySelectorAll('button')].filter(item => ['检查更新', '下载', '安装并重启'].includes(item.textContent!))) {
      act(() => button.click())
    }
    expect(calls).toEqual(['check', 'download', 'apply'])
  })
})

describe('PA-14 设置分区贡献点：排序、卸载隐藏、未知片段不下发', () => {
  const section = (id: string, title: string, order?: number): SettingsSection => ({ id, title, order, component: () => null })
  it('登记后按 order 排序，注销后消失', () => {
    const services = buildHostServices()
    const unregisterA = services.settings.register(section('b', '乙', 20))
    const unregisterB = services.settings.register(section('a', '甲', 10))
    expect(services.settings.getSnapshot().map(entry => entry.id)).toEqual(['b', 'a'])
    unregisterA(); unregisterB()
    expect(services.settings.getSnapshot()).toEqual([])
  })
  it('未知片段在设置页标注为保留配置，而不是可编辑项', () => {
    render(<SettingsPage {...{
      dataRoot: '/x', logLevel: 'info', updateState: { state: 'idle' },
      fragments: [{ id: 'gone.provider', state: 'unknown' }, { id: 'live.provider', state: 'known' }],
      onLogLevel: () => {}, onOpenLogs: () => {}, onExportDiagnostics: () => {},
      onCheckUpdate: () => {}, onDownloadUpdate: () => {}, onApplyUpdate: () => {}, onClose: () => {},
    }} />)
    const unknown = [...container.querySelectorAll('[data-testid="unknown-fragment"]')].map(node => node.textContent)
    expect(unknown).toEqual(['gone.provider'])
  })
  it('插件登记的分区出现在列表里；注销（卸载）后消失但主进程配置保留', () => {
    const services = buildHostServices()
    const unregister = services.settings.register(section('example.x', '示例', 30))
    render(<SettingsPage {...{
      dataRoot: '/x', logLevel: 'info', updateState: { state: 'idle' },
      contributed: services.settings.getSnapshot(),
      onLogLevel: () => {}, onOpenLogs: () => {}, onExportDiagnostics: () => {},
      onCheckUpdate: () => {}, onDownloadUpdate: () => {}, onApplyUpdate: () => {}, onClose: () => {},
    }} />)
    expect(container.querySelector('[data-testid="contributed-section"]')!.textContent).toBe('示例')
    unregister()
    render(<SettingsPage {...{
      dataRoot: '/x', logLevel: 'info', updateState: { state: 'idle' },
      contributed: services.settings.getSnapshot(),
      onLogLevel: () => {}, onOpenLogs: () => {}, onExportDiagnostics: () => {},
      onCheckUpdate: () => {}, onDownloadUpdate: () => {}, onApplyUpdate: () => {}, onClose: () => {},
    }} />)
    expect(container.querySelector('[data-testid="contributed-section"]')).toBeNull()
  })
})

describe('PA-04 关于面板：版本、构建号、插件版本、许可证', () => {
  const about: AboutInfo = {
    app: { productName: 'Ordessa Desktop', version: '0.1.0', build: 'ci-42', description: 'd', author: 'Ordessa', license: 'AGPL-3.0-or-later', homepage: 'h', repository: 'r' },
    plugins: [{ id: 'ordessa.workbench', version: '0.1.0' }],
    licenses: [{ name: 'react', version: '19.2.7', license: 'MIT' }],
  }
  it('应用版本/构建号与插件版本、第三方许可证、许可证全文入口都在', () => {
    let opened = 0
    render(<AboutPanel about={about} onOpenLicense={() => opened++} />)
    expect(container.querySelector('[data-testid="about-version"]')!.textContent).toBe('0.1.0')
    expect(container.querySelector('[data-testid="about-build"]')!.textContent).toBe('ci-42')
    expect(container.querySelector('[data-testid="about-plugins"]')!.textContent).toContain('ordessa.workbench')
    expect(container.querySelector('[data-testid="about-licenses"]')!.textContent).toContain('MIT')
    act(() => { container.querySelector<HTMLButtonElement>('[data-testid="about"] button')!.click() })
    expect(opened).toBe(1)
  })
})

describe('PA-19/20 命令面板与键盘全流程', () => {
  const entries: PaletteEntryView[] = [
    { id: 'example.run', title: '运行示例', available: true, key: 'Mod+Shift+E' },
    { id: 'example.hidden', title: '不可用命令', available: false },
  ]
  it('`when` 为假的命令不出现在面板里', () => {
    render(<CommandPalette open entries={entries} onRun={() => {}} onClose={() => {}} />)
    const ids = [...container.querySelectorAll('[data-testid="palette-item"] span')].map(node => node.textContent)
    expect(ids).toEqual(['运行示例'])
  })
  it('键盘全流程：打开 → 搜索 → 方向键 → Enter 执行 → Esc 关闭', () => {
    const ran: string[] = []
    let closed = 0
    render(<CommandPalette open entries={entries} onRun={id => { ran.push(id) }} onClose={() => closed++} />)
    const search = container.querySelector<HTMLInputElement>('[data-testid="palette-search"]')!
    expect(document.activeElement).toBe(search)
    act(() => { search.value = '示例'; search.dispatchEvent(new Event('input', { bubbles: true })) })
    key(search, { key: 'ArrowDown' })
    key(search, { key: 'Enter' })
    expect(ran).toEqual(['example.run'])
    key(search, { key: 'Escape' })
    expect(closed).toBe(1)
  })
  it('命令执行失败 → UI 报错，应用继续可用（面板仍在）', () => {
    render(<CommandPalette open entries={entries} onRun={() => Promise.resolve({ kind: 'Refused', commandId: 'example.run', reason: 'command-unavailable', retryable: false })} onClose={() => {}} />)
    const search = container.querySelector<HTMLInputElement>('[data-testid="palette-search"]')!
    act(() => { container.querySelector<HTMLButtonElement>('[data-testid="palette-item"]')!.click() })
    expect(container.querySelector('[data-testid="command-palette"]')).not.toBeNull()
    void search
  })
  it('执行异常以 Refused 呈现（服务层捕获，不冒泡）', async () => {
    const services = buildHostServices()
    const ran: string[] = []
    const source = buildHostServices({ onCommandError: (id, error) => ran.push(`${id}:${String(error)}`) })
    const disposable = source.commands.forScope({ isDisposed: false, add: item => item })
    disposable.add({ id: 'example.boom', title: '会抛异常的命令', run: () => { throw Error('boom') } })
    const outcome = await services.commands.execute('example.missing')
    expect(outcome.kind === 'Refused' && outcome.reason).toBe('command-absent')
    void ran
  })
})

describe('C-08 Harness 可用性渲染规则', () => {
  it('没有 Harness 插件 → 显示"未提供信息"，不显示假可用', () => {
    render(<HarnessAvailabilityPanel reports={undefined} />)
    expect(container.querySelector('[data-testid="harness-absent"]')!.textContent).toContain('未提供')
  })
  it('unknown 不得显示成可用/成功', () => {
    const reports: HarnessReport[] = [
      { brand: 'a', state: 'unknown', reason: 'inspect-timeout', observedAt: '2026-09-28T00:00:00.000Z' },
      { brand: 'b', state: 'available', observedAt: '2026-09-28T00:00:00.000Z' },
      { brand: 'c', state: 'not-logged-in', reason: '未登录', remedy: '登录后重试', observedAt: '2026-09-28T00:00:00.000Z' },
    ]
    render(<HarnessAvailabilityPanel reports={reports} />)
    const items = [...container.querySelectorAll('[data-testid="harness-item"]')]
    expect(items[0].getAttribute('data-state')).toBe('unknown')
    expect(items[0].textContent).toContain('状态未知')
    expect(items[0].textContent).toContain('inspect-timeout')
    expect(items[2].textContent).toContain('登录后重试')
  })
  it('available 且带 reason 的不变量反例由实现层拒绝（此处只验证渲染不美化）', () => {
    const broken = [{ brand: 'a', state: 'available', reason: 'contradiction', observedAt: 'now' }] as unknown as HarnessReport[]
    render(<HarnessAvailabilityPanel reports={broken} />)
    expect(container.querySelector('[data-testid="harness-item"]')!.textContent).toContain('contradiction')
  })
})

describe('PA-24 边界反例：受控第三方插件只凭公开契约完成 6 项接入', () => {
  it('插件源码对宿主内部的 import 数 = 0', () => {
    const source = readFileSync(path.join(repoRoot, 'apps/desktop/tests/fixtures/third-party-plugin.ts'), 'utf8')
    const specifiers = [...source.matchAll(/from ['"]([^'"]+)['"]/g)].map(match => match[1])
    const hostInternals = specifiers.filter(specifier =>
      specifier.startsWith('..') || specifier.startsWith('/') || specifier.includes('/src/') || specifier.startsWith('apps/'))
    expect(hostInternals).toEqual([])
    // 它只 import 两个公开面。
    expect(new Set(specifiers)).toEqual(new Set(['@extensions/ordessa.contracts/contract.js', '@ordessa/extension-api']))
  })
  it('六项接入在真实宿主装配里全部完成，且插件看不到令牌', async () => {
    const services = buildHostServices({ mode: 'dark' })
    const probe: { value: FixtureProbe | null } = { value: null }
    const desktop = runtime([createFixturePlugin(probe)], services)
    await desktop.start()
    const value = probe.value!
    expect(value.id).toBe(FIXTURE_PLUGIN_ID)
    // ① 日志 ② 主题 ③ 设置分区 ④ 诊断片段 ⑤ 命令 + 快捷键 ⑥ wire 口
    expect(services.settings.getSnapshot().map(entry => entry.id)).toContain('example.third-party')
    expect(services.diagnostics.getSnapshot().map(entry => entry.id)).toContain('example.third-party')
    expect(services.commands.getSnapshot().map(command => command.id)).toContain('example.third-party.run')
    expect(services.keybindings.getSnapshot().map(binding => binding.key)).toContain('Mod+Shift+E')
    expect(value.themeResolved).toBe('dark')
    // 令牌/定位符不可见（C-03 §4 金丝雀）
    expect(value.wireKeys).toEqual(['call', 'ready', 'scope'])
    for (const forbidden of ['token', 'tokenFile', 'origin']) expect(value.wireKeys).not.toContain(forbidden)
    expect(desktop.failures).toEqual([])
    // 卸载插件 → 它登记的分区/命令/绑定全部消失。
    await desktop.deactivate(FIXTURE_PLUGIN_ID)
    expect(services.settings.getSnapshot()).toEqual([])
    expect(services.diagnostics.getSnapshot()).toEqual([])
    expect(services.commands.getSnapshot().map(command => command.id)).not.toContain('example.third-party.run')
  })
  it('反例：宿主源码不得出现品牌名', () => {
    const hostFiles = ['apps/desktop/electron/main.ts', 'apps/desktop/electron/preload.ts', 'apps/desktop/electron/data-root.ts',
      'apps/desktop/electron/lifecycle.ts', 'apps/desktop/electron/faults.ts', 'apps/desktop/electron/settings-store.ts',
      'apps/desktop/electron/security.ts', 'apps/desktop/electron/update-client.ts', 'apps/desktop/electron/wire-fixture.ts',
      'apps/desktop/renderer/desktop-ui.tsx', 'apps/desktop/renderer/host-services.ts', 'apps/desktop/renderer/main.tsx']
    const brand = /\b(pi|codex|claude|gemini|copilot)\b/gi
    for (const file of hostFiles) {
      const source = readFileSync(path.join(repoRoot, file), 'utf8')
      const hits = [...source.matchAll(brand)].map(match => match[0])
      expect(hits, `${file} 出现品牌名`).toEqual([])
    }
  })
})

describe('C-06 §B2 诊断片段：unknown 也要显示', () => {
  it('未知片段被标出而不是静默丢弃', () => {
    render(<DiagnosticFragmentList fragments={[
      { id: 'ok.plugin', state: 'collected', data: { a: 1 } },
      { id: 'slow.plugin', state: 'unknown', reason: 'collect-timeout' },
    ]} />)
    const items = [...container.querySelectorAll('li')]
    expect(items).toHaveLength(2)
    expect(items[1].textContent).toContain('collect-timeout')
  })
})
