/**
 * Desktop 主进程（PA-02/03/04/07/08/09/10/11/12/13/21/22/23 的接线点）。
 *
 * 纪律：
 *   · 测试驱动代码**不在**本文件（PA-11）：smoke 驱动只按路径动态加载，永不进发行物；
 *   · 令牌不经过渲染进程（C-03 §4 / FR-031）：wire 调用在主进程发起，界面只拿三态；
 *   · 凭据/路径不外泄：拒绝信息最多带 basename（C-04 §4 定位符规则）。
 */
import { app, BrowserWindow, dialog, ipcMain, protocol, screen, session, shell } from 'electron'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { existsSync, readFileSync } from 'node:fs'
import { cpus, freemem, totalmem } from 'node:os'
import { createHash } from 'node:crypto'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { discover } from '@ordessa/extension-host/main'
import { protocolHandler } from '@ordessa/extension-host/main'
import { collectDiagnostics, createLogService, type LogService } from '@ordessa/extension-host/services'
import { installNativeBridge } from '@ordessa/native-bridge'
import { acquireDataRootLock, defaultHome, ensureDataRoot, probeDataRoot, resolveDataRoot } from './data-root'
import { isRenderableFault, sortFaults } from './faults'
import { beginSession, cleanSession, runCleanup, restoreWindowState, startupCrashReport, type CrashMarker, type QuitStep, type WindowState } from './lifecycle'
import { APP_ORIGIN, SECURE_WEB_PREFERENCES, WINDOW_OPEN_ACTION, isTrustedIpcCaller } from './security'
import { createSettingsStore } from './settings-store'
import { createFixtureUpdateClient, type UpdateClient } from './update-client'
import { createAbsentWirePort, type WirePort } from './wire-fixture'
import { HttpWirePort, ServerBridge, tokenReaderFor } from '@ordessa/server-bridge'
import type { Fault } from '@extensions/ordessa.contracts/contract.js'

const distDir = __dirname
const smoke = process.env.MODULAR_SMOKE === '1'
if (smoke) app.disableHardwareAcceleration()
protocol.registerSchemesAsPrivileged([{ scheme: 'ordessa', privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true } }])
void APP_ORIGIN

/** PA-02：产品元数据与版本/构建号的唯一来源是构建期注入的 build-info.json。 */
interface BuildInfo {
  name: string; productName: string; version: string; build: string; description: string
  author: string; license: string; homepage: string; repository: string; builtAt: string
}
function readBuildInfo(): BuildInfo {
  const file = path.join(distDir, 'build-info.json')
  if (!existsSync(file)) throw Error('build-info.json is missing: the app was not built by scripts/build.mjs')
  return JSON.parse(readFileSync(file, 'utf8')) as BuildInfo
}

app.setName(process.env.ORDESSA_APP_NAME ?? 'Ordessa Desktop')
if (process.env.MODULAR_USER_DATA) app.setPath('userData', process.env.MODULAR_USER_DATA)

// --- PA-07 单实例 -----------------------------------------------------------
// 二次启动不新开窗口：聚焦既有实例（这是产品行为，不是测试分支）。
const primaryInstance = app.requestSingleInstanceLock()
// 非主实例立即退出：二次启动只负责把既有窗口叫到前台（PA-07）。
if (!primaryInstance) app.exit(0)

let mainWindow: BrowserWindow | undefined
let logService: LogService | undefined
let releaseDataRootLock: (() => Promise<void>) | undefined
let quitSteps: QuitStep[] = []
const sessionState: { marker: CrashMarker | null; reloaded: boolean } = { marker: null, reloaded: false }

function trusted(event: Electron.IpcMainInvokeEvent, channel: string) {
  const win = mainWindow
  if (!win || !isTrustedIpcCaller({
    windowDestroyed: win.isDestroyed(),
    sameSender: event.sender === win.webContents,
    mainFrame: event.senderFrame === win.webContents.mainFrame,
    url: event.senderFrame?.url ?? '',
  })) throw Error(`Untrusted IPC caller: ${channel}`)
}

app.on('second-instance', () => {
  if (!mainWindow || mainWindow.isDestroyed()) return
  if (mainWindow.isMinimized()) mainWindow.restore()
  mainWindow.focus()
})

app.whenReady().then(async () => {
  const info = readBuildInfo()
  const dataRoot = resolveDataRoot(process.env, defaultHome)
  // 首次启动：数据根不存在是**正常**路径（C-01：缺省走规范），先建再用；
  // 建不起来（符号链接 / 不可写 / 被活进程锁住）才升级成故障 UI，绝不静默、也不写进 dist。
  let probe = await probeDataRoot(dataRoot, { isLive: pid => isProcessAlive(pid) })
  if (!probe.ok && probe.code === 'DATA_ROOT_INVALID') {
    try { await ensureDataRoot(dataRoot) } catch { /* 保留原始故障 */ }
    probe = await probeDataRoot(dataRoot, { isLive: pid => isProcessAlive(pid) })
  }
  const faults: Fault[] = probe.ok ? [] : [probe.fault]
  // 日志回落目录在**用户数据目录**，绝不写进发行目录（PA-11 代码卫生）。
  const fallback = path.join(app.getPath('userData'), 'logs-fallback')
  const logsDir = probe.ok ? probe.logsDir : fallback
  const secretsDir = probe.ok ? probe.secretsDir : path.join(app.getPath('userData'), 'secrets-fallback')
  await mkdir(logsDir, { recursive: true })
  logService = createLogService({
    file: path.join(logsDir, 'desktop.log'),
    secretsDir,
    onUnwritable: health => console.error('日志不可写：已丢弃', health.dropped, '条记录'),
  })
  const log = logService.child('host.desktop')
  log.info('host starting', { version: info.version, build: info.build, dataRoot: path.basename(dataRoot) })

  if (probe.ok) {
    await ensureDataRoot(dataRoot)
    try { releaseDataRootLock = await acquireDataRootLock(dataRoot, { isLive: isProcessAlive }) }
    catch (error) { faults.push(dataRootLockedFault(String(error))) }
  }
  const settings = createSettingsStore(path.join(probe.ok ? dataRoot : logsDir, 'settings.json'))
  await settings.load()
  const update: UpdateClient = createFixtureUpdateClient() // P-C 交付后换成真入口（切换点见报告）
  // INT-01 真实接缝（C-01/C-02/C-03）：服务端由本宿主启动并监管，wire 口打到它身上。
  // 令牌只在主进程（C-03 §4）：`readToken` 由这里供给，WirePort 不存令牌字段。
  const bridge = new ServerBridge({})
  let wire: WirePort
  try {
    const instance = await bridge.start()
    wire = new HttpWirePort({
      origin: instance.origin,
      scope: instance.scope,
      readToken: tokenReaderFor(dataRoot, file => readFile(file, 'utf8')),
    })
    log.info('server started', { scope: instance.scope, pid: instance.pid })
  } catch (error) {
    // C-02 §7：类型化失败 → 故障 UI；缺席实现保持诚实（不假绿、不空白）。
    faults.push(launchFault(error))
    wire = createAbsentWirePort()
  }

  // PA-10 崩溃恢复：上一次会话没干净退出就如实记账。
  const stateDir = path.join(dataRoot, 'state')
  await mkdir(stateDir, { recursive: true })
  const markerFile = path.join(stateDir, 'session.json')
  const previous = await readJson<CrashMarker>(markerFile)
  const crash = startupCrashReport(previous, new Date())
  if (crash.recovered) log.warn('recovered from an unclean previous session', { detail: crash.detail })
  sessionState.marker = beginSession(new Date(), process.pid)
  await writeFile(markerFile, JSON.stringify(sessionState.marker))

  const bundled = process.env.ORDESSA_EMPTY_HOST === '1' ? undefined : path.resolve(distDir, '../../../products/desktop/dist')
  const discovery = await discover(process.env.ORDESSA_EXTENSION_HOME ?? app.getPath('userData'), bundled)
  protocol.handle('ordessa', protocolHandler(path.join(distDir, 'renderer'), discovery))
  // 权限请求一律拒绝：渲染进程没有理由向用户要任何设备/位置/通知权限。
  session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false))

  const windowState = restoreWindowState(await readJson<WindowState>(path.join(stateDir, 'window.json')), displays())
  const frameless = process.platform !== 'darwin'
  const win = new BrowserWindow({
    width: windowState.width, height: windowState.height, ...(windowState.x >= 0 ? { x: windowState.x, y: windowState.y } : {}),
    minWidth: 760, minHeight: 520, show: !smoke, frame: !frameless,
    // PA-03：窗口图标来自构建期导出的产物；缺图时不传该字段（不阻塞启动）。
    ...(existsSync(path.join(distDir, 'icons/flat/256.png')) ? { icon: path.join(distDir, 'icons/flat/256.png') } : {}),
    // PA-23 安全基线：沙箱开、上下文隔离开、Node 集成关。三者都是回归断言的对象。
    webPreferences: { preload: path.join(distDir, 'preload.cjs'), ...SECURE_WEB_PREFERENCES },
  })
  mainWindow = win
  if (windowState.maximized) win.maximize()
  win.setMenuBarVisibility(false)
  win.setAutoHideMenuBar(true)

  if (frameless) installWindowChrome(win)
  installNativeBridge(win, discovery)
  registerIpc({ win, info, dataRoot: probe.ok ? dataRoot : logsDir, logsDir, secretsDir, discovery, settings, update, wire, faults, log })

  // PA-23 安全基线：禁止新窗口、禁止导航、禁止 webview 附着。
  win.webContents.setWindowOpenHandler(() => ({ action: WINDOW_OPEN_ACTION }))
  win.webContents.on('will-navigate', event => event.preventDefault())
  win.webContents.on('will-attach-webview', event => event.preventDefault())
  if (smoke) win.webContents.on('console-message', details => console.error('RENDERER', details.message))

  // PA-10 渲染进程崩溃：记录事实并自动重载（一次，避免崩溃循环）。
  win.webContents.on('render-process-gone', (_event, details) => {
    log.error('renderer process gone', { reason: details.reason })
    if (sessionState.reloaded || win.isDestroyed()) return
    sessionState.reloaded = true
    win.reload()
  })
  app.on('child-process-gone', (_event, details) => log.error('child process gone', { type: details.type, reason: details.reason }))

  const persistWindow = () => writeFile(path.join(stateDir, 'window.json'), JSON.stringify(currentWindowState(win))).catch(() => undefined)
  win.on('close', persistWindow)
  win.on('closed', () => { if (mainWindow === win) mainWindow = undefined })

  quitSteps = [
    // C-02 §5：只终止本宿主 spawn 的进程。
    { name: 'stop-server', run: async () => { await bridge.stop() } },
    { name: 'stop-children', run: () => log.info('stopping child processes') },
    { name: 'release-data-root-lock', run: async () => { await releaseDataRootLock?.() } },
    { name: 'flush-logs', run: async () => { await logService?.close() } },
    { name: 'mark-clean-exit', run: async () => { await writeFile(markerFile, JSON.stringify(cleanSession(sessionState.marker!))) } },
  ]
  app.on('before-quit', event => {
    if (quitting) return
    event.preventDefault()
    void shutdown(undefined)
  })

  await win.loadURL('ordessa://desktop/index.html')
  if (smoke) await runSmokeDriver(win)
}).catch(error => { console.error(error); app.exit(1) })

// --- PA-08 统一清理：清理异常收集起来，与主因一起报，绝不覆盖主因 ----------
let quitting = false
async function shutdown(cause: unknown) {
  quitting = true
  const outcome = await runCleanup(quitSteps)
  if (!outcome.ok) {
    // 清理失败不是主因：主因（若有）先记，清理错误另记，两者都在日志里。
    if (cause !== undefined) console.error('quit cause:', cause)
    console.error('cleanup errors:', JSON.stringify(outcome.errors))
  }
  app.exit(cause !== undefined && !outcome.ok ? 1 : 0)
}
app.on('window-all-closed', () => { if (!quitting) void shutdown(undefined) })

// --- PA-11 smoke 驱动：按路径动态加载，绝不进发行物 --------------------------
async function runSmokeDriver(win: BrowserWindow) {
  const driver = process.env.ORDESSA_SMOKE_DRIVER
  if (!driver) { console.error('Smoke requested without ORDESSA_SMOKE_DRIVER'); app.exit(1); return }
  const module = await import(pathToFileURL(driver).href) as { runSmoke: (ctx: { win: BrowserWindow; app: typeof app }) => Promise<void> }
  await module.runSmoke({ win, app })
}

function installWindowChrome(win: BrowserWindow) {
  ipcMain.handle('window:minimize', event => { trusted(event, 'window:minimize'); win.minimize() })
  ipcMain.handle('window:toggle-maximize', event => { trusted(event, 'window:toggle-maximize'); if (win.isMaximized()) win.unmaximize(); else win.maximize(); return win.isMaximized() })
  ipcMain.handle('window:close', event => { trusted(event, 'window:close'); win.close() })
  ipcMain.handle('window:is-maximized', event => { trusted(event, 'window:is-maximized'); return win.isMaximized() })
  const pushChromeState = () => { if (!win.isDestroyed()) win.webContents.send('window:chrome-state', win.isMaximized()) }
  win.on('maximize', pushChromeState)
  win.on('unmaximize', pushChromeState)
}

function displays() {
  return screen.getAllDisplays().map(display => ({ bounds: { x: display.bounds.x, y: display.bounds.y, width: display.bounds.width, height: display.bounds.height } }))
}

function currentWindowState(win: BrowserWindow): WindowState {
  const maximized = win.isMaximized()
  const bounds = maximized ? win.getNormalBounds() : win.getBounds()
  return { x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height, maximized }
}

function isProcessAlive(pid: number): boolean {
  try { process.kill(pid, 0); return true } catch (error) { return (error as NodeJS.ErrnoException).code === 'EPERM' }
}

async function readJson<T>(file: string): Promise<T | null> {
  try { return JSON.parse(await readFile(file, 'utf8')) as T } catch { return null }
}

/** C-02 §7 的类型化启动失败：原因 + 修复办法 + 日志定位，绝不空白。 */
function launchFault(error: unknown): Fault {
  const typed = error as { code?: string; reason?: string; remedy?: string }
  return {
    kind: 'server-launch-failed',
    reason: typed.reason ?? String(error),
    remedy: typed.remedy ?? '查看日志后重试；若随包运行时缺失，请重新安装应用',
    logRef: 'server:launch',
    code: typed.code ?? 'SERVER_START_FAILED',
  }
}

function dataRootLockedFault(detail: string): Fault {
  return { kind: 'data-root-locked', reason: `数据目录已被另一个 Ordessa 进程占用（${detail}）`, remedy: '关闭另一个实例后重试', logRef: 'data-root:lock', code: 'DATA_ROOT_LOCKED' }
}

// --- IPC 表面：每个通道都做调用方校验（PA-23） -------------------------------
interface IpcContext {
  win: BrowserWindow
  info: BuildInfo
  dataRoot: string
  logsDir: string
  secretsDir: string
  discovery: Awaited<ReturnType<typeof discover>>
  settings: ReturnType<typeof createSettingsStore>
  update: UpdateClient
  wire: WirePort
  faults: Fault[]
  log: ReturnType<LogService['child']>
}

function registerIpc(context: IpcContext) {
  const { win, info, dataRoot, logsDir, secretsDir, discovery, settings, update, wire, log } = context

  ipcMain.handle('extensions:catalog', event => {
    trusted(event, 'extensions:catalog')
    return discovery.catalog // 不含文件路径、凭据、写接口或裸 IPC。
  })
  ipcMain.handle('projects:choose-directory', async event => {
    trusted(event, 'projects:choose-directory')
    const result = await dialog.showOpenDialog(win, { properties: ['openDirectory'] })
    return result.canceled ? undefined : result.filePaths[0]
  })

  // PA-04 关于面板：应用版本、构建号、各插件版本、第三方许可证、许可证全文入口。
  ipcMain.handle('desktop:about', event => {
    trusted(event, 'desktop:about')
    return {
      app: info,
      plugins: discovery.catalog.extensions.map(extension => ({ id: extension.manifest.id, version: extension.manifest.version })),
      licenses: readLicenses(),
      licenseText: path.join(distDir, 'licenses/LICENSE.txt'),
    }
  })
  ipcMain.handle('desktop:open-license', async event => {
    trusted(event, 'desktop:open-license')
    const target = path.join(distDir, 'licenses/LICENSE.txt')
    if (!existsSync(target)) throw Error('许可证全文未随包提供')
    shell.showItemInFolder(target)
    return true
  })

  // PA-12 故障：只下发可渲染的故障，字段不全的条目直接丢掉而不是显示半条。
  ipcMain.handle('desktop:faults', event => { trusted(event, 'desktop:faults'); return sortFaults(context.faults.filter(isRenderableFault)) })
  ipcMain.handle('desktop:data-root', event => { trusted(event, 'desktop:data-root'); return { dataRoot, logsDir } })
  ipcMain.handle('desktop:open-directory', async event => {
    trusted(event, 'desktop:open-directory')
    const target = path.join(dataRoot, 'logs')
    if (!existsSync(target)) throw Error('目录不存在')
    const error = await shell.openPath(target)
    if (error) throw Error(error)
    return true
  })

  // 设置（PA-13/PA-14）
  ipcMain.handle('settings:read', (event, id: string) => { trusted(event, 'settings:read'); return settings.get(String(id)) })
  ipcMain.handle('settings:write', async (event, id: string, value: unknown) => { trusted(event, 'settings:write'); return settings.set(String(id), value) })
  ipcMain.handle('settings:fragments', (event, known: string[]) => { trusted(event, 'settings:fragments'); return settings.fragments(new Set(known.map(String))) })
  ipcMain.handle('settings:log-level', (event, level: string) => {
    trusted(event, 'settings:log-level')
    if (!['debug', 'info', 'warn', 'error'].includes(level)) throw Error('Invalid log level')
    logService?.setLevel(level as 'debug' | 'info' | 'warn' | 'error')
    return logService?.getLevel() ?? 'info'
  })
  ipcMain.handle('settings:log-health', event => { trusted(event, 'settings:log-health'); return logService?.stats() ?? { dropped: 0, writable: true } })

  // 诊断导出（PA-15）：在主进程收集，界面只拿结果。
  ipcMain.handle('diagnostics:export', async event => {
    trusted(event, 'diagnostics:export')
    const result = await dialog.showSaveDialog(win, { defaultPath: 'ordessa-diagnostics.zip' })
    if (result.canceled || !result.filePath) return { exported: false as const }
    const collected = await collectDiagnostics({
      dataRoot, secretsDir, logsDir,
      meta: {
        appVersion: info.version, build: info.build, builtAt: info.builtAt, platform: `${process.platform}-${process.arch}`,
        productManifestSha256: productManifestSha(),
      },
      environment: { os: `${process.platform} ${process.arch}`, cpus: cpus().length, memoryFree: freemem(), memoryTotal: totalmem(), electron: process.versions.electron ?? '' },
      productManifests: readProductManifests(),
    })
    await writeFile(result.filePath, collected.bytes)
    return { exported: true as const, fileName: collected.fileName, fragments: collected.fragments, elapsedMs: collected.elapsedMs }
  })

  // wire 口（PA-21/PA-22）：令牌只在这里（主进程），渲染进程拿不到。
  ipcMain.handle('wire:call', async (event, method: unknown, params: unknown) => {
    trusted(event, 'wire:call')
    return wire.call(String(method), (params ?? {}) as Record<string, unknown>)
  })
  ipcMain.handle('wire:ready', event => { trusted(event, 'wire:ready'); return wire.ready })
  ipcMain.handle('wire:scope', event => { trusted(event, 'wire:scope'); return wire.scope })

  // 更新（PA-13）：UI 与生命周期接线在宿主，引擎在 P-C。
  ipcMain.handle('update:state', event => { trusted(event, 'update:state'); return update.snapshot() })
  ipcMain.handle('update:check', async event => { trusted(event, 'update:check'); return update.check() })
  ipcMain.handle('update:download', async event => { trusted(event, 'update:download'); return update.download() })
  ipcMain.handle('update:apply', async event => {
    trusted(event, 'update:apply')
    const state = await update.apply()
    if (state.state === 'restart-required') {
      // 更新后重启：先走统一清理（停子进程/释放锁/落盘），再 relaunch。
      quitting = true
      void runCleanup(quitSteps).then(() => { app.relaunch(); app.exit(0) })
    }
    return state
  })
}

function readLicenses(): { name: string; version: string; license: string }[] {
  try {
    const raw = readFileSync(path.join(distDir, 'licenses/third-party.json'), 'utf8')
    return JSON.parse(raw) as { name: string; version: string; license: string }[]
  } catch { return [] }
}

function readProductManifests(): Record<string, string> {
  const out: Record<string, string> = {}
  for (const name of ['extensions.json', 'extensions.lock.json']) {
    const file = path.resolve(distDir, '../../../products/desktop', name)
    if (existsSync(file)) out[name] = readFileSync(file, 'utf8')
  }
  return out
}

function productManifestSha(): string {
  const manifests = readProductManifests()
  return createHash('sha256').update(JSON.stringify(manifests)).digest('hex')
}
