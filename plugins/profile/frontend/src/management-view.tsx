/**
 * Independent Profile manager (US2, PV-09, ux.md §2): in-page master/detail,
 * two-level Harness → Profile navigation, search, archived toggle, explicit
 * save with conflict retention and an unsaved-changes guard.
 */
import type { ReactNode } from 'react'
import { Button, Checkbox, Input, Notice } from '@ordessa/ui'
import type { ProfileDraftStore } from './stores'
import { groupByHarness } from './stores'
import type { ProfileIdentityDto } from '@ordessa/plugin-profile-api'

export interface ManagementViewProps {
  readonly profiles: readonly Pick<ProfileIdentityDto, 'profileId' | 'displayName' | 'harnessId' | 'archivedAt'>[]
  readonly selectedId: string | null
  readonly onSelect: (profileId: string) => void
  readonly search: string
  readonly onSearch: (value: string) => void
  readonly showArchived: boolean
  readonly onShowArchived: (value: boolean) => void
  readonly onCreate: (harnessId: string) => void
  readonly draft: ProfileDraftStore | null
  readonly onSave: () => void
  readonly onDiscard: () => void
  readonly beforeLeave?: 'saved' | 'confirm'
  /** Category buckets: the component renders only non-empty buckets. */
  readonly categoryContent: Readonly<Record<string, ReactNode>>
  readonly offline?: boolean
  readonly conflictBanner?: ReactNode
}

export function filterProfiles(
  profiles: ManagementViewProps['profiles'],
  search: string,
  showArchived: boolean,
): ManagementViewProps['profiles'] {
  const needle = search.trim().toLowerCase()
  return profiles.filter((profile) => {
    if (!showArchived && profile.archivedAt !== null) return false
    if (!needle) return true
    return profile.displayName.toLowerCase().includes(needle)
      || profile.harnessId.toLowerCase().includes(needle)
  })
}

export function ProfileManagementView(props: ManagementViewProps): ReactNode {
  const visible = filterProfiles(props.profiles, props.search, props.showArchived)
  const groups = groupByHarness(visible)
  const categories = Object.entries(props.categoryContent).filter(([, node]) => node !== null)
  return (
    <div data-profile-manager="" style={{ display: 'flex', gap: 12 }}>
      <nav data-profile-nav="" style={{ minWidth: 180 }}>
        <Input
          aria-label="搜索预设"
          value={props.search}
          onChange={(event) => props.onSearch(event.target.value)}
        />
        <label>
          <Checkbox
            aria-label="显示已归档"
            checked={props.showArchived}
            onChange={(event) => props.onShowArchived(event.target.checked)}
          />
          显示已归档
        </label>
        {props.offline && <Notice tone="warning">离线：显示最后同步列表（只读）</Notice>}
        {groups.map((group) => (
          <div key={group.harnessId} data-harness-group={group.harnessId}>
            <div role="heading" aria-level={3}>{group.harnessId} <Button
              aria-label={`在 ${group.harnessId} 新建预设`}
              onClick={() => props.onCreate(group.harnessId)}
            >+</Button></div>
            <ul>
              {group.entries.map((profile) => (
                <li key={profile.profileId}>
                  <button
                    type="button"
                    data-profile-item={profile.profileId}
                    aria-current={props.selectedId === profile.profileId}
                    onClick={() => props.onSelect(profile.profileId)}
                  >
                    {profile.displayName}
                    {profile.archivedAt !== null ? '（已归档）' : ''}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <section data-profile-detail="" style={{ flex: 1 }}>
        {props.conflictBanner}
        {props.draft === null ? (
          <p>选择一个预设</p>
        ) : (
          <>
            <h2>{props.draft.profile.displayName}</h2>
            <p>
              {props.draft.profile.harnessId} · 修订 {props.draft.profile.currentRevision}
              {props.draft.dirty ? ' · 有未保存更改' : ''}
            </p>
            {categories.map(([category, node]) => (
              <section key={category} data-category={category}>
                <h3>{category}</h3>
                {node}
              </section>
            ))}
            {props.draft.dirty && (
              <div data-unsaved-bar="">
                <span>有未保存更改</span>
                <Button data-discard="" onClick={props.onDiscard}>放弃</Button>
                <Button data-save="" onClick={props.onSave}>保存</Button>
              </div>
            )}
            {props.draft.saveError && <Notice tone="danger">{props.draft.saveError}</Notice>}
          </>
        )}
      </section>
    </div>
  )
}

/** Leave-guard answer for the router/host: unsaved drafts ask, saved/clean
 * pages leave silently (PM04).  The two confirm semantics (leave vs. switch)
 * stay separate — switching profiles never asks about overlay clearing. */
export function beforeLeave(draft: ProfileDraftStore | null): 'allow' | 'ask' {
  return draft !== null && draft.dirty ? 'ask' : 'allow'
}
