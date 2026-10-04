/**
 * Headless behaviour layer behind the Profile settings and management views
 * (PV-08/PV-09).  React components render from these stores; the stores hold
 * every rule so the UI gates stay testable without geometry.
 *
 * Rules enforced here (not in the component):
 * - settings toggles go through CAS (expectedRevision) and snapshot the
 *   impact preview BEFORE disabling a facet (PS05);
 * - editor drafts are page-local: an explicit save sends one patch list with
 *   the loaded expectedVersion; a stale-version refusal keeps the local input
 *   for compare/reload and never overwrites the remote (PM04, G05);
 * - offline/dead-scope states keep the last known list and mark it read-only
 *   instead of clearing it (PM02/G02).
 */
import type {
  FacetCatalogEntry,
  MechanismPolicyDto,
  PolicyImpactPreview,
  ProfileIdentityDto,
  ItemPatch,
  ProfileServiceClient,
  UpdatePolicyOutcomeDto,
} from '@ordessa/plugin-profile-api'
import { createEditSession } from '@ordessa/ui-components/editing'
import { createQueryCache } from '@ordessa/ui-components/query-cache'
import { createTaskScope } from '@ordessa/ui-components/tasks'

let editSessionSeq = 0

function editField(patch: Pick<ItemPatch, 'facetId' | 'itemId'>): string {
  return `${patch.facetId}\u0000${patch.itemId}`
}

export interface PolicyState {
  policy: MechanismPolicyDto | null
  lastImpact: PolicyImpactPreview | null
  loading: boolean
  error: string | null
}

export class MechanismPolicyStore {
  state: PolicyState = { policy: null, lastImpact: null, loading: false, error: null }

  constructor(private readonly client: ProfileServiceClient) {}

  /** PS05 dry run: impact counts without mutation. */
  async previewFacetDisable(realm: string, facetId: string): Promise<PolicyImpactPreview | null> {
    const policy = this.state.policy
    if (!policy) return null
    try {
      const result = await this.client.previewMechanismPolicy(
        `profile.settings.preview:${facetId}:${policy.revision}`,
        { realm, expectedRevision: policy.revision,
          patch: { facetEnabled: { [facetId]: false } }, caller: 'profile.settings' },
      )
      return result.impact
    } catch {
      return null
    }
  }

  async load(realm: string): Promise<void> {
    this.state = { ...this.state, loading: true, error: null }
    try {
      const policy = await this.client.getMechanismPolicy(realm)
      this.state = { ...this.state, policy, loading: false }
    } catch (error) {
      this.state = { ...this.state, loading: false, error: message(error) }
    }
  }

  /** Toggle one facet.  Enabling goes straight through; disabling first
   * fetches the impact preview and asks `confirm` to proceed (PS05). */
  async setFacetEnabled(
    realm: string,
    facetId: string,
    enabled: boolean,
    confirm?: (impact: PolicyImpactPreview) => boolean | Promise<boolean>,
  ): Promise<void> {
    const policy = this.state.policy
    if (!policy) throw new Error('policy not loaded')
    if (!enabled && confirm) {
      const preview = await this.previewFacetDisable(realm, facetId)
      if (preview && !(await confirm(preview))) return
    }
    await this.patch(realm, { facetEnabled: { [facetId]: enabled } }, facetId)
  }

  async setOverrideWrites(realm: string, facetId: string | null, allowed: boolean): Promise<void> {
    if (facetId === null) {
      await this.patch(realm, { allowUserOverrideWritesGlobal: allowed })
      return
    }
    await this.patch(realm, { allowUserOverrideWrites: { [facetId]: allowed } })
  }

  private async patch(realm: string, partial: Record<string, unknown>, previewKey?: string): Promise<void> {
    const policy = this.state.policy
    if (!policy) throw new Error('policy not loaded')
    const patch = partial as Parameters<ProfileServiceClient['updateMechanismPolicy']>[1]['patch']
    try {
      const result: UpdatePolicyOutcomeDto = await this.client.updateMechanismPolicy(
        `profile.settings:${previewKey ?? 'global'}:${policy.revision}:${JSON.stringify(patch)}`,
        { realm, expectedRevision: policy.revision, patch, caller: 'profile.settings' },
      )
      this.state = { ...this.state, policy: result.policy, lastImpact: result.impact, error: null }
    } catch (error) {
      this.state = { ...this.state, error: message(error) }
      throw error
    }
  }
}

export type SaveOutcome =
  | { readonly ok: true; readonly revision: number }
  | { readonly ok: false; readonly conflict: true; readonly localPatches: readonly ItemPatch[] }
  | { readonly ok: false; readonly conflict: false; readonly reason: string }

/** One open profile editor: buffered patches + explicit save. */
export class ProfileDraftStore {
  private session: ReturnType<typeof createEditSession<Record<string, ItemPatch>>>
  private pendingOperationKey = ''
  private savedRevision: number | null = null
  saveError: string | null = null
  lastConflictRemote: ProfileIdentityDto | null = null

  constructor(
    private readonly client: ProfileServiceClient,
    readonly profile: ProfileIdentityDto,
  ) {
    this.session = this.newSession()
  }

  private newSession() {
    return createEditSession<Record<string, ItemPatch>>({
      editId: `profile-edit:${this.profile.profileId}:${++editSessionSeq}`,
      baseRevision: String(this.profile.currentRevision),
      initial: {},
      commitHandler: capture => this.commitCapture(capture),
    })
  }

  get baseRevision(): string {
    return this.session.baseRevision
  }

  get dirty(): boolean {
    return this.session.dirtyFields().size > 0
  }

  get localPatches(): readonly ItemPatch[] {
    return [...this.session.dirtyFields()].map(field => this.session.current[field]!)
  }

  edit(patch: ItemPatch): void {
    this.session.setValue(editField(patch), patch)
  }

  discard(): void {
    this.session.cancel()
    this.session = this.newSession()
    this.saveError = null
    this.lastConflictRemote = null
  }

  async save(operationKey: string): Promise<SaveOutcome> {
    if (!this.dirty) return { ok: true, revision: this.profile.currentRevision }
    this.pendingOperationKey = operationKey
    this.savedRevision = null
    const outcome = await this.session.commit()
    if (outcome.kind === 'saved') {
      this.saveError = null
      this.lastConflictRemote = null
      return { ok: true, revision: this.savedRevision ?? this.profile.currentRevision }
    }
    if (outcome.kind === 'conflict') {
      return { ok: false, conflict: true, localPatches: this.localPatches }
    }
    if (outcome.kind === 'unknown') {
      return { ok: false, conflict: false, reason: this.saveError ?? `unknown save outcome (${outcome.queryHint})` }
    }
    this.saveError = outcome.reason
    return { ok: false, conflict: false, reason: outcome.reason }
  }

  private async commitCapture(capture: {
    editId: string
    baseRevision: string
    editRevision: number
    fields: ReadonlyArray<string>
    values: Readonly<Partial<Record<string, ItemPatch>>>
  }) {
    const patches = capture.fields.map(field => capture.values[field]!).filter(Boolean)
    try {
      const result = await this.client.saveProfile(this.pendingOperationKey, {
        profileId: this.profile.profileId,
        expectedVersion: this.profile.version,
        patches,
      })
      this.savedRevision = result.profile.currentRevision
      return { kind: 'saved' as const, consumedFields: [...capture.fields] }
    } catch (error) {
      const code = (error as { code?: string }).code
      if (code === 'PROFILE_VERSION_CONFLICT') {
        // Keep every local input for compare/reload; never auto-overwrite.
        this.lastConflictRemote = (error as { current?: ProfileIdentityDto }).current ?? null
        return {
          kind: 'conflict' as const,
          field: capture.fields[0] ?? 'profile',
          theirRevision: String(this.lastConflictRemote?.currentRevision ?? this.lastConflictRemote?.version ?? 'unknown'),
        }
      }
      this.saveError = message(error)
      return { kind: 'unknown' as const, queryHint: `profile-save:${this.pendingOperationKey}` }
    }
  }

}

/** Catalog state for the management navigator (PM02): offline keeps the last
 * list read-only instead of emptying it. */
export class ProfileCatalogStore {
  state = {
    profiles: [] as readonly ProfileIdentityDto[],
    facets: [] as readonly FacetCatalogEntry[],
    online: true,
    loading: false,
    lastSyncedAt: null as string | null,
  }

  private readonly cache = createQueryCache({ maxEntries: 16 })
  private readonly generationScope = 'profile-catalog-instance'
  private generation = 0
  private readonly tasks = createTaskScope({ currentGeneration: () => this.generation })

  constructor(private readonly client: ProfileServiceClient) {}

  async refresh(realm: string, includeArchived: boolean): Promise<void> {
    const generation = ++this.generation
    this.state = { ...this.state, loading: true }
    const key = {
      environment: realm,
      connectionGeneration: 0,
      authorizationScope: this.generationScope,
      authorizationGeneration: 0,
      serviceTarget: 'profile.catalog',
      contractVersion: 'profile-service/1',
      params: { realm, includeArchived },
    }
    const declaration = this.cache.declaration({ key, run: async () => {
      const [profiles, facets] = await Promise.all([
        this.client.listProfiles(realm, includeArchived),
        this.client.describeFacets(null),
      ])
      return { profiles, facets }
    } })
    const task = this.tasks.run(
      { activation: 'profile-catalog', generation },
      async () => {
        const entry = this.cache.read(declaration)
        if (entry.state === 'success' || entry.state === 'error' || entry.state === 'stale') {
          await this.cache.refresh(key)
        }
        const refreshed = this.cache.read(declaration)
        await this.waitForTerminal(refreshed)
        if (refreshed.state === 'error' || refreshed.data === undefined) {
          throw new Error('Profile catalog read failed')
        }
        return refreshed.data
      },
    )
    const result = await task.result()
    if (generation !== this.generation) return
    if (result.kind === 'done') {
      this.state = {
        profiles: result.value.profiles, facets: result.value.facets, online: true, loading: false,
        lastSyncedAt: new Date().toISOString(),
      }
    } else if (result.kind === 'failed') {
      // keep the previous lists; mark offline/read-only (PM02)
      this.state = { ...this.state, online: false, loading: false }
    } else {
      this.state = { ...this.state, loading: false }
    }
  }

  private waitForTerminal(entry: {
    readonly state: 'idle' | 'loading' | 'success' | 'error' | 'stale'
    subscribe(listener: () => void): { release(): void }
  }): Promise<void> {
    if (entry.state === 'success' || entry.state === 'error' || entry.state === 'stale') return Promise.resolve()
    return new Promise(resolve => {
      const handle = entry.subscribe(() => {
        if (entry.state === 'success' || entry.state === 'error' || entry.state === 'stale') {
          handle.release()
          resolve()
        }
      })
    })
  }

  dispose(): void {
    this.tasks.releaseAll()
    this.cache.clearScope(this.generationScope)
  }
}

/** Two-level navigator grouping: Harness → profiles (PM01/PM03), with the
 * Unicode NFC + trim + casefold duplicate view filter kept server-authority
 * (the backend enforces; the view only groups). */
export function groupByHarness<T extends { profileId: string; harnessId: string }>(
  profiles: readonly T[],
  facetApplicability: Readonly<Record<string, string>> = {},
): readonly { harnessId: string; entries: readonly T[] }[] {
  const groups = new Map<string, T[]>()
  for (const profile of profiles) {
    if (facetApplicability[profile.harnessId] === 'unsupported') continue
    const list = groups.get(profile.harnessId) ?? []
    list.push(profile)
    groups.set(profile.harnessId, list)
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([harnessId, entries]) => ({ harnessId, entries }))
}

export function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
