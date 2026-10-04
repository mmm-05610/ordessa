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
import type { f5 } from '@extensions/ordessa.contracts/contract.js'
import { createEditSession } from '@ordessa/ui-components/editing'

type DraftEditValue = { composition: DraftComposition }
type DraftEditSession = f5.EditSession<DraftEditValue>
type DraftEditOutcome = f5.EditOutcome

interface PaneEditState {
  session: DraftEditSession
  resolvePending?: (outcome: DraftEditOutcome) => void
}

export interface DraftSendCapture {
  readonly composition: DraftComposition
  readonly editId: string
  readonly baseRevision: string
  settle(outcome: 'accepted' | 'refused' | 'unknown'): Promise<void>
}

let editSessionSeq = 0

export interface DraftComposition {
  text: string
  items: readonly ChatInputItem[]
  revision: number
}

const EMPTY_COMPOSITION: DraftComposition = { text: '', items: [], revision: 0 }

/** The single-editor lease of one pane (T010-07): at most one editor may edit
 * a draft composition at a time. Captured submission settlement has its own
 * lease-independent path and remains bound to the captured revision. */
export interface DraftEditorLease {
  readonly editorId: string
  readonly pane: string
  release(): void
}

export class DraftStore {
  private readonly panes = new Map<string, DraftComposition>()
  private readonly editSessions = new Map<string, PaneEditState>()
  private readonly pendingCaptures = new Set<string>()
  private readonly editors = new Map<string, string>() // pane → editorId (lease)
  private readonly objectUrls = new Map<string, string>() // itemId → URL (revocable)
  private readonly handedOff = new Set<string>()
  private readonly listeners = new Set<() => void>()

  read = (pane: string): DraftComposition => this.panes.get(pane) ?? EMPTY_COMPOSITION

  /** Claim the pane's editor lease (stable draftId/revision/editorLease,
   * T010-07). A second editor is refused — one writer per pane. */
  claimEditor(pane: string, editorId: string): DraftEditorLease {
    const held = this.editors.get(pane)
    if (held !== undefined && held !== editorId) throw new Error('DRAFT_EDITOR_LEASE_HELD')
    this.editors.set(pane, editorId)
    return {
      editorId, pane,
      release: () => { if (this.editors.get(pane) === editorId) this.editors.delete(pane) },
    }
  }

  private assertEditor(pane: string, editorId?: string): void {
    const held = this.editors.get(pane)
    if (held !== undefined && editorId !== held) throw new Error('DRAFT_EDITOR_LEASE_HELD')
  }

  /** Whether this pane still has a live composition (a disposed pane is never
   * resurrected by a late settle). */
  has = (pane: string): boolean => this.panes.has(pane)

  /** Identity-stable snapshot for useSyncExternalStore: user mutations update
   * the owner snapshot and its F5 edit session together. */
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }
  private changed(): void {
    for (const listener of [...this.listeners]) listener()
  }

  private editState(pane: string): PaneEditState {
    let state = this.editSessions.get(pane)
    if (state !== undefined) return state
    const initial = this.read(pane)
    state = {
      session: undefined as unknown as DraftEditSession,
    }
    state.session = createEditSession<DraftEditValue>({
      editId: `chat-draft:${pane}:${++editSessionSeq}`,
      baseRevision: String(initial.revision),
      initial: { composition: initial },
      commitHandler: async () => new Promise<DraftEditOutcome>(resolve => {
        state!.resolvePending = resolve
      }),
    })
    this.editSessions.set(pane, state)
    return state
  }

  /** Capture the current composition with F5 edit revision semantics. The
   * later settle is bound to this capture and remains valid after its editor
   * lease is released or its view unmounts. */
  captureForSend(pane: string, submissionId: string): DraftSendCapture {
    if (this.pendingCaptures.has(pane)) throw new Error('DRAFT_SEND_CAPTURE_PENDING')
    const composition = this.read(pane)
    const state = this.editState(pane)
    this.pendingCaptures.add(pane)
    const commit = state.session.commit()
    let settled = false
    return {
      composition,
      editId: state.session.editId,
      baseRevision: state.session.baseRevision,
      settle: async outcome => {
        if (settled) return
        settled = true
        const editOutcome: DraftEditOutcome = outcome === 'accepted'
          ? { kind: 'saved', consumedFields: ['composition'] }
          : outcome === 'refused'
            ? { kind: 'rejected', reason: 'submission refused' }
            : { kind: 'unknown', queryHint: `submission:${submissionId}` }
        state.resolvePending?.(editOutcome)
        await commit
        if (this.editSessions.get(pane) === state) state.resolvePending = undefined
        this.pendingCaptures.delete(pane)

        // Preserve DraftStore ownership and its durable pane identity. The
        // session only authorizes consuming the exact captured revision.
        if (outcome === 'accepted' && this.has(pane) && this.editSessions.get(pane) === state) {
          const current = this.read(pane)
          if (current.revision === composition.revision) {
            this.panes.set(pane, { ...current, text: '', revision: current.revision + 1 })
            this.editSessions.delete(pane)
            this.changed()
          }
        }
      },
    }
  }

  /** Owner mutation primitive used by composer edits and input insertion. */
  write(pane: string, next: DraftComposition): void {
    this.panes.set(pane, next)
    // DraftStore remains the owner; its user-visible mutation is mirrored into
    // the public F5 edit session so a captured settle observes every edit event.
    this.editState(pane).session.setValue('composition', next)
    this.changed()
  }

  addItem(pane: string, item: ChatInputItem, editorId?: string): void {
    this.assertEditor(pane, editorId)
    const current = this.read(pane)
    if (current.items.some(existing => existing.id === item.id)) return
    if (item.kind === 'image' && item.previewUrl) this.objectUrls.set(item.id, item.previewUrl)
    this.write(pane, { ...current, items: [...current.items, item], revision: current.revision + 1 })
  }

  updateItem(pane: string, itemId: string, patch: Partial<ChatInputItem>, editorId?: string): void {
    this.assertEditor(pane, editorId)
    const current = this.read(pane)
    if (!current.items.some(item => item.id === itemId)) return
    this.write(pane, {
      ...current,
      items: current.items.map(item => (item.id === itemId ? { ...item, ...patch } : item)),
      revision: current.revision + 1,
    })
  }

  removeItem(pane: string, itemId: string, editorId?: string): void {
    this.assertEditor(pane, editorId)
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

  setText(pane: string, text: string, editorId?: string): void {
    this.assertEditor(pane, editorId)
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
    this.editSessions.delete(pane)
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
