/**
 * Settings → Profile view (US1, PV-08, ux.md §1).
 * Lists only REAL registered facet providers; provider settings sections load
 * through the contributions registry (no section → no empty card); the
 * Agent-autoswitch switch does not exist in v1 (PS03) — nothing to fake.
 */
import type { ReactNode } from 'react'
import { Button, Checkbox, Notice, Select } from '@ordessa/ui'
import type { MechanismPolicyStore } from './stores'

export interface ProfileSettingsSectionProps {
  readonly id: string
  readonly title: string
  readonly render: () => ReactNode
}

export interface ProfileSettingsViewProps {
  readonly realms: readonly string[]
  readonly realm: string
  readonly onRealmChange: (realm: string) => void
  readonly store: MechanismPolicyStore
  /** facetId → display label (from describeFacets); unregistered facets never
   * render as grey placeholders (PS01/ux.md §1). */
  readonly facetLabels: Readonly<Record<string, string>>
  readonly onReload: () => void
  /** Provider-owned settings sections (id/title/render), already scoped. */
  readonly sections: readonly ProfileSettingsSectionProps[]
}

export function ProfileSettingsView(props: ProfileSettingsViewProps): ReactNode {
  const { policy } = props.store.state
  return (
    <div data-profile-settings="">
      <div data-profile-settings-realm="">
        <span>服务：</span>
        <Select
          aria-label="服务域"
          value={props.realm}
          onChange={(event) => props.onRealmChange(event.target.value)}
        >
          {props.realms.map((realm) => (
            <option key={realm} value={realm}>{realm}</option>
          ))}
        </Select>
      </div>

      {props.store.state.error && (
        <Notice tone="danger">{props.store.state.error}</Notice>
      )}

      <h3>配置提供者</h3>
      {policy === null ? (
        <p>{props.store.state.loading ? '加载中…' : '尚未加载'}</p>
      ) : (
        <ul data-profile-facet-list="">
          {Object.keys(props.facetLabels).map((facetId) => {
            const enabled = policy.facetEnabled[facetId] ?? true
            return (
              <li key={facetId} data-facet-row={facetId}>
                <label>
                  <Checkbox
                    aria-label={`启用 ${props.facetLabels[facetId] ?? facetId}`}
                    checked={enabled}
                    onChange={(event) => {
                      void props.store.setFacetEnabled(
                        props.realm, facetId, event.target.checked,
                        (impact) => window.confirm(describeImpact(impact)),
                      )
                    }}
                  />
                  {props.facetLabels[facetId] ?? facetId}
                </label>
                <label>
                  <Checkbox
                    aria-label={`允许修改 ${props.facetLabels[facetId] ?? facetId} 的临时覆盖`}
                    checked={policy.allowUserOverrideWrites[facetId] ?? policy.allowUserOverrideWritesGlobal}
                    onChange={(event) => {
                      void props.store.setOverrideWrites(props.realm, facetId, event.target.checked)
                    }}
                  />
                  允许临时覆盖
                </label>
              </li>
            )
          })}
        </ul>
      )}

      <h3>会话配置修改</h3>
      {policy && (
        <label>
          <Checkbox
            aria-label="允许用户新增或修改临时覆盖"
            checked={policy.allowUserOverrideWritesGlobal}
            onChange={(event) => {
              void props.store.setOverrideWrites(props.realm, null, event.target.checked)
            }}
          />
          允许用户新增/修改临时覆盖
        </label>
      )}
      <p>说明：关闭后仍可查看和清除既有覆盖，也不绕过运行权限。</p>

      <Button data-profile-open-manager="" onClick={() => { /* wired by host */ }}>
        管理配置预设
      </Button>

      <h3>提供者设置区</h3>
      {props.sections.length === 0 ? null : (
        props.sections.map((section) => (
          <section key={section.id} data-profile-section={section.id}>
            <h4>{section.title}</h4>
            {section.render()}
          </section>
        ))
      )}
      {props.sections.length === 0 && null}
    </div>
  )
}

export function describeImpact(impact: {
  disabling: Readonly<Record<string, { profilesWithValues: number; sessionsWithOverlays: number }>>
}): string {
  for (const [facetId, counts] of Object.entries(impact.disabling)) {
    return `禁用 ${facetId} 将影响 ${counts.profilesWithValues} 个预设与 ${counts.sessionsWithOverlays} 个会话的覆盖；数据保留。`
  }
  return '禁用后数据保留。'
}

/** Reload button for the offline/error path (PM02/ux.md). */
export function SettingsReload({ onReload }: { onReload: () => void }): ReactNode {
  return <Button onClick={onReload}>重新加载</Button>
}
