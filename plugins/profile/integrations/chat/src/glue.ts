/**
 * Profile → Chat glue (PV-10).  Optional entry: without Chat (no
 * ChatContributionsToken) or without Profile (no ProfileServiceToken) this
 * glue is simply absent and both products keep working (contracts.md §4).
 *
 * The glue contributes one composer.toolbar picker.  It owns NO state of the
 * Chat, stores no draft text, and holds no session lifecycle: selections live
 * in {@link ProfileSelectionStore} and die with the UI scope (G18).
 */
import type { ResourceScope } from '@ordessa/extension-api'
import {
  chatContribution,
  defineChatComponentKey,
  type ChatContributionContext,
  type ChatContributionsService,
  type ChatLocation,
} from '@extensions/ordessa.chat-api/contract.js'
import type {
  ProfileCatalogGroup,
  ProfileSelection,
  ProfileServiceClient,
} from '@ordessa/plugin-profile-api'
import { ProfilePicker } from './picker'
import type { ProfilePickerProps } from './picker-model'
import { catalogForLocation, ProfileSelectionStore } from './selection'

export { ProfileSelectionStore, catalogForLocation } from './selection'
export type { ApplyOutcome, SelectionCounters } from './selection'
export { ProfilePicker } from './picker'
export { pickerOptionGroups, selectedOptionValue } from './picker-model'
export type { ProfilePickerProps } from './picker-model'

/** Chat-owned key factory: the glue never invents a second key identity. */
export const ProfilePickerKey =
  defineChatComponentKey<ProfilePickerProps>('ordessa.profile.picker', 1)

export interface ChatLocationLike {
  readonly kind?: string
  readonly draftId?: string
  readonly sessionUid?: string
}

/** Extract the picker's store key + catalog scope from the chat location. */
export function pickerKeyFor(location: ChatLocation): {
  key: string
  scope: { readonly kind: 'draft' } | { readonly kind: 'session'; readonly harnessId: string }
} {
  const raw = location as unknown as {
    kind?: string
    draftId?: string
    sessionUid?: string
    harnessId?: string
  }
  if (raw.kind === 'session' && raw.sessionUid) {
    return {
      key: `session:${raw.sessionUid}`,
      scope: { kind: 'session', harnessId: raw.harnessId ?? '' },
    }
  }
  return { key: `draft:${raw.draftId ?? 'unknown'}`, scope: { kind: 'draft' } }
}

export interface ProfileChatGlueInput {
  readonly store?: ProfileSelectionStore
  readonly profiles: Pick<ProfileServiceClient, 'beginTurnApplication'>
  readonly catalog: () => readonly ProfileCatalogGroup[]
  readonly onOpenManager?: () => void
}

export function createProfileChatGlue(
  scope: ResourceScope,
  contributions: ChatContributionsService,
  input: ProfileChatGlueInput,
) {
  const store = input.store ?? new ProfileSelectionStore()
  const registration = chatContribution<ProfilePickerProps>({
    id: 'ordessa.profile-chat.picker',
    slot: 'composer.toolbar',
    order: 10,
    key: ProfilePickerKey,
    project: (context: ChatContributionContext) => {
      if (context.slot !== 'composer.toolbar') return { hidden: true }
      const { key, scope: pickerScope } = pickerKeyFor(context.location)
      const groups = catalogForLocation(input.catalog(), pickerScope)
      if (groups.length === 0) return { hidden: true }
      return {
        hidden: false,
        props: {
          label: store.currentLabel(key),
          groups,
          onOpenManager: input.onOpenManager,
          onSelect: (selection: ProfileSelection) => store.select(key, selection),
        },
      }
    },
  })
  const disposeRegistration =
    contributions.forScope(scope).addContribution(registration)
  return {
    store,
    dispose() {
      disposeRegistration.dispose()
    },
  }
}

/** Read-side convenience for the Chat host outlet. */
export function pickerComponent() {
  return ProfilePicker
}
