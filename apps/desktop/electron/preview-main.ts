// Test-only controlled visual preview for the UI optimization round. Boots the real product UI
// (workbench + sessions + conversation + connections statusbar) driven by the anonymous
// example.ui-preview fixture connectors, captures the five required screenshot states and runs
// interaction regression checks. It does not touch the production main process or the bridge.
import { app, BrowserWindow, ipcMain, protocol, session } from 'electron'
import path from 'node:path'
import { mkdir, writeFile } from 'node:fs/promises'
import { discover } from '@ordessa/extension-host/main'
import { protocolHandler } from '@ordessa/extension-host/main'

app.setName('Ordessa Desktop Preview')
if (process.env.MODULAR_USER_DATA) app.setPath('userData', process.env.MODULAR_USER_DATA)
protocol.registerSchemesAsPrivileged([{ scheme: 'ordessa', privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true } }])

const outDir = process.env.ORDESSA_PREVIEW_OUT ?? 'docs/ui-preview'
const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

const HELPERS = `(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const waitFor = async (fn, limit = 200) => { for (let i = 0; i < limit; i++) { if (fn()) return true; await sleep(50); } return false; };
  const toggle = () => document.querySelector('.conn-status-toggle');
  const popover = () => document.querySelector('[role="group"][aria-label="Agent connections"]');
  const openPopover = async () => { if (!popover()) { toggle().click(); if (!await waitFor(popover)) throw Error('popover missing'); } };
  const closePopover = async () => { if (popover()) { toggle().click(); await waitFor(() => !popover()); } };
  const pick = async id => { await openPopover(); document.querySelector('[data-connection-id="' + id + '"]').click(); await waitFor(() => !!document.querySelector('.conn-dot-connected')); await closePopover(); };
`

let win: BrowserWindow | undefined
app.whenReady().then(async () => {
  const bundled = process.env.ORDESSA_EMPTY_HOST === '1' ? undefined : path.resolve(__dirname, '../../../products/desktop/dist')
  const discovery = await discover(process.env.ORDESSA_EXTENSION_HOME ?? app.getPath('userData'), bundled)
  // 预览驱动编译在 dist-preview/，渲染产物仍在 dist/（PA-11：驱动不进发行目录）。
  const rendererRoot = process.env.ORDESSA_PREVIEW_RENDERER ?? path.join(__dirname, 'renderer')
  protocol.handle('ordessa', protocolHandler(rendererRoot, discovery))
  session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false))
  win = new BrowserWindow({
    width: 1280, height: 860, show: false, frame: false,
    // 驱动与 preload 分处两个目录（驱动不进发行目录），preload 路径由脚本显式给出。
    webPreferences: {
      preload: process.env.ORDESSA_PREVIEW_PRELOAD ?? path.join(__dirname, 'preload.cjs'),
      contextIsolation: true, nodeIntegration: false, sandbox: true,
    },
  })
  win!.setMenuBarVisibility(false)
  ipcMain.handle('extensions:catalog', () => discovery.catalog) // Same catalog the production shell exposes to the preload.
  // Mirror the production frameless window-control IPC so screenshots are faithful.
  ipcMain.handle('window:minimize', () => win?.minimize())
  ipcMain.handle('window:toggle-maximize', () => { if (!win) return false; if (win.isMaximized()) win.unmaximize(); else win.maximize(); return win.isMaximized() })
  ipcMain.handle('window:close', () => win?.close())
  ipcMain.handle('window:is-maximized', () => win?.isMaximized() ?? false)
  const pushChromeState = () => { if (win && !win.isDestroyed()) win.webContents.send('window:chrome-state', win.isMaximized()) }
  win.on('maximize', pushChromeState); win.on('unmaximize', pushChromeState)
  const consoleErrors: string[] = []
  win!.webContents.on('console-message', details => { if (details.level === 'error') consoleErrors.push(details.message) })
  win!.webContents.on('will-navigate', event => event.preventDefault())
  await win.loadURL('ordessa://desktop/index.html')
  const run = (step: string, body: string) => win!.webContents.executeJavaScript(HELPERS + 'try { ' + body + ' } catch (error) { throw new Error(' + JSON.stringify(step + ': ') + ' + String(error)); } })()')
  const shot = async (name: string) => { await mkdir(outDir, { recursive: true }); await writeFile(path.join(outDir, name), (await win!.webContents.capturePage()).toPNG()) }
  win!.showInactive()
  await sleep(300)

  const result: Record<string, unknown> = {}
  result.boot = await run('boot', `
    await waitFor(() => document.documentElement.dataset.ready === 'true', 400);
    [...document.querySelectorAll('nav button')].find(b => b.getAttribute('aria-label') === 'Agents')?.click();
    const nav = await waitFor(() => !!toggle());
    await openPopover();
    const connectors = popover().querySelectorAll('[data-connection-id]').length;
    await closePopover();
    return { nav, connectors };`)
  result.empty = await run('empty', `
    await pick('ui-preview.empty');
    await waitFor(() => !!document.querySelector('.agent-placeholder'));
    return {
      placeholder: !!document.querySelector('.agent-placeholder'),
      emptyList: !!document.querySelector('.agent-sessions .agent-empty'),
      rightInert: document.querySelector('[data-region="right"]')?.hasAttribute('inert') ?? false,
      bottomInert: document.querySelector('[data-region="bottom"]')?.hasAttribute('inert') ?? false,
    };`)
  await shot('01-empty.png')
  result.history = await run('history', `
    await pick('ui-preview.history');
    const opened = await waitFor(() => document.querySelectorAll('.agent-message').length >= 4);
    const user = document.querySelector('.agent-message[data-role="user"]');
    const assistant = document.querySelector('.agent-message[data-role="assistant"]');
    return { opened,
      userRole: !!user, assistantRole: !!assistant,
      userRight: !!user && user.getBoundingClientRect().left > assistant.getBoundingClientRect().left,
      assistantFont: getComputedStyle(assistant).fontSize,
      userRadius: getComputedStyle(user).borderTopRightRadius,
      composer: !!document.querySelector('.agent-compose textarea'),
      composerRadius: getComputedStyle(document.querySelector('.agent-compose')).borderRadius,
      toolCards: document.querySelectorAll('.agent-tool').length,
      thinkingCards: document.querySelectorAll('.agent-reasoning').length };`)
  await shot('02-history.png')
  result.sessionSwitch = await run('sessionSwitch', `
    const row = [...document.querySelectorAll('.agent-session-list button')].find(b => b.textContent.includes('Weekly status draft'));
    row.click();
    const switched = await waitFor(() => document.querySelectorAll('.agent-message').length === 2 && document.querySelector('.agent-conversation-head h2')?.textContent === 'Weekly status draft');
    const back = [...document.querySelectorAll('.agent-session-list button')].find(b => b.textContent.includes('Fixture module review'));
    back.click();
    const restored = await waitFor(() => document.querySelectorAll('.agent-message').length === 4);
    return { switched, restored };`)
  result.send = await run('send', `
    const field = document.querySelector('.agent-compose textarea');
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(field, 'Fixture send check');
    field.dispatchEvent(new Event('input', { bubbles: true }));
    const btn = () => [...document.querySelectorAll('.agent-compose button')].find(b => b.textContent === 'Send');
    const enabled = await waitFor(() => !!btn() && !btn().disabled, 60);
    btn().click();
    const replied = await waitFor(() => [...document.querySelectorAll('.agent-message')].at(-1)?.textContent.includes('Echo (fixture)'));
    return { enabled, replied, total: document.querySelectorAll('.agent-message').length,
      userBubbles: document.querySelectorAll('.agent-message[data-role="user"]').length };`)
  result.toolExpand = await run('toolExpand', `
    const tool = document.querySelector('.agent-tool');
    tool.querySelector('summary').click();
    const expanded = await waitFor(() => (tool.querySelector('pre')?.getBoundingClientRect().height ?? 0) > 0);
    const thinking = document.querySelector('.agent-reasoning');
    thinking.querySelector('summary').click();
    const thinkingOpen = await waitFor(() => thinking.open);
    return { expanded, thinkingOpen };`)
  await shot('03-tool-expanded.png')
  result.approval = await run('approval', `
    await pick('ui-preview.approval');
    const card = await waitFor(() => !!document.querySelector('.agent-interaction'));
    return { card, inThread: !!document.querySelector('.agent-interactions-in-thread'),
      choices: [...document.querySelectorAll('.agent-interaction button')].map(b => b.textContent),
      runChip: document.querySelector('.agent-run-state')?.dataset.status };`)
  await shot('04-approval.png')
  result.approvalRespond = await run('approvalRespond', `
    [...document.querySelectorAll('.agent-interaction button')].find(b => b.textContent === 'Allow once').click();
    const resolved = await waitFor(() => document.querySelector('.agent-interaction header small')?.textContent === 'resolved');
    const runDone = await waitFor(() => ['completed', 'idle'].includes(document.querySelector('.agent-run-state')?.dataset.status ?? 'idle'));
    return { resolved, runDone };`)
  result.running = await run('running', `
    await pick('ui-preview.running');
    const chipRunning = await waitFor(() => document.querySelector('.agent-run-state')?.dataset.status === 'running');
    const stop = [...document.querySelectorAll('.agent-compose button')].find(b => b.textContent === 'Request stop');
    return { chipRunning, stopVisible: !!stop, stopEnabled: !!stop && !stop.disabled,
      runningTool: !!document.querySelector('.agent-tool[data-tool-state="running"]') };`)
  await shot('05-running.png')
  result.stop = await run('stop', `
    [...document.querySelectorAll('.agent-compose button')].find(b => b.textContent === 'Request stop').click();
    const requested = await waitFor(() => document.querySelector('.agent-run-state')?.dataset.status === 'stop-requested');
    const notice = [...document.querySelectorAll('.agent-notice')].some(p => p.textContent.includes('Stop requested'));
    const cancelled = await waitFor(() => document.querySelector('.agent-run-state')?.dataset.status === 'cancelled');
    return { requested, notice, cancelled };`)
  result.gateRelease = await run('gateRelease', `
    await pick('ui-preview.history');
    return { backInHistory: document.querySelectorAll('.agent-message').length === 6 };`)
  result.layout = await run('layout', `
    const left = () => document.querySelector('[data-region="left"]');
    document.querySelector('button[aria-label="收起左侧栏"]').click();
    const collapsed = await waitFor(() => left()?.hasAttribute('inert'));
    document.querySelector('button[aria-label="展开左侧栏"]').click();
    const expanded = await waitFor(() => !left()?.hasAttribute('inert'));
    return { collapsed, expanded,
      separator: !!document.getElementById('resize-left'),
      leftWidth: Math.round(left().getBoundingClientRect().width) };`)
  const separatorPoint = await run('separatorPoint', `
    const r = document.getElementById('resize-left').getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + Math.min(r.height / 2, 200) };`) as { x: number, y: number }
  await run('resizeArmed', `
    window.__pe = { down: 0, move: 0, up: 0 };
    window.addEventListener('pointerdown', () => { window.__pe.down++ }, true);
    window.addEventListener('pointermove', () => { window.__pe.move++ }, true);
    window.addEventListener('pointerup', () => { window.__pe.up++ }, true);
    return true;`)
  win!.focus()
  await sleep(150)
  const widthBefore = await run('widthBefore', `return Math.round(document.querySelector('[data-region="left"]').getBoundingClientRect().width);`) as number
  // Fully synthetic trusted-shaped sequence: react-resizable-panels aborts when a pointermove
  // arrives with buttons === 0, which Electron sendInputEvent cannot express mid-drag.
  const dragProbe = await run('resizeMoves', `
    const sep = document.getElementById('resize-left');
    const x = ${JSON.stringify(separatorPoint.x)}, y = ${JSON.stringify(separatorPoint.y)};
    const fire = (type, at, buttons) => sep.dispatchEvent(new PointerEvent(type, { pointerId: 1, isPrimary: true, pointerType: 'mouse',
      button: type === 'pointerup' ? -1 : 0, buttons, clientX: at, clientY: y, bubbles: true, cancelable: true }));
    fire('pointerdown', x, 1);
    await sleep(60);
    const probe = { stateAfterDown: sep.dataset.separator, widths: [], stateAfterUp: '' };
    for (let i = 1; i <= 8; i++) {
      fire('pointermove', x + i * 12, 1);
      await sleep(40);
      probe.widths.push(Math.round(document.getElementById('wb-left').getBoundingClientRect().width));
    }
    fire('pointerup', x + 96, 0);
    await sleep(150);
    probe.stateAfterUp = sep.dataset.separator;
    return probe;`) as Record<string, unknown>
  await sleep(100)
  const widthAfter = await run('widthAfter', `return Math.round(document.querySelector('[data-region="left"]').getBoundingClientRect().width);`) as number
  const pointerCounts = await run('pointerCounts', `return window.__pe;`) as Record<string, number | string>
  // Last resize path: the separator's own keyboard handler drives the same panel.resize commit.
  await run('focusSep', `document.getElementById('resize-left').focus(); return true;`)
  const keyboard: Record<string, number> = { before: widthAfter }
  for (const [tag, code] of [['right', 'Right'], ['arrowRight', 'ArrowRight']] as const) {
    for (let i = 0; i < 4; i++) {
      await win!.webContents.sendInputEvent({ type: 'keyDown', keyCode: code })
      await win!.webContents.sendInputEvent({ type: 'keyUp', keyCode: code })
      await sleep(60)
    }
    keyboard[tag] = await run(`widthKey${tag}`, `return Math.round(document.getElementById('wb-left').getBoundingClientRect().width);`) as number
  }
  result.resize = { widthBefore, widthAfter, dragged: widthAfter > widthBefore + 8, pointerCounts, dragProbe,
    keyboard, keyboardResized: (keyboard.right ?? widthAfter) > widthBefore + 4 || (keyboard.arrowRight ?? widthAfter) > widthBefore + 4 }
  await win!.webContents.sendInputEvent({ type: 'keyDown', keyCode: 'Tab' })
  await win!.webContents.sendInputEvent({ type: 'keyUp', keyCode: 'Tab' })
  await win!.webContents.sendInputEvent({ type: 'keyDown', keyCode: 'Tab' })
  await win!.webContents.sendInputEvent({ type: 'keyUp', keyCode: 'Tab' })
  await sleep(150)
  result.focus = await run('focus', `
    const active = document.activeElement;
    return { focused: !!active && active !== document.body && active !== document.documentElement, tag: active?.tagName };`)
  win!.setBounds({ width: 1280, height: 560 })
  await sleep(250)
  result.scroll = await run('scroll', `
    // Grow the transcript first: at this window height six fixture messages still fit the viewport.
    for (let i = 0; i < 5; i++) {
      const field = document.querySelector('.agent-compose textarea');
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(field, 'Filler scroll probe ' + i);
      field.dispatchEvent(new Event('input', { bubbles: true }));
      await sleep(30);
      [...document.querySelectorAll('.agent-compose button')].find(b => b.textContent === 'Send').click();
      await sleep(260);
    }
    await waitFor(() => document.querySelectorAll('.agent-message').length >= 16, 60);
    const info = { innerHeight: window.innerHeight, messages: document.querySelectorAll('.agent-message').length, chain: [] };
    let scroller = null;
    for (let n = document.querySelector('.agent-viewport'); n; n = n.parentElement) {
      const style = getComputedStyle(n);
      info.chain.push({ el: String(n.className).slice(0, 40), scrollH: n.scrollHeight, clientH: n.clientHeight, overflowY: style.overflowY });
      if (!scroller && n.scrollHeight > n.clientHeight + 4 && /auto|scroll/.test(style.overflowY)) scroller = n;
    }
    if (scroller) { scroller.scrollTop = scroller.scrollHeight; info.scrolled = scroller.scrollTop > 4; info.scroller = String(scroller.className).slice(0, 40); scroller.scrollTop = 0; }
    else { const se = document.scrollingElement; se.scrollTop = se.scrollHeight; info.scrolled = se.scrollTop > 4; info.scroller = 'document'; se.scrollTop = 0; }
    return info;`)
  win!.setBounds({ width: 760, height: 520 })
  await sleep(350)
  result.narrow = await run('narrow', `
    const wb = document.querySelector('.wb');
    return { overflowX: wb.scrollWidth - wb.clientWidth,
      composerVisible: !!document.querySelector('.agent-compose textarea')?.getBoundingClientRect().width };`)
  await shot('06-narrow.png')
  win!.setBounds({ width: 1280, height: 860 })
  await sleep(200)
  result.consoleErrors = consoleErrors
  console.log('PREVIEW_RESULT ' + JSON.stringify(result))
  app.exit(0)
}).catch(async error => {
  console.error('PREVIEW_FAILED', error?.message ?? error)
  try {
    if (!win) throw Error('no window yet')
    console.log('PREVIEW_DIAG ' + JSON.stringify(await win!.webContents.executeJavaScript(`(async () => ({
      ready: document.documentElement?.dataset?.ready, settled: document.documentElement?.dataset?.settled,
      nav: [...document.querySelectorAll('nav button')].map(b => b.getAttribute('aria-label')),
      toggle: !!document.querySelector('.conn-status-toggle'),
      alerts: [...document.querySelectorAll('[role="alert"]')].map(p => p.textContent),
      regions: [...document.querySelectorAll('[data-region]')].map(s => s.getAttribute('data-region') + ':' + s.childElementCount),
    }))()`)))
  } catch { /* the renderer may already be gone */ }
  app.exit(1)
})
app.on('window-all-closed', () => app.quit())
