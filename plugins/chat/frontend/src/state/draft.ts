// Draft composition state for one Chat pane (input-contracts §2). The draft
// owns: controlled text, input items with their attachment lifecycle phases,
// and a revision that bumps on every user-visible mutation. Backend authority
// (sessions, runs, channels) stays with the facade — this is UI state only.
//
// Object URL ownership (input-spec A05): preview URLs are created for image
// items and revoked when the item is removed or the store is disposed — but
// NEVER for items whose ids were handed to an accepted submission (the sent
// record may still reference them). Unknown submission results also keep
// everything alive: nothing may be reclaimed while the backend outcome is
// unproven.
import type { ChatInputItem, ChatInputItemKind } from '@extensions/ordessa.chat-api/contract.js'

export interface DraftComposition {
  text: string
  items: readonly ChatInputItem[]
  revision: number
}

const EMPTY_COMPOSITION: DraftComposition = { text: '', items: [], revision: 0 }

export class DraftStore {
  private readonly panes = new Map<string, DraftComposition>()
  private readonly objectUrls = new Map<string, string>() // itemId → URL (revocable)
  private readonly handedOff = new Set<string>()
  private readonly listeners = new Set<() => void>()

  read = (pane: string): DraftComposition => this.panes.get(pane) ?? EMPTY_COMPOSITION

  /** Identity-stable snapshot for useSyncExternalStore: writes produce a new
   * composition object, so React re-renders exactly on real mutations. */
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }
  private changed(): void {
    for (const listener of [...this.listeners]) listener()
  }

  write(pane: string, next: DraftComposition): void {
    this.panes.set(pane, next)
    this.changed()
  }

  addItem(pane: string, item: ChatInputItem): void {
    const current = this.read(pane)
    if (current.items.some(existing => existing.id === item.id)) return
    if (item.kind === 'image' && item.previewUrl) this.objectUrls.set(item.id, item.previewUrl)
    this.write(pane, { ...current, items: [...current.items, item], revision: current.revision + 1 })
  }

  updateItem(pane: string, itemId: string, patch: Partial<ChatInputItem>): void {
    const current = this.read(pane)
    if (!current.items.some(item => item.id === itemId)) return
    this.write(pane, {
      ...current,
      items: current.items.map(item => (item.id === itemId ? { ...item, ...patch } : item)),
      revision: current.revision + 1,
    })
  }

  removeItem(pane: string, itemId: string): void {
    const current = this.read(pane)
    if (!current.items.some(item => item.id === itemId)) return
    this.reclaimItem(itemId)
    this.write(pane, { ...current, items: current.items.filter(item => item.id !== itemId), revision: current.revision + 1 })
  }

  /** Accepted submission: the referenced items' ownership moves to the sent
   * record — their object URLs survive draft teardown. */
  markHandedOff(pane: string, itemIds: readonly string[]): void {
    for (const id of itemIds) {
      this.handedOff.add(id)
      this.objectUrls.delete(id) // ownership moved; the store no longer revokes these
    }
    void pane
  }

  setText(pane: string, text: string): void {
    const current = this.read(pane)
    if (current.text === text) return
    this.write(pane, { ...current, text, revision: current.revision + 1 })
  }

  private reclaimItem(itemId: string): void {
    const url = this.objectUrls.get(itemId)
    if (url !== undefined && !this.handedOff.has(itemId)) {
      URL.revokeObjectURL(url)
      this.objectUrls.delete(itemId)
    }
  }

  disposePane(pane: string): void {
    // Discarding a draft reclaims what the store still owns; handed-off items
    // are explicitly excluded by reclaimItem.
    for (const item of this.read(pane).items) this.reclaimItem(item.id)
    this.panes.delete(pane)
  }

  dispose(): void {
    for (const pane of [...this.panes.keys()]) this.disposePane(pane)
  }

  itemCountByKind(pane: string, kind: ChatInputItemKind): number {
    return this.read(pane).items.filter(item => item.kind === kind).length
  }

  /** Prepared attachments the store still owns in this pane — ready and never
   * handed to a sent record. The discard path releases exactly these through
   * the owning service before tearing the pane down (input-spec A05). */
  releaseCandidates(pane: string): readonly ChatInputItem[] {
    return this.read(pane).items.filter(item => item.phase.state === 'ready' && !this.handedOff.has(item.id))
  }
}

/** Send gate (input-spec A04): every attachment must be `ready`; one failed,
 * undecidable or still-preparing item blocks the send and names the reason. */
export function attachmentBlockReason(items: readonly ChatInputItem[]): string | null {
  const failed = items.find(item => item.phase.state === 'failed')
  if (failed) return `附件「${failed.displayName}」未就绪：${failed.phase.state === 'failed' ? failed.phase.reason : ''}`
  const unknown = items.find(item => item.phase.state === 'unknown')
  if (unknown) return `附件「${unknown.displayName}」准备结果未知，已保留；核实后可重试。`
  const preparing = items.find(item => item.phase.state === 'preparing' || item.phase.state === 'selected')
  if (preparing) return `附件「${preparing.displayName}」仍在准备中`
  return null
}
