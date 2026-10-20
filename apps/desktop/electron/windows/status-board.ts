import { BrowserWindow, ipcMain, screen } from 'electron'
import { SECURE_WEB_PREFERENCES, isTrustedIpcCaller } from '../security'
export function createStatusBoardWindow(preload: string, show: boolean): BrowserWindow {
  const area = screen.getPrimaryDisplay().workArea
  const win = new BrowserWindow({ width: 390, height: Math.min(760, area.height), minWidth: 360, maxWidth: 420, minHeight: 60, x: area.x + area.width - 406, y: area.y + 16, frame: false, show, resizable: true, maximizable: false, fullscreenable: false, webPreferences: { preload, ...SECURE_WEB_PREFERENCES } })
  let previousHeight = win.getBounds().height, collapsed = false
  const trust = (event: Electron.IpcMainInvokeEvent) => {
    if (!isTrustedIpcCaller({ windowDestroyed: win.isDestroyed(), sameSender: event.sender === win.webContents, mainFrame: event.senderFrame === win.webContents.mainFrame, url: event.senderFrame?.url ?? '' })) throw Error('Untrusted status-board caller')
  }
  ipcMain.handle('status-board:collapse', (event, value: unknown) => {
    trust(event); if (typeof value !== 'boolean') throw Error('Invalid collapse value')
    if (value === collapsed) return
    if (value) { previousHeight = win.getBounds().height; win.setMinimumSize(360, 60); win.setSize(win.getBounds().width, 60); win.setResizable(false) }
    else { win.setResizable(true); win.setMinimumSize(360, 360); win.setSize(win.getBounds().width, previousHeight) }
    collapsed = value
  })
  ipcMain.handle('status-board:pin', (event, value: unknown) => { trust(event); if (typeof value !== 'boolean') throw Error('Invalid pin value'); win.setAlwaysOnTop(value) })
  win.once('closed', () => { ipcMain.removeHandler('status-board:collapse'); ipcMain.removeHandler('status-board:pin') })
  win.setMinimumSize(360, 360)
  return win
}
