import { contextBridge, ipcRenderer } from 'electron'
contextBridge.exposeInMainWorld('extensionCatalog', {
  read: () => ipcRenderer.invoke('extensions:catalog'),
})
contextBridge.exposeInMainWorld('projectDirectory', {
  choose: (): Promise<string | undefined> => ipcRenderer.invoke('projects:choose-directory'),
})
// Frameless window chrome exists only on Windows/Linux; macOS keeps the native title bar.
if (process.platform !== 'darwin') contextBridge.exposeInMainWorld('desktopWindow', {
  minimize: () => ipcRenderer.invoke('window:minimize'),
  toggleMaximize: () => ipcRenderer.invoke('window:toggle-maximize'),
  close: () => ipcRenderer.invoke('window:close'),
  isMaximized: (): Promise<boolean> => ipcRenderer.invoke('window:is-maximized'),
  onChromeState: (listener: (maximized: boolean) => void) => {
    const handler = (_event: Electron.IpcRendererEvent, maximized: boolean) => listener(maximized)
    ipcRenderer.on('window:chrome-state', handler)
    return () => ipcRenderer.off('window:chrome-state', handler)
  },
})
contextBridge.exposeInMainWorld('agentNative', {
  open: (adapterId: string) => ipcRenderer.invoke('agent-native:open', adapterId),
  send: (instanceId: string, frame: unknown) => ipcRenderer.invoke('agent-native:send', instanceId, frame),
  close: (instanceId: string) => ipcRenderer.invoke('agent-native:close', instanceId),
  subscribe: (listener: (event: { instanceId: string; frame?: unknown; error?: string }) => void) => {
    const handler = (_event: Electron.IpcRendererEvent, payload: { instanceId: string; frame?: unknown; error?: string }) => listener(payload)
    ipcRenderer.on('agent-native:event', handler)
    return () => ipcRenderer.off('agent-native:event', handler)
  },
})

// --- 013 宿主桥（PA-12/13/15/21/22）---------------------------------------
// 全部经 contextBridge 暴露；**没有**任何令牌、令牌路径或 Server origin 出现在这里，
// 渲染进程拿到的只是类型化三态（C-03 §4 的硬门）。
contextBridge.exposeInMainWorld('desktopHost', {
  about: (): Promise<unknown> => ipcRenderer.invoke('desktop:about'),
  openLicense: (): Promise<boolean> => ipcRenderer.invoke('desktop:open-license'),
  faults: (): Promise<unknown[]> => ipcRenderer.invoke('desktop:faults'),
  dataRoot: (): Promise<{ dataRoot: string; logsDir: string }> => ipcRenderer.invoke('desktop:data-root'),
  openLogs: (): Promise<boolean> => ipcRenderer.invoke('desktop:open-directory'),
  readSetting: (id: string): Promise<unknown> => ipcRenderer.invoke('settings:read', id),
  writeSetting: (id: string, value: unknown): Promise<unknown> => ipcRenderer.invoke('settings:write', id, value),
  settingFragments: (known: string[]): Promise<unknown[]> => ipcRenderer.invoke('settings:fragments', known),
  setLogLevel: (level: string): Promise<string> => ipcRenderer.invoke('settings:log-level', level),
  logHealth: (): Promise<{ dropped: number; writable: boolean }> => ipcRenderer.invoke('settings:log-health'),
  exportDiagnostics: (): Promise<unknown> => ipcRenderer.invoke('diagnostics:export'),
  wireCall: (method: string, params: Record<string, unknown>): Promise<unknown> => ipcRenderer.invoke('wire:call', method, params),
  wireReady: (): Promise<boolean> => ipcRenderer.invoke('wire:ready'),
  wireScope: (): Promise<string | null> => ipcRenderer.invoke('wire:scope'),
  updateState: (): Promise<unknown> => ipcRenderer.invoke('update:state'),
  checkUpdate: (): Promise<unknown> => ipcRenderer.invoke('update:check'),
  downloadUpdate: (): Promise<unknown> => ipcRenderer.invoke('update:download'),
  applyUpdate: (): Promise<unknown> => ipcRenderer.invoke('update:apply'),
})
