import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mkdtemp, realpath, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
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

declare global {
  // Set from fixture adapter modules to observe connection closes across the module boundary.
  // eslint-disable-next-line no-var
  var __closed: number | undefined
}

interface FakeWindow { isDestroyed(): boolean; webContents: { mainFrame: { url: string }
  send(channel: string, payload: unknown): void }
  sent: Array<{ channel: string; payload: any }>
  once(event: string, cb: () => void): void; fire(event: string): void }

function makeWindow(url = 'ordessa://desktop/index.html'): FakeWindow {
  const listeners = new Map<string, Array<() => void>>()
  const win: FakeWindow = {
    isDestroyed: () => false,
    webContents: {
      mainFrame: { url },
      send: (channel, payload) => { win.sent.push({ channel, payload }) },
    },
    sent: [],
    once: (event, cb) => { listeners.set(event, [...(listeners.get(event) ?? []), cb]) },
    fire: event => { for (const cb of listeners.get(event) ?? []) cb() },
  }
  return win
}

const trusted = (win: FakeWindow) => ({ sender: win.webContents, senderFrame: win.webContents.mainFrame })
const invoke = (channel: string, event: unknown, ...args: unknown[]) => electron.handlers.get(channel)!(event, ...args)

let home = ''
let extensionRoot = ''
let bridge: ReturnType<typeof installNativeBridge> | undefined
let win: FakeWindow

async function fixtureAdapter(source: string, name = 'adapter.mjs'): Promise<string> {
  await writeFile(path.join(extensionRoot, name), source, 'utf8')
  return name
}
async function install(native = 'adapter.mjs'): Promise<FakeWindow> {
  win = makeWindow()
  const discovery = { catalog: { extensions: [], failures: [] },
    installed: new Map([['fixture.server', { root: extensionRoot, manifest: { native } }]]) }
  bridge = installNativeBridge(win as never, discovery as never)
  return win
}

beforeEach(async () => {
  home = await mkdtemp(path.join(tmpdir(), 'ordessa-bridge-'))
  extensionRoot = await realpath(home)
})
afterEach(async () => {
  bridge?.dispose()
  bridge = undefined
  electron.handlers.clear()
})

describe('restricted caller surface', () => {
  it('rejects open from a sub frame, another webContents, or a repurposed main frame url', async () => {
    const w = await install()
    await expect(invoke('agent-native:open', { sender: w.webContents, senderFrame: { url: 'ordessa://desktop/index.html' } }, 'fixture.server'))
      .rejects.toThrow('Untrusted native transport caller')
    await expect(invoke('agent-native:open', { sender: {}, senderFrame: w.webContents.mainFrame }, 'fixture.server'))
      .rejects.toThrow('Untrusted native transport caller')
    await expect(invoke('agent-native:open', { sender: w.webContents, senderFrame: { url: 'https://evil.test/' } }, 'fixture.server'))
      .rejects.toThrow('Untrusted native transport caller')
    w.webContents.mainFrame.url = 'https://evil.test/'
    await expect(invoke('agent-native:send', trusted(w), 'any', {})).rejects.toThrow('Untrusted native transport caller')
    await expect(invoke('agent-native:close', trusted(w), 'any')).rejects.toThrow('Untrusted native transport caller')
  })

  it('window close removes every handler and closes live adapter connections', async () => {
    await fixtureAdapter('export default () => ({ open: () => ({ send: async () => {}, close: async () => { globalThis.__closed = (globalThis.__closed ?? 0) + 1 } }) })')
    const w = await install()
    await invoke('agent-native:open', trusted(w), 'fixture.server')
    w.fire('closed')
    expect(['agent-native:open', 'agent-native:send', 'agent-native:close'].some(channel => electron.handlers.has(channel))).toBe(false)
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(globalThis.__closed).toBe(1)
    delete globalThis.__closed
    bridge = undefined
  })
})

describe('adapter confinement', () => {
  it('only opens installed adapters that declare a native entry', async () => {
    const w = await install()
    await expect(invoke('agent-native:open', trusted(w), 'not.installed')).rejects.toThrow('Native adapter unavailable')
    await expect(invoke('agent-native:open', trusted(w), 42 as never)).rejects.toThrow('Invalid adapter')
    win = makeWindow()
    const discovery = { catalog: { extensions: [], failures: [] },
      installed: new Map([['fixture.server', { root: extensionRoot, manifest: {} }]]) }
    bridge = installNativeBridge(win as never, discovery as never)
    await expect(invoke('agent-native:open', trusted(win), 'fixture.server')).rejects.toThrow('Native adapter unavailable')
  })

  it('refuses native entries that escape the extension root', async () => {
    await writeFile(path.join(path.dirname(extensionRoot), 'outside.mjs'), 'export default () => ({ open: () => ({ send: async () => {}, close: async () => {} }) })', 'utf8')
    const w = await install('../outside.mjs')
    await expect(invoke('agent-native:open', trusted(w), 'fixture.server')).rejects.toThrow()
  })

  it('rejects modules without a valid transport factory', async () => {
    await fixtureAdapter('export default 7', 'entry-bad.mjs')
    let w = await install('entry-bad.mjs')
    await expect(invoke('agent-native:open', trusted(w), 'fixture.server')).rejects.toThrow('Invalid native adapter entry')
    bridge?.dispose()
    await fixtureAdapter('export default () => ({})', 'transport-bad.mjs')
    w = await install('transport-bad.mjs')
    await expect(invoke('agent-native:open', trusted(w), 'fixture.server')).rejects.toThrow('Invalid native transport')
  })
})

describe('frame validation and lifecycle', () => {
  it('rejects renderer->adapter frames above 1MiB or unserializable', async () => {
    await fixtureAdapter('export default () => ({ open: () => ({ send: async () => {}, close: async () => {} }) })')
    const w = await install()
    const instanceId = await invoke('agent-native:open', trusted(w), 'fixture.server')
    await expect(invoke('agent-native:send', trusted(w), instanceId, 'x'.repeat(2 * 1024 * 1024)))
      .rejects.toThrow('Invalid native transport frame')
    const circular: Record<string, unknown> = {}
    circular.self = circular
    await expect(invoke('agent-native:send', trusted(w), instanceId, circular)).rejects.toThrow()
  })

  it('delivers adapter frames to the main frame with the instance id; oversized pushes surface as error events', async () => {
    await fixtureAdapter(`export default () => ({ open: onFrame => {
      for (let i = 0; i < 3; i++) onFrame({ seq: i })
      onFrame('x'.repeat(2 * 1024 * 1024))
      return { send: async () => {}, close: async () => {} } } })`)
    const w = await install()
    const instanceId = await invoke('agent-native:open', trusted(w), 'fixture.server') as string
    const events = w.sent.filter(entry => entry.channel === 'agent-native:event')
    expect(events.filter(entry => entry.payload.frame).map(entry => entry.payload.frame)).toEqual([{ seq: 0 }, { seq: 1 }, { seq: 2 }])
    const errors = events.filter(entry => entry.payload.error)
    expect(errors.length).toBe(1)
    expect(errors[0].payload).toEqual({ instanceId, error: 'Invalid native transport frame' })
    expect(events.every(entry => entry.payload.instanceId === instanceId)).toBe(true)
  })

  it('bounds startup buffering at 256 frames', async () => {
    await fixtureAdapter(`export default () => ({ open: onFrame => {
      for (let i = 0; i < 257; i++) onFrame({ seq: i })
      return { send: async () => {}, close: async () => {} } } })`)
    const w = await install()
    await invoke('agent-native:open', trusted(w), 'fixture.server')
    const events = w.sent.filter(entry => entry.channel === 'agent-native:event')
    expect(events.filter(entry => entry.payload.frame).length).toBe(256)
    expect(events.filter(entry => entry.payload.error).length).toBe(1)
  })

  it('unknown and closed instances never reach a live connection; close is single-shot per instance', async () => {
    await fixtureAdapter('export default () => ({ open: () => ({ send: async f => f, close: async () => { globalThis.__closed = (globalThis.__closed ?? 0) + 1 } }) })')
    const w = await install()
    const instanceId = await invoke('agent-native:open', trusted(w), 'fixture.server') as string
    await expect(invoke('agent-native:send', trusted(w), 'other-instance', {})).rejects.toThrow('Native instance unavailable')
    expect(await invoke('agent-native:send', trusted(w), instanceId, { ping: 1 })).toEqual({ ping: 1 })
    await invoke('agent-native:close', trusted(w), instanceId)
    await invoke('agent-native:close', trusted(w), instanceId)
    expect(globalThis.__closed).toBe(1)
    delete globalThis.__closed
    await expect(invoke('agent-native:send', trusted(w), instanceId, {})).rejects.toThrow('Native instance unavailable')
  })
})

describe('registration-gated identity frames (FC-0034 fixture piece)', () => {
  it('surfaces a hello ack only after main-side auth ran, preserving adapter frame order', async () => {
    await fixtureAdapter(`export default () => ({
      open: onFrame => ({
        send: async frame => {
          if (frame?.type === 'server:hello') { onFrame({ seq: 0 }); onFrame({ type: 'hello:ack', serverId: 'srv-A' }); return { accepted: true } }
          throw Error('Unknown protocol frame')
        },
        close: async () => {},
      }),
    })`)
    const w = await install()
    const instanceId = await invoke('agent-native:open', trusted(w), 'fixture.server') as string
    expect(w.sent.filter(entry => entry.payload?.frame?.type === 'hello:ack').length).toBe(0)
    await invoke('agent-native:send', trusted(w), instanceId, { type: 'server:hello' })
    const acks = w.sent.filter(entry => entry.payload?.frame?.type === 'hello:ack')
    expect(acks).toEqual([{ channel: 'agent-native:event', payload: { instanceId, frame: { type: 'hello:ack', serverId: 'srv-A' } } }])
    expect(w.sent.map(entry => entry.payload.frame).filter(Boolean)).toEqual([{ seq: 0 }, { type: 'hello:ack', serverId: 'srv-A' }])
  })

  it('a failed main-side auth leaves no registerable ack frame in the event stream', async () => {
    await fixtureAdapter(`export default () => ({
      open: onFrame => ({
        send: async frame => {
          if (frame?.type === 'server:hello') { onFrame({ type: 'hello:error' }); throw Error('401 unauthorized') }
          throw Error('Unknown protocol frame')
        },
        close: async () => {},
      }),
    })`)
    const w = await install()
    const instanceId = await invoke('agent-native:open', trusted(w), 'fixture.server') as string
    await expect(invoke('agent-native:send', trusted(w), instanceId, { type: 'server:hello' })).rejects.toThrow('401 unauthorized')
    expect(w.sent.filter(entry => entry.payload?.frame?.type === 'hello:ack').length).toBe(0)
  })

  it('keeps per-instance event streams apart across instances of one adapter', async () => {
    await fixtureAdapter(`export default () => ({
      open: onFrame => ({
        send: async frame => { if (frame?.type === 'ping') { onFrame({ pong: frame.tag }); return 'ok' } throw Error('Unknown protocol frame') },
        close: async () => {},
      }),
    })`)
    const w = await install()
    const first = await invoke('agent-native:open', trusted(w), 'fixture.server') as string
    const second = await invoke('agent-native:open', trusted(w), 'fixture.server') as string
    expect(second).not.toBe(first)
    await invoke('agent-native:send', trusted(w), second, { type: 'ping', tag: 'B' })
    expect(w.sent.map(entry => entry.payload).filter(payload => payload.frame)).toEqual([{ instanceId: second, frame: { pong: 'B' } }])
  })
})

describe('same-instance loopback handoff shape (zero host change evidence)', () => {
  it('a main-process adapter reads the token file and answers only whitelisted protocol frames', async () => {
    await writeFile(path.join(extensionRoot, 'token.txt'), 'fixture-secret-do-not-leak', 'utf8')
    await fixtureAdapter(`import { readFile } from 'node:fs/promises'
      const token = () => readFile(new URL('./token.txt', import.meta.url), 'utf8')
      export default () => ({
        open: async () => ({
          send: async frame => {
            if (frame?.type === 'handshake') return { endpoint: 'http://127.0.0.1:4477', instanceKey: 'srv-fixture-1', authenticated: (await token()).length > 0 }
            throw Error('Unknown protocol frame')
          },
          close: async () => {},
        }),
      })`)
    const w = await install()
    const instanceId = await invoke('agent-native:open', trusted(w), 'fixture.server') as string
    const ok = await invoke('agent-native:send', trusted(w), instanceId, { type: 'handshake' })
    expect(JSON.stringify(ok)).toBe('{"endpoint":"http://127.0.0.1:4477","instanceKey":"srv-fixture-1","authenticated":true}')
    await expect(invoke('agent-native:send', trusted(w), instanceId, { type: 'config:dump' })).rejects.toThrow('Unknown protocol frame')
    await expect(invoke('agent-native:send', trusted(w), instanceId, { type: 'token:raw' })).rejects.toThrow('Unknown protocol frame')
  })
})
