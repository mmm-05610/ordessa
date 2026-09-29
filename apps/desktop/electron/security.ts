/**
 * 安全基线（PA-23 / FR-033）。这些字面量是**回归门**：集中在这里，主进程只引用它，
 * 单测直接断言它们不被放宽，而不是"看一眼觉得没问题"。
 */
export const APP_ORIGIN = 'ordessa://desktop/index.html'

/** 渲染进程安全基线：沙箱开、上下文隔离开、Node 集成关。 */
export const SECURE_WEB_PREFERENCES = Object.freeze({
  contextIsolation: true,
  nodeIntegration: false,
  sandbox: true,
})

export interface CallerFacts {
  /** 事件发送方是否就是主窗口的 webContents。 */
  sameSender: boolean
  /** 是否来自主 frame。 */
  mainFrame: boolean
  /** 该 frame 的 URL。 */
  url: string
  /** 窗口已销毁时为 true（此时一律拒绝）。 */
  windowDestroyed: boolean
}

/** IPC 调用方校验：任一条不满足即拒绝（含跨窗口 / 子 frame / 其它协议来源）。 */
export function isTrustedIpcCaller(facts: CallerFacts): boolean {
  return !facts.windowDestroyed && facts.sameSender && facts.mainFrame && facts.url === APP_ORIGIN
}

/** 权限请求一律拒绝（C-04 之外的第二道门）。 */
export const DENY_ALL_PERMISSIONS = true

/** 新窗口一律拒绝。 */
export const WINDOW_OPEN_ACTION = 'deny' as const
