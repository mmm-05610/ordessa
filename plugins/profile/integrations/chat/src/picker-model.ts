/**
 * Composer picker component: a plain grouped selector, keyboard-reachable,
 * showing the selected name immediately (ux.md §3).  Deliberately thin:
 * Harness groups map to option groups, profiles to options; no status
 * badges ("当前使用/下轮待生效/本会话有修改") are ever rendered here.
 */
import type { ProfileCatalogGroup, ProfileSelection } from '@ordessa/plugin-profile-api'

export interface ProfilePickerProps {
  readonly label: string | null
  readonly groups: readonly ProfileCatalogGroup[]
  readonly disabledReason?: string
  readonly statusMessage?: string
  /** 021 §6c F1.1: the current pick's click-time registration failed (or has
   * not been retried). Surfaced, never swallowed; the pick stays unregistered
   * and a retry happens at the next submit. */
  readonly registrationError?: string | null
  readonly onRefresh?: () => void
  readonly onOpenSelector?: () => void
  readonly subscribe?: (listener: () => void) => () => void
  readonly getSnapshot?: () => number
  readonly getLiveProps?: () => ProfilePickerProps
  readonly onOpenManager?: () => void
  readonly onSelect: (selection: ProfileSelection) => void
  readonly onClearSelection?: () => void
  /** 021 T04 bound-fact seam: when this chat session has a Profile glue
   * binding registered (a backend fact learned at registerNativeSession),
   * its chat identity travels here so the model route's submission guard can
   * dispatch bound (apply nothing) vs unbound (apply the queued intent).
   * Absent — no Profile extension, no binding — reads as unbound. */
  readonly boundNativeSession?: {
    readonly serverInstanceId: string
    readonly sessionId: string
  } | null
  /** 021 §6c F1.2 click-order seam: when a binding exists, the model side's
   * `chooseForSession` click call must run through this per-session
   * serializer so both contributions' registration calls reach the Server in
   * click order (the backend action_seq stamps click order). Null — no
   * binding — means the model side calls directly, unchanged. Same read-side
   * projection channel as `boundNativeSession`; it never applies anything. */
  readonly serializeRegistration?: ((task: () => Promise<void>) => Promise<void>) | null
}

export function selectedOptionValue(groups: readonly ProfileCatalogGroup[],
                                    label: string | null): string {
  if (label) {
    for (const group of groups) {
      for (const profile of group.profiles) {
        if (profile.displayName === label)
          return `${group.harnessId}::${profile.profileId}`
      }
    }
  }
  return ''
}

export function pickerOptionGroups(groups: readonly ProfileCatalogGroup[]) {
  return groups.map((group) => ({
    harnessId: group.harnessId,
    harnessTitle: group.harnessTitle,
    options: group.profiles.map((profile) => ({
      value: `${group.harnessId}::${profile.profileId}`,
      label: profile.displayName,
      archived: profile.archived,
      selection: { harnessId: group.harnessId, profileId: profile.profileId, displayName: profile.displayName } satisfies ProfileSelection,
    })),
  }))
}
