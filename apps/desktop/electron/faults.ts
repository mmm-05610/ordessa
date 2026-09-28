/**
 * 故障 UI 的事实构造（PA-12，C-06 §C）：每条故障都是
 * `kind + reason（人话）+ remedy（可执行下一步）+ logRef`，绝不留空白窗口。
 * 这里只产数据；渲染在 `renderer/desktop-ui.tsx`。
 */
import type { Fault, FaultKind } from '@extensions/ordessa.contracts/contract.js'

export const FAULT_TITLES: Readonly<Record<FaultKind, string>> = {
  'data-root-missing': '数据目录不可用',
  'port-conflict': '无法启动 Ordessa Server',
  'runtime-missing': '无法启动 Ordessa Server',
  'data-root-locked': '数据目录已被占用',
  'update-source-unreachable': '检查更新失败',
  'server-launch-failed': '无法启动 Ordessa Server',
}

export function faultTitle(fault: Fault): string { return FAULT_TITLES[fault.kind] }

/** 故障的稳定标识（用于测试与日志关联，不含路径与令牌）。 */
export function faultId(fault: Fault): string { return fault.code ?? fault.kind }

/** 一次会话可有多条故障；顺序固定（先数据根，再运行时，再更新），保证 UI 可复现。 */
export function sortFaults(faults: readonly Fault[]): readonly Fault[] {
  const order: FaultKind[] = ['data-root-missing', 'data-root-locked', 'runtime-missing', 'port-conflict',
    'server-launch-failed', 'update-source-unreachable']
  return [...faults].sort((a, b) => order.indexOf(a.kind) - order.indexOf(b.kind))
}

/** 故障必须字段齐全：缺 reason/remedy/logRef 的故障不允许进入 UI。 */
export function isRenderableFault(value: unknown): value is Fault {
  const fault = value as Partial<Fault> | null
  return !!fault && typeof fault.kind === 'string' && typeof fault.reason === 'string' && fault.reason.length > 0 &&
    typeof fault.remedy === 'string' && fault.remedy.length > 0 && typeof fault.logRef === 'string' && fault.logRef.length > 0
}
