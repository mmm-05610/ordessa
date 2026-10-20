import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mkdtemp, mkdir, readFile, rm, symlink, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { discover } from '@ordessa/extension-host/main'
import { installNativeBridge } from './index'

const electron = vi.hoisted(() => {
  const handlers = new Map<string, (...args: unknown[]) => Promise<unknown>>()
  return {
    handlers,
    ipcMain: {
      handle: (channel: string, fn: (...args: unknown[]) => Promise<unknown>) => handlers.set(channel, fn),
      removeHandler: (channel: string) => { handlers.delete(channel) },
    },
  }
})
vi.mock('electron', () => ({ ipcMain: electron.ipcMain }))

interface FakeWindow {
  isDestroyed(): boolean
  once(event: string, listener: () => void): void
  webContents: { mainFrame: { url: string }; send(channel: string, payload: unknown): void }
  sent: Array<{ channel: string; payload: any }>
}

function makeWindow(url = 'ordessa://desktop/index.html'): FakeWindow {
  const win: FakeWindow = {
    isDestroyed: () => false,
    once: () => {},
    webContents: {
      mainFrame: { url },
      send: (channel, payload) => { win.sent.push({ channel, payload }) },
    },
    sent: [],
  }
  return win
}

const trusted = (win: FakeWindow) => ({ sender: win.webContents, senderFrame: win.webContents.mainFrame })
const invoke = (channel: string, event: unknown, ...args: unknown[]) => electron.handlers.get(channel)!(event, ...args)

let home = ''
let bridge: ReturnType<typeof installNativeBridge> | undefined
let win: FakeWindow

const adapterSource = (logUrl: string) => `
  import { appendFile } from 'node:fs/promises'
  const log = new URL(${JSON.stringify(logUrl)})
  const record = async value => appendFile(log, JSON.stringify(value) + '\\n', 'utf8')
  await record({ type: 'import' })
  export default () => ({
    open: async onFrame => {
      await record({ type: 'open' })
      onFrame({ type: 'opened' })
      return {
        send: async frame => { await record({ type: 'send', frame }); return { accepted: true } },
        close: async () => { await record({ type: 'close' }) },
      }
    },
  })
`

async function fixture(options: { enabled?: string[]; native?: string; symlinkOutside?: boolean } = {}) {
  const dataRoot = path.join(home, 'data')
  const extensionRoot = path.join(dataRoot, 'extensions', 'fixture.server')
  await mkdir(extensionRoot, { recursive: true })
  await writeFile(path.join(dataRoot, 'extensions.json'), JSON.stringify({ enabled: options.enabled ?? ['fixture.server'] }), 'utf8')
  const manifest: Record<string, unknown> = { id: 'fixture.server', version: '1.0.0', hostApi: '2', entry: 'entry.js' }
  if (options.native !== undefined) manifest.native = options.native
  else if (!('native' in options)) manifest.native = 'native.js'
  await writeFile(path.join(extensionRoot, 'manifest.json'), JSON.stringify(manifest), 'utf8')
  await writeFile(path.join(extensionRoot, 'package.json'), JSON.stringify({ type: 'module' }), 'utf8')
  await writeFile(path.join(extensionRoot, 'entry.js'), 'export default () => ({})', 'utf8')
  const logPath = path.join(extensionRoot, 'calls.jsonl')
  const outsidePath = path.join(home, 'outside.js')
  if (options.symlinkOutside) {
    await writeFile(outsidePath, adapterSource(pathToFileURL(logPath).href), 'utf8')
    await symlink(outsidePath, path.join(extensionRoot, 'native.js'))
  } else if (manifest.native === 'native.js') {
    await writeFile(path.join(extensionRoot, 'native.js'), adapterSource(pathToFileURL(logPath).href), 'utf8')
  }
  const discovery = await discover(dataRoot)
  return { dataRoot, extensionRoot, logPath, discovery }
}

function install(discovery: Awaited<ReturnType<typeof discover>>) {
  win = makeWindow()
  bridge = installNativeBridge(win as never, discovery)
  return win
}

async function calls(logPath: string) {
  try {
    return (await readFile(logPath, 'utf8')).trim().split('\n').filter(Boolean).map(line => JSON.parse(line))
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return []
    throw error
  }
}

beforeEach(async () => {
  electron.handlers.clear()
  home = await mkdtemp(path.join(tmpdir(), 'ordessa-native-provenance-'))
  await writeFile(path.join(home, 'package.json'), JSON.stringify({ type: 'module' }), 'utf8')
})
afterEach(async () => {
  try { await bridge?.dispose() } finally {
    bridge = undefined
    electron.handlers.clear()
    if (home) await rm(home, { recursive: true, force: true })
    home = ''
  }
})

describe('native adapter provenance from real discovery', () => {
  it('imports and opens only the enabled confined native entry, then forwards send and close', async () => {
    const { logPath, discovery } = await fixture()
    expect(discovery.installed.has('fixture.server')).toBe(true)
    expect(discovery.catalog.extensions.map(item => item.manifest.id)).toEqual(['fixture.server'])
    const w = install(discovery)

    const instanceId = await invoke('agent-native:open', trusted(w), 'fixture.server') as string
    expect(instanceId).toMatch(/^[0-9a-f-]{36}$/)
    expect(w.sent).toEqual([{ channel: 'agent-native:event', payload: { instanceId, frame: { type: 'opened' } } }])
    expect(await invoke('agent-native:send', trusted(w), instanceId, { type: 'ping' })).toEqual({ accepted: true })
    await invoke('agent-native:close', trusted(w), instanceId)
    expect(await calls(logPath)).toEqual([
      { type: 'import' }, { type: 'open' }, { type: 'send', frame: { type: 'ping' } }, { type: 'close' },
    ])
  })

  it('does not import a valid but disabled extension, and refuses unknown IDs from the real installed map', async () => {
    const { logPath, discovery } = await fixture({ enabled: [] })
    expect(discovery.installed.size).toBe(0)
    expect(discovery.catalog.extensions).toEqual([])
    const w = install(discovery)
    await expect(invoke('agent-native:open', trusted(w), 'fixture.server')).rejects.toThrow('Native adapter unavailable')
    await expect(invoke('agent-native:open', trusted(w), 'unknown.server')).rejects.toThrow('Native adapter unavailable')
    expect(await calls(logPath)).toEqual([])
  })

  it('refuses an enabled extension with no native declaration without importing its UI entry', async () => {
    const { logPath, discovery } = await fixture({ native: undefined })
    expect(discovery.installed.has('fixture.server')).toBe(true)
    const w = install(discovery)
    await expect(invoke('agent-native:open', trusted(w), 'fixture.server')).rejects.toThrow('Native adapter unavailable')
    expect(await calls(logPath)).toEqual([])
  })

  it.each([
    ['absolute native entry', path.resolve('/outside/native.js')],
    ['traversal native entry', '../outside.js'],
  ])('does not import an enabled manifest with a %s', async (_label, native) => {
    const { logPath, discovery } = await fixture({ native })
    expect(discovery.installed.has('fixture.server')).toBe(false)
    const w = install(discovery)
    await expect(invoke('agent-native:open', trusted(w), 'fixture.server')).rejects.toThrow('Native adapter unavailable')
    expect(await calls(logPath)).toEqual([])
  })

  it('does not import an enabled native entry whose symlink resolves outside its extension root', async () => {
    const { logPath, discovery } = await fixture({ symlinkOutside: true })
    expect(discovery.installed.has('fixture.server')).toBe(false)
    const w = install(discovery)
    await expect(invoke('agent-native:open', trusted(w), 'fixture.server')).rejects.toThrow('Native adapter unavailable')
    expect(await calls(logPath)).toEqual([])
  })

  it('rejects an untrusted IPC caller before importing the discovered adapter', async () => {
    const { logPath, discovery } = await fixture()
    const w = install(discovery)
    await expect(invoke('agent-native:open', {
      sender: w.webContents,
      senderFrame: { url: 'https://untrusted.invalid/' },
    }, 'fixture.server')).rejects.toThrow('Untrusted native transport caller')
    expect(await calls(logPath)).toEqual([])
  })
})
