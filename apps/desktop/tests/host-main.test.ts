/**
 * 宿主主进程侧的门（PA-02/03/04/07/08/09/10/11/13/14/21/22/23）。
 * 每条断言都对应契约里的一条反例或硬门；node 环境，不起 Electron。
 */
import { mkdtemp, mkdir, readFile, rm, stat, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterEach, describe, expect, it } from 'vitest'
import { buildInfo, assertBuildInfo, writeBuildInfo } from '../scripts/build-info.mjs'
import { exportIcons, ICON_SIZES, HICOLOR_SIZES } from '../scripts/build-icons.mjs'
import { findTestDrivers, FORBIDDEN_MARKERS } from '../scripts/release-hygiene.mjs'
import { acquireDataRootLock, ensureDataRoot, probeDataRoot, resolveDataRoot } from '../electron/data-root'
import { isRenderableFault, sortFaults, faultId } from '../electron/faults'
import { DEFAULT_WINDOW_STATE, beginSession, cleanSession, restoreWindowState, runCleanup, startupCrashReport } from '../electron/lifecycle'
import { createSettingsStore, normalizeDocument, projectFragments } from '../electron/settings-store'
import { createFixtureUpdateClient } from '../electron/update-client'
import { createAbsentWirePort, createFixtureWirePort, createRendererWirePort, visibleWireKeys } from '../electron/wire-fixture'
import { APP_ORIGIN, SECURE_WEB_PREFERENCES, WINDOW_OPEN_ACTION, isTrustedIpcCaller } from '../electron/security'

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
const scratch: string[] = []
async function tempDir() { const dir = await mkdtemp(path.join(tmpdir(), 'ordessa-host-')); scratch.push(dir); return dir }
afterEach(async () => { for (const dir of scratch.splice(0)) await rm(dir, { recursive: true, force: true }) })

describe('PA-02 产品身份：版本号单一来源 + 构建号注入', () => {
  it('版本与构建号只从 package.json 派生，元数据字段齐全', () => {
    const info = assertBuildInfo(buildInfo({ name: '@modular/desktop-app', version: '0.1.0', productName: 'Ordessa Desktop' }, { buildNumber: 'ci-42', builtAt: '2026-09-28T00:00:00.000Z' }))
    expect(info.version).toBe('0.1.0')
    expect(info.build).toBe('ci-42')
    for (const field of ['name', 'productName', 'description', 'author', 'license', 'homepage', 'repository'] as const) {
      expect(typeof info[field]).toBe('string')
    }
  })
  it('反例：非法版本号被拒（不允许各写一份版本）', () => {
    expect(() => assertBuildInfo(buildInfo({ name: 'x', version: 'dev' }))).toThrow(/Invalid app version/)
  })
  it('构建把 build-info.json 与许可证聚合写进 dist，四处同源', async () => {
    const out = await tempDir()
    const { info, licenses } = await writeBuildInfo({ repoRoot, outDir: out })
    const written = JSON.parse(await readFile(path.join(out, 'build-info.json'), 'utf8'))
    expect(written.version).toBe(info.version)
    expect(written.build).toBe(info.build)
    expect(Array.isArray(licenses)).toBe(true)
    // 应用自身不出现在第三方列表里（它有独立的许可证入口）。
    expect(licenses.every(entry => entry.name !== '@modular/desktop-app')).toBe(true)
  })
})

describe('PA-03 图标接线：单一事实位置 + 缺图不阻塞', () => {
  it('设计稿缺失时导出全部尺寸的占位 PNG 与 hicolor 布局', async () => {
    const out = await tempDir()
    const report = await exportIcons({ repoRoot, outDir: out, source: path.join(out, 'absent.svg') })
    expect(report.haveSource).toBe(false)
    expect(report.warnings.length).toBeGreaterThan(0)
    for (const size of ICON_SIZES) {
      const file = path.join(out, 'flat', `${size}.png`)
      expect((await stat(file)).size).toBeGreaterThan(0)
      // 真 PNG 魔数：占位图也必须是合法 PNG。
      expect((await readFile(file)).subarray(0, 8)).toEqual(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))
    }
    for (const size of HICOLOR_SIZES) {
      await stat(path.join(out, 'hicolor', `${size}x${size}`, 'apps/ordessa.png'))
    }
  })
  it('反例：换设计稿不需要改代码——同一导出函数对存在的 SVG 走矢量路径', async () => {
    const out = await tempDir()
    const source = path.join(out, 'icon.svg')
    await writeFile(source, '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256"/></svg>')
    const report = await exportIcons({ repoRoot, outDir: path.join(out, 'icons'), source })
    expect(report.haveSource).toBe(true)
    await stat(path.join(out, 'icons/hicolor/scalable/apps/ordessa.svg'))
    await stat(path.join(out, 'icons/generated.json'))
  })
})

describe('PA-11 代码卫生：发行物零测试驱动代码', () => {
  it('闸门能抓住残留的驱动标记', async () => {
    const dir = await tempDir()
    await writeFile(path.join(dir, 'electron-main.cjs'), 'console.log("MODULAR_LOADER_READY")')
    const violations = await findTestDrivers(dir)
    expect(violations).toHaveLength(1)
  })
  it('干净目录无违例', async () => {
    const dir = await tempDir()
    await writeFile(path.join(dir, 'electron-main.cjs'), 'require("electron")')
    expect(await findTestDrivers(dir)).toEqual([])
  })
  it('真实构建产物里没有驱动代码（dist 存在时才断言；不存在即失败而不是跳过）', async () => {
    const dist = path.join(repoRoot, 'apps/desktop/dist')
    const main = path.join(dist, 'electron-main.cjs')
    if (!await stat(main).then(() => true, () => false)) {
      throw Error('dist/electron-main.cjs 缺失：先跑 npm run build（真实构建即真实门）')
    }
    const source = await readFile(main, 'utf8')
    for (const marker of FORBIDDEN_MARKERS) expect(source).not.toContain(marker)
  })
})

describe('PA-07 数据根与锁语义（消费 C-01）', () => {
  it('解析顺序：env 优先，缺省 ~/.ordessa', () => {
    expect(resolveDataRoot({ ORDESSA_DATA_ROOT: '/tmp/custom' }, '/home/u')).toBe('/tmp/custom')
    expect(resolveDataRoot({}, '/home/u')).toBe(path.join('/home/u', '.ordessa'))
  })
  it('目录缺失 → 故障带 reason/remedy/logRef，不抛异常', async () => {
    const dir = await tempDir()
    const probe = await probeDataRoot(path.join(dir, 'nope'))
    expect(probe.ok).toBe(false)
    if (probe.ok) throw Error('unreachable')
    expect(probe.fault.kind).toBe('data-root-missing')
    expect(isRenderableFault(probe.fault)).toBe(true)
  })
  it('根被活进程锁住 → DATA_ROOT_LOCKED（C-01 类型化码）', async () => {
    const dir = await tempDir()
    await ensureDataRoot(dir)
    await writeFile(path.join(dir, '.lock'), JSON.stringify({ pid: 4242, host: 'test' }))
    const probe = await probeDataRoot(dir, { isLive: () => true })
    expect(probe.ok).toBe(false)
    if (probe.ok) throw Error('unreachable')
    expect(probe.code).toBe('DATA_ROOT_LOCKED')
    expect(faultId(probe.fault)).toBe('DATA_ROOT_LOCKED')
  })
  it('取锁 → 释放 → 残留锁不阻塞下次启动', async () => {
    const dir = await tempDir()
    await ensureDataRoot(dir)
    const release = await acquireDataRootLock(dir, { isLive: () => false, pid: 1 })
    expect((await probeDataRoot(dir, { isLive: () => false })).ok).toBe(true)
    await release()
    expect((await probeDataRoot(dir, { isLive: () => false })).ok).toBe(true)
  })
  it('反例：活锁存在时取锁被拒', async () => {
    const dir = await tempDir()
    await ensureDataRoot(dir)
    await writeFile(path.join(dir, '.lock'), JSON.stringify({ pid: 7 }))
    await expect(acquireDataRootLock(dir, { isLive: () => true })).rejects.toThrow(/locked/)
  })
})

describe('PA-08 统一清理：清理异常不覆盖主因', () => {
  it('所有步骤都跑完，失败被收集而不是短路', async () => {
    const order: string[] = []
    const outcome = await runCleanup([
      { name: 'a', run: () => { order.push('a') } },
      { name: 'b', run: () => { order.push('b'); throw Error('disk full') } },
      { name: 'c', run: async () => { order.push('c') } },
    ])
    expect(order).toEqual(['a', 'b', 'c'])
    expect(outcome.ok).toBe(false)
    expect(outcome.errors).toEqual([{ step: 'b', error: 'Error: disk full' }])
  })
  it('无失败时 ok 为真', async () => {
    expect((await runCleanup([{ name: 'a', run: () => undefined }])).ok).toBe(true)
  })
})

describe('PA-09 窗口状态记忆与显示器变化退化', () => {
  const displays = [{ bounds: { x: 0, y: 0, width: 1920, height: 1080 } }]
  it('合法几何被恢复', () => {
    expect(restoreWindowState({ x: 100, y: 80, width: 1000, height: 700, maximized: false }, displays))
      .toEqual({ x: 100, y: 80, width: 1000, height: 700, maximized: false })
  })
  it('显示器变小 → 退化为默认值（不裁剪、不丢窗）', () => {
    expect(restoreWindowState({ x: 0, y: 0, width: 3000, height: 1400 }, displays)).toEqual(DEFAULT_WINDOW_STATE)
  })
  it('拔掉扩展屏 → 位置失效但尺寸保留', () => {
    const onlyLaptop = [{ bounds: { x: 0, y: 0, width: 1280, height: 800 } }]
    expect(restoreWindowState({ x: 3000, y: 200, width: 1000, height: 700 }, onlyLaptop))
      .toEqual({ x: -1, y: -1, width: 1000, height: 700, maximized: false })
  })
  it('反例：损坏/缺失的状态文件不抛异常', () => {
    expect(restoreWindowState('garbage', displays)).toEqual(DEFAULT_WINDOW_STATE)
    expect(restoreWindowState(null, displays)).toEqual(DEFAULT_WINDOW_STATE)
  })
})

describe('PA-10 崩溃恢复', () => {
  it('上次没干净退出 → 如实记账并可读', () => {
    const marker = { startedAt: '2026-09-28T10:00:00.000Z', pid: 99, clean: false }
    const report = startupCrashReport(marker, new Date('2026-09-28T10:00:30.000Z'))
    expect(report.recovered).toBe(true)
    expect(report.detail).toContain('pid 99')
  })
  it('干净退出 / 无记录 → 不谎报崩溃', () => {
    expect(startupCrashReport({ startedAt: 'x', pid: 1, clean: true }, new Date()).recovered).toBe(false)
    expect(startupCrashReport(null, new Date()).recovered).toBe(false)
  })
  it('会话标记可写可清', () => {
    const begin = beginSession(new Date(), 7)
    expect(begin.clean).toBe(false)
    expect(cleanSession(begin).clean).toBe(true)
  })
})

describe('PA-12 故障事实：字段齐全、顺序稳定', () => {
  const fault = (kind: any) => ({ kind, reason: 'r', remedy: 'm', logRef: 'l' })
  it('五种故障都被识别为可渲染', () => {
    for (const kind of ['data-root-missing', 'port-conflict', 'runtime-missing', 'data-root-locked', 'update-source-unreachable']) {
      expect(isRenderableFault(fault(kind))).toBe(true)
    }
  })
  it('反例：缺 reason/remedy/logRef 的故障不得进入 UI', () => {
    expect(isRenderableFault({ kind: 'port-conflict', remedy: 'm', logRef: 'l' })).toBe(false)
    expect(isRenderableFault(null)).toBe(false)
  })
  it('顺序稳定：先数据根再运行时再更新', () => {
    const sorted = sortFaults([fault('update-source-unreachable'), fault('port-conflict'), fault('data-root-missing')])
    expect(sorted.map(entry => entry.kind)).toEqual(['data-root-missing', 'port-conflict', 'update-source-unreachable'])
  })
})

describe('PA-14 设置片段：未知不下发、卸载保留配置', () => {
  it('未知片段被标记 unknown 且不携带值', () => {
    const document = { version: 1 as const, values: { 'known.one': 1, 'gone.provider': { secret: 'x' } } }
    const fragments = projectFragments(document, new Set(['known.one']))
    const unknown = fragments.find(fragment => fragment.id === 'gone.provider')!
    expect(unknown.state).toBe('unknown')
    expect(unknown.value).toBeUndefined()
  })
  it('反例：坏 JSON / 非对象文档归一化为空，不崩', () => {
    expect(normalizeDocument(null).values).toEqual({})
    expect(normalizeDocument({ values: [1, 2] }).values).toEqual({})
  })
  it('卸载提供者后配置仍在（读回断言）', async () => {
    const dir = await tempDir()
    const store = createSettingsStore(path.join(dir, 'settings.json'))
    await store.load()
    await store.set('gone.provider', { keep: 'me' })
    const reopened = createSettingsStore(path.join(dir, 'settings.json'))
    await reopened.load()
    // 提供者缺席：只影响"已知"集合，数据不动。
    expect(reopened.fragments(new Set())).toEqual([{ id: 'gone.provider', state: 'unknown', value: undefined }])
    expect(reopened.get('gone.provider')).toEqual({ keep: 'me' })
  })
})

describe('PA-21/22 wire 口：三态、缺席、不重发、令牌不可见', () => {
  it('正常返回 Accepted', async () => {
    const port = createFixtureWirePort()
    const result = await port.call('example.method', {})
    expect(result.kind).toBe('Accepted')
  })
  it('宿主未就绪 → Unknown/host-not-ready，不抛异常', async () => {
    const port = createFixtureWirePort({ scenario: { kind: 'not-ready' } })
    expect(port.ready).toBe(false)
    expect((await port.call('example.method', {})).kind).toBe('Unknown')
  })
  it('令牌缺席 → Unknown/transport-unreachable', async () => {
    const port = createFixtureWirePort({ scenario: { kind: 'unreachable' } })
    const result = await port.call('example.method', {})
    expect(result.kind === 'Unknown' && result.reason).toBe('transport-unreachable')
  })
  it('业务拒绝 → Refused 且 retryable 正确', async () => {
    const port = createFixtureWirePort({ scenario: { kind: 'refused', reason: 'not-allowed', retryable: false } })
    const result = await port.call('example.method', {})
    expect(result.kind === 'Refused' && [result.reason, result.retryable]).toEqual(['not-allowed', false])
  })
  it('传输中断 → Unknown/result-unknown 且不重发（调用只记一次）', async () => {
    const calls: { method: string }[] = []
    const port = createFixtureWirePort({ scenario: { kind: 'disconnect' }, calls: calls as never })
    const result = await port.call('example.method', {})
    expect(result.kind === 'Unknown' && result.reason).toBe('result-unknown')
    expect(calls).toHaveLength(1)
  })
  it('非法方法名 → Unknown/invalid-method', async () => {
    const result = await createFixtureWirePort().call('bad method!', {})
    expect(result.kind === 'Unknown' && result.reason).toBe('invalid-method')
  })
  it('缺席传输口恒 Unknown/port-absent', async () => {
    const port = createAbsentWirePort()
    expect(port.ready).toBe(false)
    expect(port.scope).toBeNull()
    const result = await port.call('example.method', {})
    expect(result.kind === 'Unknown' && result.reason).toBe('port-absent')
  })
  it('金丝雀：插件可见面只有 call/ready/scope，没有令牌或 origin', () => {
    const keys = visibleWireKeys(createFixtureWirePort())
    expect(keys).toEqual(['call', 'ready', 'scope'])
    for (const forbidden of ['token', 'tokenFile', 'origin']) expect(keys).not.toContain(forbidden)
  })
  it('渲染侧代理：桥抛错降级为 Unknown，不冒泡到界面', async () => {
    const port = createRendererWirePort({ call: async () => { throw Error('ipc down') }, ready: async () => true, scope: async () => null })
    const result = await port.call('example.method', {})
    expect(result.kind === 'Unknown' && result.reason).toBe('transport-unreachable')
  })
})

describe('PA-13 更新分区接线（引擎归 P-C，此处只有受控 fixture）', () => {
  it('检查→下载→安装→需要重启', async () => {
    const client = createFixtureUpdateClient()
    expect((await client.check()).state).toBe('available')
    expect((await client.download()).state).toBe('ready-to-install')
    expect((await client.apply()).state).toBe('restart-required')
  })
  it('反例：更新源不可达不得静默当成"已是最新"', async () => {
    const client = createFixtureUpdateClient({ sourceReachable: false })
    const state = await client.check()
    expect(state.state).toBe('failed')
    expect(state.state === 'failed' && state.fault?.kind).toBe('update-source-unreachable')
  })
  it('反例：下载失败保留旧版本', async () => {
    const client = createFixtureUpdateClient({ failAt: 'download' })
    await client.check()
    expect((await client.download()).state).toBe('failed')
  })
})

describe('PA-23 安全基线不退化', () => {
  it('sandbox/contextIsolation/nodeIntegration 保持 true/true/false', () => {
    expect(SECURE_WEB_PREFERENCES.sandbox).toBe(true)
    expect(SECURE_WEB_PREFERENCES.contextIsolation).toBe(true)
    expect(SECURE_WEB_PREFERENCES.nodeIntegration).toBe(false)
  })
  it('IPC 调用方校验：只有主窗口主 frame 的应用源被接受', () => {
    const trusted = { sameSender: true, mainFrame: true, url: APP_ORIGIN, windowDestroyed: false }
    expect(isTrustedIpcCaller(trusted)).toBe(true)
    expect(isTrustedIpcCaller({ ...trusted, sameSender: false })).toBe(false)
    expect(isTrustedIpcCaller({ ...trusted, mainFrame: false })).toBe(false)
    expect(isTrustedIpcCaller({ ...trusted, url: 'https://example.com' })).toBe(false)
    expect(isTrustedIpcCaller({ ...trusted, windowDestroyed: true })).toBe(false)
  })
  it('新窗口一律 deny', () => { expect(WINDOW_OPEN_ACTION).toBe('deny') })
})
