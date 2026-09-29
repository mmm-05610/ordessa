/**
 * 宿主生命周期内核（PA-07…PA-10）。这里**不** import electron：所有平台能力都注入，
 * 因此单实例、退出清理、窗口状态记忆、崩溃恢复四条都能在 vitest 里用假平台真跑。
 * 契约依据：FR-025 / FR-026 / FR-027 / FR-028、C-02 §5（清理异常不覆盖主因）。
 */

/** 单一清理顺序的退出账本：先停外部进程，再释放锁，最后落盘。 */
export interface QuitStep { readonly name: string; run(): void | Promise<void> }

export interface CleanupOutcome {
  /** 每一步的结果；失败项进 errors，绝不吞掉主因。 */
  readonly errors: { readonly step: string; readonly error: string }[]
  /** 清理整体是否成功（任一步失败即 false，但仍执行完所有步骤）。 */
  readonly ok: boolean
}

/**
 * PA-08 统一清理：**所有**步骤都跑完，失败被收集而不是短路；
 * 调用方把 `errors` 与主因一起报出去（constitution 2）。
 */
export async function runCleanup(steps: readonly QuitStep[]): Promise<CleanupOutcome> {
  const errors: { step: string; error: string }[] = []
  for (const step of steps) {
    try { await step.run() } catch (error) { errors.push({ step: step.name, error: String(error) }) }
  }
  return { errors, ok: errors.length === 0 }
}

/**
 * PA-07 单实例 + 数据根锁：两者是同一把锁的两个来源。
 * 锁文件里记 pid 与起始时间；`isLive` 由注入的探测函数决定（测试用假探测）。
 */
export interface DataRootLockState { readonly pid: number; readonly since: string; readonly host: string }

export function lockHeld(state: DataRootLockState, isLive: (pid: number) => boolean): boolean {
  return isLive(state.pid)
}

/** PA-09 窗口状态记忆：几何在当前显示器上不可用时退化为默认值，而不是把窗口丢到屏幕外。 */
export interface WindowState { readonly x: number; readonly y: number; readonly width: number; readonly height: number; readonly maximized: boolean }
export const DEFAULT_WINDOW_STATE: WindowState = { x: -1, y: -1, width: 1220, height: 800, maximized: false }
export interface Display { readonly bounds: { x: number; y: number; width: number; height: number } }

export function restoreWindowState(saved: unknown, displays: readonly Display[]): WindowState {
  if (!saved || typeof saved !== 'object') return DEFAULT_WINDOW_STATE
  const candidate = saved as Partial<WindowState>
  const { width, height, maximized } = candidate
  const valid = typeof width === 'number' && typeof height === 'number' && width >= 760 && height >= 520 &&
    displays.some(d => d.bounds.width >= width && d.bounds.height >= height)
  if (!valid) return DEFAULT_WINDOW_STATE
  const onSomeDisplay = displays.some(d => {
    const b = d.bounds
    return candidate.x === undefined || candidate.y === undefined ||
      (candidate.x < b.x + b.width - 80 && candidate.x + (width ?? 0) > b.x + 80 &&
       candidate.y < b.y + b.height - 40 && candidate.y + (height ?? 0) > b.y + 80)
  })
  // 显示器配置变化（拔掉扩展屏）时位置失效：保留尺寸、退回默认位置。
  return onSomeDisplay
    ? { x: candidate.x!, y: candidate.y!, width: width!, height: height!, maximized: maximized === true }
    : { x: -1, y: -1, width: width!, height: height!, maximized: maximized === true }
}

/** PA-10 崩溃恢复：启动时若上次没有干净退出，就留下可读的事实（而不是静默重来）。 */
export interface CrashMarker { readonly startedAt: string; readonly pid: number; readonly clean: boolean }

export function startupCrashReport(marker: CrashMarker | null, now: Date): { recovered: boolean; detail: string } {
  if (!marker) return { recovered: false, detail: 'no previous session recorded' }
  if (marker.clean) return { recovered: false, detail: 'previous session exited cleanly' }
  const age = Math.max(0, now.getTime() - Date.parse(marker.startedAt))
  return { recovered: true, detail: `previous session (pid ${marker.pid}) ended without a clean exit, ${Math.round(age / 1000)}s ago` }
}

export function beginSession(now: Date, pid: number): CrashMarker { return { startedAt: now.toISOString(), pid, clean: false } }
export function cleanSession(marker: CrashMarker): CrashMarker { return { ...marker, clean: true } }
