import { randomUUID } from 'node:crypto'
import { pathToFileURL } from 'node:url'
import type { BrowserWindow } from 'electron'
import { ipcMain } from 'electron'
import { confinedFile, type Discovery } from '@ordessa/extension-host/main'

export interface NativeConnection {
  send(frame: unknown): Promise<unknown>
  close(): Promise<void>
}
export interface NativeTransport {
  open(onFrame: (frame: unknown) => void): Promise<NativeConnection>
}

/** Only enabled extensions with a confined native entry can provide a transport. */
export function installNativeBridge(win: BrowserWindow, discovery: Discovery) {
  const live = new Map<string, { adapterId: string; connection: NativeConnection }>()
  let disposed = false
  const trusted = (event: Electron.IpcMainInvokeEvent) => {
    if (disposed || event.sender !== win.webContents || event.senderFrame !== win.webContents.mainFrame ||
        event.senderFrame.url !== 'ordessa://desktop/index.html') throw Error('Untrusted native transport caller')
  }
  const validateFrame = (frame: unknown) => {
    const serialized = JSON.stringify(frame)
    if (typeof serialized !== 'string' || serialized.length > 1024 * 1024) throw Error('Invalid native transport frame')
  }
  const open = async (event: Electron.IpcMainInvokeEvent, adapterId: string) => {
    trusted(event)
    if (typeof adapterId !== 'string') throw Error('Invalid adapter')
    const installed = discovery.installed.get(adapterId)
    if (!installed?.manifest.native) throw Error('Native adapter unavailable')
    const filename = await confinedFile(installed.root, installed.manifest.native)
    const module = await import(pathToFileURL(filename).href) as { default?: () => NativeTransport }
    if (typeof module.default !== 'function') throw Error('Invalid native adapter entry')
    const transport = module.default()
    if (!transport || typeof transport.open !== 'function') throw Error('Invalid native transport')
    const instanceId = randomUUID()
    const early: unknown[] = []
    const deliver = (frame: unknown) => {
      if (disposed || win.isDestroyed()) return
      try {
        validateFrame(frame)
        if (!live.has(instanceId)) {
          if (early.length >= 256) throw Error('Native transport startup buffer exceeded')
          early.push(frame)
          return
        }
        win.webContents.send('agent-native:event', { instanceId, frame })
      } catch { win.webContents.send('agent-native:event', { instanceId, error: 'Invalid native transport frame' }) }
    }
    const connection = await transport.open(deliver)
    if (disposed) { await connection.close(); throw Error('Native bridge closed') }
    live.set(instanceId, { adapterId, connection })
    for (const frame of early) deliver(frame)
    return instanceId
  }
  const send = async (event: Electron.IpcMainInvokeEvent, instanceId: string, frame: unknown) => {
    trusted(event)
    validateFrame(frame)
    const item = live.get(instanceId)
    if (!item) throw Error('Native instance unavailable')
    const result = await item.connection.send(frame)
    if (result !== undefined) validateFrame(result)
    return result
  }
  const close = async (event: Electron.IpcMainInvokeEvent, instanceId: string) => {
    trusted(event)
    const item = live.get(instanceId)
    if (!item) return
    live.delete(instanceId)
    await item.connection.close()
  }
  ipcMain.handle('agent-native:open', open)
  ipcMain.handle('agent-native:send', send)
  ipcMain.handle('agent-native:close', close)
  const dispose = async () => {
    if (disposed) return
    disposed = true
    ipcMain.removeHandler('agent-native:open')
    ipcMain.removeHandler('agent-native:send')
    ipcMain.removeHandler('agent-native:close')
    const pending = [...live.values()]
    live.clear()
    await Promise.allSettled(pending.map(item => item.connection.close()))
  }
  win.once('closed', () => { void dispose() })
  return { dispose }
}
