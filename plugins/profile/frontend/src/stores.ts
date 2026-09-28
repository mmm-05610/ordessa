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
    confirm?: (impact: PolicyImpactPreview) => boolean,
  ): Promise<void> {
    const policy = this.state.policy
    if (!policy) throw new Error('policy not loaded')
    if (!enabled && confirm) {
      const preview = await this.previewFacetDisable(realm, facetId)
      if (preview && !confirm(preview)) return
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
  private patches: ItemPatch[] = []
  dirty = false
  saveError: string | null = null
  lastConflictRemote: ProfileIdentityDto | null = null

  constructor(
    private readonly client: ProfileServiceClient,
    readonly profile: ProfileIdentityDto,
  ) {}

  get localPatches(): readonly ItemPatch[] {
    return this.patches
  }

  edit(patch: ItemPatch): void {
    this.patches = [...this.patches.filter((p) => !(p.facetId === patch.facetId && p.itemId === patch.itemId)), patch]
    this.dirty = true
  }

  async save(operationKey: string): Promise<SaveOutcome> {
    if (!this.dirty) return { ok: true, revision: this.profile.currentRevision }
    try {
      const result = await this.client.saveProfile(operationKey, {
        profileId: this.profile.profileId,
        expectedVersion: this.profile.version,
        patches: this.patches,
      })
      this.patches = []
      this.dirty = false
      this.saveError = null
      this.lastConflictRemote = null
      return { ok: true, revision: result.profile.currentRevision }
    } catch (error) {
      const code = (error as { code?: string }).code
      if (code === 'PROFILE_VERSION_CONFLICT') {
        // Keep every local input for compare/reload; never auto-overwrite.
        this.lastConflictRemote = (error as { current?: ProfileIdentityDto }).current ?? null
        return { ok: false, conflict: true, localPatches: this.patches }
      }
      this.saveError = message(error)
      return { ok: false, conflict: false, reason: this.saveError }
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

  constructor(private readonly client: ProfileServiceClient) {}

  async refresh(realm: string, includeArchived: boolean): Promise<void> {
    this.state = { ...this.state, loading: true }
    try {
      const [profiles, facets] = await Promise.all([
        this.client.listProfiles(realm, includeArchived),
        this.client.describeFacets(null),
      ])
      this.state = {
        profiles, facets, online: true, loading: false,
        lastSyncedAt: new Date().toISOString(),
      }
    } catch {
      // keep the previous lists; mark offline/read-only (PM02)
      this.state = { ...this.state, online: false, loading: false }
    }
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
