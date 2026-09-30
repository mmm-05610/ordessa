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
import type { ProfileCatalog } from './catalog'

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
  readonly sessionId?: string
}

/** Extract the picker's store key + catalog scope from the chat location. */
export function pickerKeyFor(location: ChatLocation): {
  key: string
  scope: { readonly kind: 'draft' } | { readonly kind: 'session'; readonly harnessId: string }
} {
  if (location.kind === 'session') {
    return {
      key: `session:${location.sessionId}`,
      scope: { kind: 'session', harnessId: location.harnessId ?? '' },
    }
  }
  return { key: `draft:${location.draftId}`, scope: { kind: 'draft' } }
}

export interface ProfileChatGlueInput {
  readonly store?: ProfileSelectionStore
  readonly profiles: Pick<ProfileServiceClient, 'beginTurnApplication'> & Partial<Pick<ProfileServiceClient, 'selectForSession' | 'inspectSessionConfig'>>
  readonly catalog: () => readonly ProfileCatalogGroup[]
  readonly catalogState?: Pick<ProfileCatalog, 'message' | 'subscribe' | 'getSnapshot' | 'refresh'>
  readonly onOpenManager?: () => void
}

export function createProfileChatGlue(
  scope: ResourceScope,
  contributions: ChatContributionsService,
  input: ProfileChatGlueInput,
) {
  const store = input.store ?? new ProfileSelectionStore()
  const subscribe = (listener: () => void) => {
    const stopStore = store.subscribe(listener)
    const stopCatalog = input.catalogState?.subscribe(listener)
    return () => { stopStore(); stopCatalog?.() }
  }
  const getSnapshot = () => store.getSnapshot() + (input.catalogState?.getSnapshot() ?? 0)
  const scoped = contributions.forScope(scope)
  const guard = scoped.addSubmissionGuard({ id: 'ordessa.profile-chat.application', order: 10,
    async prepare(snapshot) {
      const { key } = pickerKeyFor(snapshot.target)
      return store.peek(key)
        ? { status: 'refused', reason: 'Profile 会话应用尚未接入：缺少后端会话身份与生产应用端口。所选预设和草稿已保留。' }
        : { status: 'ready' }
    },
  })
  const registration = chatContribution<ProfilePickerProps>({
    id: 'ordessa.profile-chat.picker',
    slot: 'composer.toolbar',
    order: 10,
    key: ProfilePickerKey,
    project: (context: ChatContributionContext) => {
      if (context.slot !== 'composer.toolbar') return { hidden: true }
      const { key, scope: pickerScope } = pickerKeyFor(context.location)
      const liveProps = (): ProfilePickerProps => {
        const groups = catalogForLocation(input.catalog(), pickerScope)
        return {
          label: store.currentLabel(key), groups,
          statusMessage: input.catalogState?.message || (groups.length ? undefined : '当前 Harness 没有可用预设。'),
          onRefresh: input.catalogState ? () => { void input.catalogState!.refresh() } : undefined,
          onOpenSelector: input.catalogState ? () => { void input.catalogState!.refresh() } : undefined,
          onOpenManager: input.onOpenManager,
          onSelect: (selection: ProfileSelection) => store.select(key, selection),
          onClearSelection: () => store.forget(key),
        }
      }
      return {
        hidden: false,
        props: {
          ...liveProps(), subscribe, getSnapshot, getLiveProps: liveProps,
        },
      }
    },
  })
  const disposeRegistration =
    scoped.addContribution(registration)
  return {
    store,
    dispose() {
      disposeRegistration.dispose()
      guard.dispose()
    },
  }
}

/** Read-side convenience for the Chat host outlet. */
export function pickerComponent() {
  return ProfilePicker
}
