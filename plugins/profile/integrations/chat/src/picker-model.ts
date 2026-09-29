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
  readonly onOpenManager?: () => void
  readonly onSelect: (selection: ProfileSelection) => void
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
