/**
 * Ordessa Profile v2 — public contract vocabulary (the `profile-api`
 * checkpoint surface, TS half).
 *
 * Source of truth for semantics: docs/design/profile-v2/contracts.md
 * (§1 facet providers, §2 frontend contributions, §3 service operations),
 * data-model.md (§1 entities, §2 resolution), ux.md.  The Python twin of
 * this surface is `plugins/profile/src/ordessa_profile/contracts.py`;
 * field names here are its camelCase projection.
 *
 * Contract-only package: nothing here performs I/O, holds configuration
 * values, or enables anything by its mere import (no auto-enable).
 */
import type { IDisposable, ResourceScope } from '@ordessa/extension-api'
import type { ComponentType } from 'react'

// ---------------------------------------------------------------------------
// value states (PF04): unset / explicit value / disabled / provider-absent
// ---------------------------------------------------------------------------

/**
 * Sentinel for "not set — defer to the target default".  Deliberately NOT
 * `undefined`/`null`: an explicit `null` is a real value whenever the item
 * schema allows it.  The four states are never collapsed into one (PF04);
 * `provider-absent` is a registry fact, never a stored state, and is
 * reported through `availability` fields instead.
 */
export const UNSET = Symbol('ordessa.profile.unset')
export type Unset = typeof UNSET

export interface DisabledValue {
  readonly disabled: true
  /** Optional non-secret reason string for diagnostics. */
  readonly reason?: string
}

export type ItemValue = Unset | DisabledValue | unknown

export type ValueStateKind = 'unset' | 'explicit' | 'disabled' | 'provider-absent'

/** Classify one value (mirror of Python `value_state`). */
export function valueState(value: ItemValue): ValueStateKind {
  if (value === UNSET) return 'unset'
  if (
    typeof value === 'object' && value !== null &&
    (value as DisabledValue).disabled === true
  ) return 'disabled'
  return 'explicit'
}

// ---------------------------------------------------------------------------
// facet / item descriptors (contracts.md §1)
// ---------------------------------------------------------------------------

export type Applicability = 'supported' | 'unsupported' | 'unknown'

export type FacetCategory =
  | 'model' | 'capabilities' | 'behavior' | 'instructions' | 'advanced'

export type ItemSensitivity = 'non-secret' | 'opaque-reference'

export type ItemEffect =
  | 'configuration'
  | 'capability-selection'
  | 'permission'
  | 'instruction'

/** Controlled JSON-schema subset; unknown keywords are refused backend-side
 * (Python `validate_schema_shape`) — the frontend copy is for rendering only
 * and is never an authorization (contracts.md §2). */
export type ItemValueSchema = {
  readonly type: 'string' | 'integer' | 'number' | 'boolean' | 'array' | 'object' | 'null'
  readonly enum?: readonly unknown[]
  readonly items?: ItemValueSchema
  readonly minItems?: number
  readonly maxItems?: number
  readonly minimum?: number
  readonly maximum?: number
  readonly default?: unknown
  readonly title?: string
  readonly description?: string
  readonly allowNull?: boolean
}

export interface ItemDescriptor {
  readonly itemId: string
  readonly valueSchema: ItemValueSchema
  readonly optional: boolean
  readonly overrideSupported: boolean
  readonly sensitivity: ItemSensitivity
  readonly effect: ItemEffect
  readonly title: string
  readonly description: string
}

export interface FacetDescriptor {
  readonly facetId: string
  readonly apiMajor: number
  readonly schemaVersion: string
  readonly label: string
  readonly description: string
  readonly category: FacetCategory
  readonly order: number
  readonly itemDescriptors: readonly ItemDescriptor[]
}

/** Sanitized catalog entry (service `describeFacets` result). */
export interface FacetCatalogEntry extends FacetDescriptor {
  /** Host-injected owner plugin id; never self-reported. */
  readonly ownerPluginId: string
  readonly applicability: Applicability
}

// ---------------------------------------------------------------------------
// violations, patches, sources, receipts, journal (data-model.md §1)
// ---------------------------------------------------------------------------

export interface Violation {
  readonly facetId: string
  readonly itemId: string
  readonly code: string
  readonly message: string
}

/** One typed set/unset edit.  Unmodified items never appear in a patch;
 * `unset` carries no value. */
export type ItemPatch =
  | { readonly facetId: string; readonly itemId: string; readonly op: 'set'; readonly value: unknown }
  | { readonly facetId: string; readonly itemId: string; readonly op: 'unset' }

/** Namespace-scoped settings patch (provider-owned settings section). */
export type SettingsPatch = {
  readonly namespace: string
} & ItemPatch

export function assertItemPatch(patch: ItemPatch): void {
  if (typeof patch.facetId !== 'string' || !patch.facetId)
    throw new TypeError('ItemPatch.facetId is required')
  if (typeof patch.itemId !== 'string' || !patch.itemId)
    throw new TypeError('ItemPatch.itemId is required')
  if (patch.op === 'set') {
    if (patch.value === undefined)
      throw new TypeError('a "set" patch requires a value (use op:"unset" instead)')
  } else if (patch.op === 'unset') {
    if ('value' in patch)
      throw new TypeError('an "unset" patch must not carry a value')
  } else {
    throw new TypeError(`unknown ItemPatch op: ${String((patch as { op?: unknown }).op)}`)
  }
}

/** Where one resolved value came from (data-model.md §2.6). */
export type ValueSource =
  | { readonly kind: 'profile'; readonly revision: number }
  | { readonly kind: 'session-overlay'; readonly revision: number }
  | { readonly kind: 'target-default'; readonly fingerprint: string }

export interface ResolvedItem {
  readonly facetId: string
  readonly itemId: string
  readonly value: ItemValue
  readonly state: ValueStateKind
  readonly source: ValueSource
  readonly needsRunValidation?: boolean
}

/** Canonical, stable session identity — a short-lived channel id is never a
 * session identity (data-model.md §1).  Mirror of Python `SessionRef`. */
export interface SessionRef {
  readonly realm: string
  readonly harnessId: string
  readonly nativeSessionKey: string
  readonly sessionUid: string
}

export type JournalState =
  | 'planned' | 'applying' | 'confirmed' | 'rejected' | 'unknown'

export interface AppliedReceiptDto {
  readonly operationId: string
  readonly sessionRef: SessionRef
  readonly runtimeGeneration: string
  /** Digest over non-secret config facts only — never secret values (G15). */
  readonly configDigest: string
  readonly profileId: string
  readonly profileRevision: number
  readonly overlayRevision: number | null
  readonly policyRevision: number
  readonly providerGenerations: Readonly<Record<string, number>>
  /** Adapter-declared evidence kind; 'legacy-unverified' can never be stored
   * as a receipt, and a DB read-back is never runtime evidence. */
  readonly evidenceKind: string
  readonly confirmedAt: string
  readonly executionId?: string
}

export interface JournalEntryDto {
  readonly operationId: string
  readonly state: JournalState
  readonly profileId: string
  readonly profileRevision: number
  readonly planDigest: string
  readonly failure?: string
  readonly detailRefs: readonly string[]
  readonly createdAt: string
  readonly updatedAt: string
}

/** Session evidence projection: a session without any receipt is reported
 * as `legacy-unverified`, never as confirmed (PV-04). */
export interface SessionEvidence {
  readonly journal: JournalEntryDto | null
  readonly receipt: AppliedReceiptDto | null
  readonly evidenceKind: string
}

// ---------------------------------------------------------------------------
// mechanism policy (US1)
// ---------------------------------------------------------------------------

export interface MechanismPolicyDto {
  readonly realm: string
  readonly revision: number
  /** Registered facets default to enabled; this map carries explicit rulings. */
  readonly facetEnabled: Readonly<Record<string, boolean>>
  readonly allowUserOverrideWritesGlobal: boolean
  readonly allowUserOverrideWrites: Readonly<Record<string, boolean>>
}

export interface PolicyImpactPreview {
  readonly disabling: Readonly<Record<string, {
    readonly profilesWithValues: number
    readonly sessionsWithOverlays: number
  }>>
}

export interface MechanismPolicyPatch {
  readonly facetEnabled?: Readonly<Record<string, boolean>>
  readonly allowUserOverrideWritesGlobal?: boolean
  readonly allowUserOverrideWrites?: Readonly<Record<string, boolean>>
}

// ---------------------------------------------------------------------------
// editor / settings contributions (contracts.md §2)
// ---------------------------------------------------------------------------

export interface ProfileTargetRef {
  readonly serverRef: string
  readonly profileId: string
  readonly harnessId: string
}

/** Props every facet editor receives.  Editors only mutate the page draft
 * through `onPatch` — they never save the profile, never touch sessions,
 * credentials or registries (contracts.md §2). */
export interface FacetEditorProps {
  readonly target: ProfileTargetRef
  readonly revision: number
  readonly draftGeneration: number
  readonly items: readonly ResolvedItem[]
  readonly validation: readonly Violation[]
  readonly applicability: Applicability
  readonly readOnlyReason?: string
  readonly onPatch: (patches: readonly ItemPatch[]) => void
}

/** C7 component key; aligned with the platform component registry.  Kept as
 * a type alias so the C7 alignment is a type-level change only. */
export type ComponentKey<P> = string & { readonly __componentProps?: P }

export type EditorCategory = FacetCategory

export interface ProfileEditorContribution {
  readonly facetId: string
  readonly supportedSchemaRange: readonly [string, string]
  readonly componentKey: ComponentKey<FacetEditorProps>
  readonly category: EditorCategory
  readonly order: number
}

export interface ProfileSettingsTargetRef {
  readonly serverRef: string
}

/** Props for a provider-owned settings section inside the Profile settings
 * page.  The provider owns schema, validation and persistence of its own
 * namespace; Profile only binds the restricted props/actions (contracts.md
 * §2) — never a whole-store writer or a service locator. */
export interface ProfileSettingsProps {
  readonly target: ProfileSettingsTargetRef
  readonly settingsRevision: number
  readonly providerGeneration: number
  readonly values: Readonly<Record<string, unknown>>
  readonly validation: readonly Violation[]
  readonly readOnlyReason?: string
  readonly onPatch: (patch: SettingsPatch, expectedRevision: number) => void
}

export interface ProfileSettingsContribution {
  readonly id: string
  readonly facetId: string
  readonly title: string
  readonly order: number
  readonly componentKey: ComponentKey<ProfileSettingsProps>
}

/** The two independent registration faces Profile exposes (contracts.md §2).
 * Duplicate ids are refused; releasing the scope unloads the contributions.
 * Absence of the token means no Profile UI — consumers must not fake it. */
export interface ProfileContributionsForScope {
  addEditor(contribution: ProfileEditorContribution): IDisposable
  addSettingsSection(contribution: ProfileSettingsContribution): IDisposable
}

export interface ProfileContributions {
  forScope(scope: ResourceScope): ProfileContributionsForScope
}

// ---------------------------------------------------------------------------
// chat glue data shapes (PV-10 — the Chat-side registry is chat-api's)
// ---------------------------------------------------------------------------

export interface ProfileSummary {
  readonly profileId: string
  readonly harnessId: string
  readonly displayName: string
  readonly archived: boolean
}

/** Two-level catalog group for selectors: Harness → its profiles.  Only
 * currently-available Harness groups are included; offline data stays
 * visible in management UI, not here (ux.md §3). */
export interface ProfileCatalogGroup {
  readonly harnessId: string
  readonly harnessTitle: string
  readonly profiles: readonly ProfileSummary[]
}

/** What the user picked.  Selecting registers intent only — it never claims
 * the selection is applied (PA01/ux.md §3). */
export interface ProfileSelection {
  readonly harnessId: string
  readonly profileId: string
  readonly displayName: string
}
