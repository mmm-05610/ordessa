/**
 * The Profile-editor Skill section model (T10 / G15).
 *
 * The two-source discipline the whole surface is built on (ux.md §Profile
 * 编辑器):
 *
 * * 本层设置 = the Profile host's stored relation for this Profile's fixed
 *   harness, overlaid by this section's unsaved draft; when the host reads
 *   `PROFILE_LAYER_UNAVAILABLE` the choice is `undetermined` — 显示为「继承
 *   未确定」, never a fake "disabled" (G06/G09 edge);
 * * 最终结果 = the SAME `EffectiveView` row `skills.resolve` produces for this
 *   Profile target (deciding scope + fixed revision), rendered through the
 *   shared `effect-text.ts` wording — a decision here never claims a load,
 *   and a projection never claims a decision.
 *
 * Consequences the G15 counter-examples name:
 *
 * * 选择即修改内容实体 — editing a tri-state button calls no gateway method
 *   at all; drafts land on the host only through an explicit save;
 * * 取消删除已导入资产 — `cancelEditing` asks the host to drop relationship
 *   state; the imported content rows stay in the library and the gateway has
 *   no content-deletion method to reach for;
 * * 旧贡献残留 UI — unmounting the section writes nothing; stored relations
 *   survive and a re-mount reads them back (this model is the mount unit).
 */
import type {
  ProfileDraftState, ProfileDraftWriteResult, ProfileHost, ProfileImportPreview, ProfileLayerChoice,
  ProfileLibraryRow, ProfileRevisionOption, ProfileSkillsGateway, ProfileSkillRelation, ProfileSkillRow,
} from '../../contracts/src/profile'
import type { Decision, EffectiveView, RevisionDiff } from '../../contracts/src/skills'
import { isProfileLayerUnavailable } from '../../contracts/src/profile'
import { sha256Hex } from './sha256'

export type ProfileImportPhase =
  | { kind: 'idle' }
  | { kind: 'transferring'; importId: string; sent: number; total: number }
  | { kind: 'prepared'; importId: string; preview: ProfileImportPreview }
  | { kind: 'committed'; assetId: string; revision: number }
  | { kind: 'failed'; message: string }

export interface ProfileDraftEdit { decision: Decision; revision: number | null }

export interface ProfileSkillsSnapshot {
  state: 'loading' | 'ready' | 'error'
  error: string | null
  /** How the profile *layer* reads (host side). */
  layerStatus: 'loading' | 'ready' | 'unavailable'
  /** How the *effective view* reads (gateway side); both may be unavailable
   * independently and each is said separately. */
  effectiveStatus: 'loading' | 'ready' | 'unavailable' | 'error'
  profile: ProfileDraftState | null
  library: readonly ProfileLibraryRow[]
  effective: EffectiveView | null
  rows: readonly ProfileSkillRow[]
  /** Per-asset unsaved edits, keyed by assetId. */
  draft: Record<string, ProfileDraftEdit>
  /** Per-asset imported-for-this-Profile badges that are not yet saved as a
   * relation (survives draft discard and host cancel — content is published). */
  importedHere: readonly string[]
  /** The open 更新版本 panel, if any. */
  switcher: { assetId: string; revisions: readonly ProfileRevisionOption[] | null } | null
  /** FR07 批准证明缺口 (second-round review, MINOR-6): a repoint draft may
   * only be produced for a target whose approval state was READ from the
   * loaded version list. When `confirmSwitch` cannot prove it (revisions
   * not loaded → `options === null`, or the target revision is not in the
   * loaded list), the model REFUSES and records the typed reason here —
   * the wall is in the model, not only in the button's visibility. */
  switchRefusal: {
    code: 'SWITCH_APPROVAL_UNPROVEN'
    assetId: string
    toRevision: number
    message: string
  } | null
  diffPreview: { assetId: string; fromRevision: number; toRevision: number; diff: RevisionDiff | null; error: string | null } | null
  saving: boolean
  conflict: { message: string; serverConfigRevision: number } | null
  importPhase: ProfileImportPhase
}

export interface ProfileSkillsModel {
  subscribe(listener: () => void): () => void
  getSnapshot(): ProfileSkillsSnapshot
  refresh(): Promise<void>
  /** Tri-state edit at the profile layer (draft only — nothing is sent). */
  edit(assetId: string, decision: Decision): void
  /** 移除覆写 = 恢复继承; wording is the section's, see profileSection.tsx. */
  removeOverride(assetId: string): void
  openSwitcher(assetId: string): Promise<void>
  closeSwitcher(): void
  /** Diff before switching (`skills.diff`), shown before any repoint act. */
  previewSwitch(assetId: string, toRevision: number): Promise<void>
  /** The explicit approve-and-repoint (FR07): approval on the content layer
   * plus a draft repoint, in one user act; never implicit, and refused with
   * the typed `switchRefusal` state when the target's approval cannot be
   * proven from the loaded version list (see ProfileSkillsSnapshot). */
  confirmSwitch(assetId: string, toRevision: number): Promise<void>
  save(): Promise<void>
  discard(): void
  reread(): Promise<void>
  importPicked(files: readonly { path: string; bytes: Uint8Array }[]): Promise<void>
  confirmImport(assetId: string): Promise<void>
  cancelImport(): Promise<void>
  /** Profile cancel: relationship state goes back to stored; content stays
   * imported (G15 counter-example 「取消删除已导入资产」). */
  cancelProfileEditing(): Promise<void>
}

export function createProfileSkillsModel(gateway: ProfileSkillsGateway, host: ProfileHost): ProfileSkillsModel {
  let snapshot: ProfileSkillsSnapshot = {
    state: 'loading', error: null, layerStatus: 'loading', effectiveStatus: 'loading',
    profile: null, library: [], effective: null, rows: [], draft: {}, importedHere: [],
    switcher: null, switchRefusal: null, diffPreview: null, saving: false, conflict: null, importPhase: { kind: 'idle' },
  }
  const listeners = new Set<() => void>()
  const publish = () => { for (const listener of listeners) listener() }
  const patch = (part: Partial<ProfileSkillsSnapshot>) => { snapshot = { ...snapshot, ...part }; publish() }

  const relationOf = (assetId: string): ProfileSkillRelation | null =>
    snapshot.profile?.relations.find(row => row.assetId === assetId) ?? null

  const effectiveOf = (assetId: string) =>
    snapshot.effective?.resolved.find(item => item.assetId === assetId) ?? null

  /** Choice precedence: unsaved draft → stored relation → `undetermined` when
   * the layer cannot be read → plain 继承 (the honest absence). */
  const choiceOf = (assetId: string): { choice: ProfileLayerChoice; revision: number | null } => {
    const draft = snapshot.draft[assetId]
    if (draft !== undefined) return { choice: draft.decision, revision: draft.revision }
    if (snapshot.layerStatus === 'unavailable') return { choice: 'undetermined', revision: null }
    const stored = relationOf(assetId)
    if (stored === null) return { choice: 'inherit', revision: null }
    return { choice: stored.decision, revision: stored.revision }
  }

  const rebuild = () => {
    const ids = [...new Set([
      ...snapshot.library.map(row => row.assetId),
      ...(snapshot.profile?.relations ?? []).map(row => row.assetId),
      ...snapshot.importedHere,
    ])]
    const rows: ProfileSkillRow[] = ids.map(assetId => {
      const record = snapshot.library.find(row => row.assetId === assetId) ?? null
      const resolved = effectiveOf(assetId)
      const stored = relationOf(assetId)
      const imported = stored?.importedForProfile === true || snapshot.importedHere.includes(assetId)
      const { choice, revision } = choiceOf(assetId)
      // Ownership is BADGED only from a proven source: the host's own import
      // fact, or a row the resolver actually selected (with its server-side
      // origin field). Excluded/absent rows carry no proven origin, and
      // `skills.list`'s raw view carries none either — null says 归属未证明
      // instead of guessing public.
      const proven = resolved !== null && resolved.excludedBy === null && resolved.selectedBy.layer !== 'none'
      return {
        assetId,
        nativeName: record?.nativeName ?? resolved?.nativeName ?? assetId,
        // Ownership is only ever BADGED from a proven source: the host's own
        // import fact, or the resolver's origin field. `skills.list`'s raw
        // view carries none (records.py `asset_view`), so nothing is guessed.
        originScope: imported ? 'profile' : proven ? resolved!.originScope : null,
        importedForProfile: imported,
        profileChoice: choice,
        profileRevision: revision,
        draft: snapshot.draft[assetId] ?? null,
        effective: resolved,
      }
    })
    // Stable order so the keyboard cursor is never shuffled away (same rule as
    // the settings list).
    rows.sort((a, b) => a.nativeName.localeCompare(b.nativeName) || a.assetId.localeCompare(b.assetId))
    patch({ rows })
  }

  const readOnly = () => snapshot.profile?.archived === true || snapshot.layerStatus === 'unavailable'

  /** Merge the current draft into the stored relations, without writing. */
  const drafted = (): ProfileSkillRelation[] => {
    const base = [...(snapshot.profile?.relations ?? [])]
    for (const [assetId, edit] of Object.entries(snapshot.draft)) {
      const at = base.findIndex(row => row.assetId === assetId)
      const relation: ProfileSkillRelation = {
        assetId, decision: edit.decision,
        revision: edit.decision === 'enable' ? edit.revision : null,
        importedForProfile: at >= 0 ? base[at].importedForProfile : snapshot.importedHere.includes(assetId),
      }
      if (at >= 0) base.splice(at, 1, relation)
      else base.push(relation)
    }
    for (const assetId of snapshot.importedHere) {
      if (!base.some(row => row.assetId === assetId)) {
        base.push({ assetId, decision: 'inherit', revision: null, importedForProfile: true })
      }
    }
    return base.filter(row => !(row.decision === 'inherit' && !row.importedForProfile))
  }

  const refreshEffective = async () => {
    if (snapshot.profile === null) return
    const { profileId, harnessId } = snapshot.profile
    patch({ effectiveStatus: 'loading' })
    try {
      const effective = await gateway.resolveProfile({ profileId, harnessId })
      patch({ effective, effectiveStatus: 'ready' })
    } catch (failure) {
      if (isProfileLayerUnavailable(failure)) {
        // The §G3 face of the same rule the backend port follows: refuse with
        // a type, never answer "empty set" as if it meant "nothing enabled".
        patch({ effective: null, effectiveStatus: 'unavailable' })
      } else {
        patch({ effectiveStatus: 'error', error: String(failure) })
      }
    }
  }

  const model: ProfileSkillsModel = {
    subscribe(listener) { listeners.add(listener); return () => { listeners.delete(listener) } },
    getSnapshot: () => snapshot,

    async refresh() {
      patch({ state: 'loading', error: null })
      // Content reads first: they are true even while the profile layer is
      // not (the section must still show WHICH content exists).
      try {
        patch({ library: await gateway.listSkills() })
      } catch (failure) {
        patch({ state: 'error', error: `内容库读取失败：${String(failure)}` })
      }
      try {
        const profile = await host.current()
        patch({ profile, layerStatus: 'ready', state: 'ready' })
        rebuild()
        await refreshEffective()
        rebuild()
      } catch (failure) {
        if (isProfileLayerUnavailable(failure)) {
          patch({ profile: null, layerStatus: 'unavailable', state: 'ready', effective: null, effectiveStatus: 'unavailable' })
          rebuild()
        } else {
          patch({ state: 'error', error: String(failure) })
        }
      }
    },

    edit(assetId, decision) {
      if (readOnly()) {
        // New choices are refused with a reason, not accepted into a draft
        // the user would then trust (same discipline as the settings model).
        const reason = snapshot.profile?.archived ? '已归档 Profile 只读：选择未记录' : 'Profile 层暂不可读：选择未记录'
        patch({ error: reason })
        return
      }
      if (decision === 'inherit') {
        // 恢复继承: the draft row says inherit; `drafted()` turns that into a
        // removed relation at save (minus the imported-for badge row, which
        // keeps existing to carry the origin badge).
        snapshot = { ...snapshot, draft: { ...snapshot.draft, [assetId]: { decision, revision: null } } }
        patch({})
        rebuild()
        return
      }
      if (decision === 'enable') {
        // 启用 must pin an approved revision (FR04/G06): with no pinned row
        // yet, the draft pins the highest approved revision we can see, and
        // the row invites the picker for an explicit choice.
        const stored = relationOf(assetId)
        const pinned = stored?.revision ?? highestKnownApproved(assetId)
        if (pinned === null) {
          patch({ error: '启用需要指定已批准版本：请在“指定已批准版本”中选择' })
          void model.openSwitcher(assetId)
          return
        }
        snapshot = { ...snapshot, draft: { ...snapshot.draft, [assetId]: { decision, revision: pinned } } }
      } else {
        snapshot = { ...snapshot, draft: { ...snapshot.draft, [assetId]: { decision, revision: null } } }
      }
      patch({})
      rebuild()
    },

    removeOverride(assetId) {
      // 恢复继承 is a draft choice; it is wording's job (and the row's badge)
      // to say it is neither an uninstall nor a global disable. No gateway
      // method is called from here — there is nothing to call.
      model.edit(assetId, 'inherit')
    },

    async openSwitcher(assetId) {
      patch({ switcher: { assetId, revisions: null }, switchRefusal: null })
      try {
        const revisions = await gateway.revisions(assetId)
        patch({ switcher: { assetId, revisions } })
      } catch (failure) {
        patch({ switcher: null, error: String(failure) })
      }
    },

    closeSwitcher() {
      patch({ switcher: null, diffPreview: null, switchRefusal: null })
    },

    async previewSwitch(assetId, toRevision) {
      // "diff from what the binding actually pins"; when nothing is pinned
      // yet the newest installed revision is the honest comparison base.
      const from = choiceOf(assetId).revision
        ?? snapshot.library.find(row => row.assetId === assetId)?.latestInstalledRevision ?? 1
      patch({ diffPreview: { assetId, fromRevision: from, toRevision, diff: null, error: null } })
      try {
        const diff = await gateway.diff({ assetId, fromRevision: from, toRevision })
        patch({ diffPreview: { assetId, fromRevision: from, toRevision, diff, error: null } })
      } catch (failure) {
        patch({ diffPreview: { assetId, fromRevision: from, toRevision, diff: null, error: String(failure) } })
      }
    },

    async confirmSwitch(assetId, toRevision) {
      if (readOnly()) { patch({ error: '本区当前只读：绑定未变更' }); return }
      // The FR07 sequence, in one explicit act and never split silently:
      // (1) an unapproved target is approved on the CONTENT layer first —
      //     approval alone moves no binding;
      // (2) only then does the profile binding draft repoint to it.
      // And NEVER for an unproven target: the approval fact must come from
      // the loaded version list. `options === null` (list not read / read
      // failed / switcher open for another asset) or a revision absent
      // from the list refuses with the typed state below — the model wall
      // exists independently of whether the view happens to hide a button.
      const options = snapshot.switcher?.assetId === assetId ? snapshot.switcher.revisions : null
      const target = options?.find(option => option.revision === toRevision) ?? null
      if (target === null) {
        patch({
          switchRefusal: {
            code: 'SWITCH_APPROVAL_UNPROVEN', assetId, toRevision,
            message: `目标版本 r${toRevision} 的批准状态未证明：版本列表未读到或该版本不在列表中，已拒绝重指，绑定未变更`,
          },
          error: '批准状态未证明：拒绝重指，绑定未变更',
        })
        return
      }
      if (!target.approved) {
        try {
          await gateway.approveRevision({ assetId, revision: toRevision })
        } catch (failure) {
          patch({ error: `批准失败，绑定保持 r${choiceOf(assetId).revision ?? '—'}：${String(failure)}` })
          return
        }
      }
      snapshot = { ...snapshot, draft: { ...snapshot.draft, [assetId]: { decision: 'enable', revision: toRevision } } }
      patch({ diffPreview: null, switchRefusal: null })
      rebuild()
    },

    async save() {
      if (readOnly() || snapshot.profile === null) {
        patch({ error: '本区当前不可保存：修改保留在草稿中，未发送任何请求' })
        return
      }
      const entries = Object.keys(snapshot.draft)
      if (entries.length === 0 && snapshot.importedHere.length === 0) return
      patch({ saving: true, conflict: null, error: null })
      // One operation key per save act: a retry of the same save cannot
      // double-apply (§G3(c) CAS contract the host mirrors).
      const operationKey = `profile-skills:${snapshot.profile.profileId}:${snapshot.profile.configRevision}:${entries.sort().join(',')}:${[...snapshot.importedHere].sort().join(',')}`
      const result = await host.saveRelations(drafted(), {
        expectedVersion: snapshot.profile.configRevision, operationKey,
      }).catch((failure: unknown) => ({
        kind: 'conflict' as const, message: String(failure), serverConfigRevision: snapshot.profile?.configRevision ?? 0,
      }) satisfies ProfileDraftWriteResult)
      if (result.kind === 'conflict') {
        // Every draft cell stays; nothing is re-sent or force-overwritten.
        patch({ saving: false, conflict: { message: result.message, serverConfigRevision: result.serverConfigRevision } })
        return
      }
      patch({ saving: false, draft: {}, importedHere: [], profile: { ...snapshot.profile, configRevision: result.configRevision } })
      await refreshEffective()
      rebuild()
    },

    discard() {
      patch({ draft: {}, conflict: null })
      rebuild()
    },

    async reread() {
      // Re-read stored state around the draft — the user's unsaved choices
      // never vanish because the server moved.
      try {
        const profile = await host.current()
        patch({ profile, layerStatus: 'ready', conflict: null })
      } catch (failure) {
        if (isProfileLayerUnavailable(failure)) patch({ layerStatus: 'unavailable' })
        else patch({ conflict: { message: String(failure), serverConfigRevision: snapshot.profile?.configRevision ?? 0 } })
      }
      await refreshEffective()
      rebuild()
    },

    async importPicked(files) {
      const declared = await Promise.all([...files].map(async file =>
        ({ path: file.path, bytes: file.bytes.byteLength, sha256: sha256Hex(file.bytes) })))
      const total = declared.reduce((sum, file) => sum + file.bytes, 0)
      let opened: { importId: string }
      try {
        opened = await gateway.importBegin(declared, total)
      } catch (failure) {
        patch({ importPhase: { kind: 'failed', message: String(failure) } })
        return
      }
      patch({ importPhase: { kind: 'transferring', importId: opened.importId, sent: 0, total: declared.length } })
      const ordered = [...files].sort((a, b) => a.path < b.path ? -1 : 1)
      const byPath = new Map(declared.map(entry => [entry.path, entry]))
      try {
        for (let index = 0; index < ordered.length; index++) {
          await gateway.importChunk(opened.importId, index, ordered[index].bytes, byPath.get(ordered[index].path)!.sha256)
          patch({ importPhase: { kind: 'transferring', importId: opened.importId, sent: index + 1, total: ordered.length } })
        }
        const preview = await gateway.importPreview(opened.importId)
        patch({ importPhase: { kind: 'prepared', importId: opened.importId, preview } })
      } catch (refusal) {
        await gateway.importCancel(opened.importId).catch(() => undefined)
        patch({ importPhase: { kind: 'failed', message: String(refusal) } })
      }
    },

    async confirmImport(assetId) {
      const phase = snapshot.importPhase
      if (phase.kind !== 'prepared') return
      const existing = snapshot.library.find(row => row.assetId === assetId) ?? null
      try {
        const committed = await gateway.importCommit(
          phase.importId, assetId, (existing?.latestInstalledRevision ?? 0) + 1)
        // Publishing proved storage, nothing more; the *relationship* becomes
        // profile draft state — content itself is never auto-chosen (FR07).
        patch({ importPhase: { kind: 'committed', assetId: committed.assetId, revision: committed.revision } })
        if (!snapshot.importedHere.includes(committed.assetId)) {
          patch({ importedHere: [...snapshot.importedHere, committed.assetId] })
        }
        patch({ library: await gateway.listSkills() })
        rebuild()
      } catch (refusal) {
        patch({ importPhase: { kind: 'failed', message: String(refusal) } })
      }
    },

    async cancelImport() {
      const phase = snapshot.importPhase
      if (phase.kind === 'prepared' || phase.kind === 'transferring') {
        await gateway.importCancel(phase.importId).catch(() => undefined)
      }
      patch({ importPhase: { kind: 'idle' } })
    },

    async cancelProfileEditing() {
      // The host discards the profile EDIT (relationship state). There is no
      // call this could make that deletes imported content — the G15
      // counter-example is structurally impossible, and the rows below prove
      // the content survived.
      await host.cancelEditing().catch(() => undefined)
      patch({ draft: {}, importedHere: [], conflict: null, importPhase: { kind: 'idle' } })
      try {
        patch({ library: await gateway.listSkills() })
      } catch { /* the error banner keeps the last-good list; nothing deleted */ }
      try {
        const profile = await host.current()
        patch({ profile, layerStatus: 'ready' })
      } catch (failure) {
        if (isProfileLayerUnavailable(failure)) patch({ layerStatus: 'unavailable' })
      }
      await refreshEffective()
      rebuild()
    },
  }

  const highestKnownApproved = (assetId: string): number | null => {
    const options = snapshot.switcher?.assetId === assetId ? snapshot.switcher.revisions : null
    const approved = (options ?? []).filter(option => option.approved)
    return approved.length === 0 ? null : Math.max(...approved.map(option => option.revision))
  }

  rebuild()
  return model
}

/** A committed import needs a client-side slug for `skills.importCommit`'s
 * required `assetId` param (the backend wall is `api/identity.py ASSET_ID`);
 * a name that cannot slugify is refused rather than invented into a hash. */
export function deriveAssetId(name: string): string | null {
  const slug = name.toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^[^a-z0-9]+/, '').slice(0, 64)
  return /^[a-z0-9][a-z0-9._-]{0,63}$/.test(slug) && slug.length > 0 ? slug : null
}
