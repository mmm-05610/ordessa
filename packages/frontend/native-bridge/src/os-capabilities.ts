/**
 * F4 host-interaction OS capabilities (T009-08; platform-services.md §宿主交互).
 *
 * The renderer-facing handles below never carry secrets and never grant
 * access: choosing a path is a USER SELECTION, not a read/write right, and a
 * late result for a revoked scope writes nothing (the caller re-checks its
 * scope before touching business state). Cancel is always zero-write.
 *
 * Absence is honest: a Web runtime declares `unavailable` — it never fakes a
 * choice and never falls back to `window.confirm`.
 */
import { ipcMain, type BrowserWindow } from 'electron'

export interface OsCapabilities {
  readonly availability: {
    chooseFile: 'available' | 'unavailable'
    chooseDirectory: 'available' | 'unavailable'
    clipboardWrite: 'available' | 'unavailable'
    openExternal: 'available' | 'unavailable'
  }
  /** User selection; `null` = cancelled. A selection grants NO access right. */
  chooseFile(options?: { title?: string; filters?: Array<{ name: string; extensions: string[] }> }): Promise<string | null>
  chooseDirectory(options?: { title?: string }): Promise<string | null>
  clipboardWrite(text: string): Promise<'written' | 'unavailable'>
  openExternal(url: string): Promise<'opened' | 'unavailable'>
}

export const OS_CAPABILITY_CHANNELS = {
  chooseFile: 'os-capability:choose-file',
  chooseDirectory: 'os-capability:choose-directory',
  clipboardWrite: 'os-capability:clipboard-write',
  openExternal: 'os-capability:open-external',
} as const

/** Main-process installation: dialog/clipboard/shell behind IPC handles. */
export function installOsCapabilities(win: BrowserWindow): () => void {
  const { dialog, clipboard, shell } = require('electron') as typeof import('electron')
  const alive = (sender: unknown): boolean => sender === win.webContents
  const handle = (
    channel: string,
    run: (payload: unknown) => Promise<unknown>,
  ) => {
    ipcMain.handle(channel, async (event, payload) => {
      if (!alive(event.sender)) return { status: 'revoked' }
      try {
        return await run(payload)
      } catch {
        return { status: 'failed' }
      }
    })
    return () => ipcMain.removeHandler(channel)
  }
  const removals = [
    handle(OS_CAPABILITY_CHANNELS.chooseFile, async payload => {
      const options = (payload ?? {}) as { title?: string; filters?: Array<{ name: string; extensions: string[] }> }
      const result = await dialog.showOpenDialog(win, {
        title: options.title, filters: options.filters, properties: ['openFile'],
      })
      return result.canceled ? { status: 'cancelled' } : { status: 'selected', path: result.filePaths[0] }
    }),
    handle(OS_CAPABILITY_CHANNELS.chooseDirectory, async payload => {
      const options = (payload ?? {}) as { title?: string }
      const result = await dialog.showOpenDialog(win, {
        title: options.title, properties: ['openDirectory'],
      })
      return result.canceled ? { status: 'cancelled' } : { status: 'selected', path: result.filePaths[0] }
    }),
    handle(OS_CAPABILITY_CHANNELS.clipboardWrite, async payload => {
      const text = typeof payload === 'string' ? payload : ''
      clipboard.writeText(text)
      return { status: 'written' }
    }),
    handle(OS_CAPABILITY_CHANNELS.openExternal, async payload => {
      const url = typeof payload === 'string' ? payload : ''
      if (!/^https?:/i.test(url)) return { status: 'refused' }
      await shell.openExternal(url)
      return { status: 'opened' }
    }),
  ]
  return () => { for (const remove of removals) remove() }
}

/** Renderer face over the IPC channels; the preload exposes exactly this. */
export function createOsCapabilities(invoke: (channel: string, payload?: unknown) => Promise<unknown>): OsCapabilities {
  const status = async (channel: string, payload?: unknown): Promise<string> => {
    const result = await invoke(channel, payload)
    return result && typeof result === 'object' && 'status' in result
      ? String((result as { status: string }).status) : 'failed'
  }
  return {
    availability: {
      chooseFile: 'available', chooseDirectory: 'available',
      clipboardWrite: 'available', openExternal: 'available',
    },
    async chooseFile(options) {
      const result = await invoke(OS_CAPABILITY_CHANNELS.chooseFile, options) as { status: string; path?: string }
      return result.status === 'selected' && typeof result.path === 'string' ? result.path : null
    },
    async chooseDirectory(options) {
      const result = await invoke(OS_CAPABILITY_CHANNELS.chooseDirectory, options) as { status: string; path?: string }
      return result.status === 'selected' && typeof result.path === 'string' ? result.path : null
    },
    async clipboardWrite(text) {
      return (await status(OS_CAPABILITY_CHANNELS.clipboardWrite, text)) === 'written' ? 'written' : 'unavailable'
    },
    async openExternal(url) {
      return (await status(OS_CAPABILITY_CHANNELS.openExternal, url)) === 'opened' ? 'opened' : 'unavailable'
    },
  }
}

/** Web / absent-adapter face: typed unavailability, never a fake choice. */
export function createAbsentOsCapabilities(): OsCapabilities {
  return {
    availability: {
      chooseFile: 'unavailable', chooseDirectory: 'unavailable',
      clipboardWrite: 'unavailable', openExternal: 'unavailable',
    },
    async chooseFile() { return null },
    async chooseDirectory() { return null },
    async clipboardWrite() { return 'unavailable' },
    async openExternal() { return 'unavailable' },
  }
}
