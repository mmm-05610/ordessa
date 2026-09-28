// Expansion state for one conversation view, replacing the upstream module-
// level `toolLayoutOpenState` Map (ZCode ToolLayout.tsx @ 29628c9a keeps a
// process-wide Map that only grows — research-plan flags it as the thing this
// port must NOT copy). Keys are `${conversationKey}\u0000${toolId}`; the store
// is owned by the mounted conversation view and discarded with it, so the same
// tool name in two sessions never shares state and nothing accumulates across
// unmount/remount cycles.
import { useMemo, useSyncExternalStore } from 'react'

export class ViewExpansionState {
  private readonly open = new Map<string, boolean>()
  private readonly listeners = new Set<() => void>()
  private snapshot = ''

  isDisposed = false
  isOpen(key: string): boolean { return this.open.get(key) ?? false }
  setOpen(key: string, value: boolean): void {
    if (this.isDisposed) return
    if (this.open.get(key) === value) return
    this.open.set(key, value)
    this.snapshot = [...this.open.entries()].map(([k, v]) => `${k}=${v ? 1 : 0}`).join('|')
    for (const listener of [...this.listeners]) listener()
  }
  getSnapshot = (): string => this.snapshot
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }
  dispose(): void {
    this.isDisposed = true
    this.open.clear()
    this.listeners.clear()
  }
}

/** Hook used by the conversation view that owns the store. */
export function useViewState(): ViewExpansionState {
  return useMemo(() => new ViewExpansionState(), [])
}

export function useExpansion(expansion: ViewExpansionState, key: string): [boolean, (open: boolean) => void] {
  const snapshot = useSyncExternalStore(expansion.subscribe, expansion.getSnapshot, expansion.getSnapshot)
  // snapshot only forces re-render; the value is read directly.
  void snapshot
  return [expansion.isOpen(key), open => expansion.setOpen(key, open)]
}
