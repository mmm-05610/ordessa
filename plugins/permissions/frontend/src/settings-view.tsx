// Presentational half of the 「权限与审批」 Settings region. It renders one
// thing: what the `permissions.policy.describe` round-trip proved — the
// strict decoder already refused anything outside the closed shape, so no
// option list, brand mode name or verdict is authored here. The Workbench
// owns the Settings page container; nothing here adds a conversation shell
// or popover (ux.md §文案和可访问性). Controls are native button/select/input
// so keyboard focus and ARIA come from the platform's C8 foundations at the
// DOM level. Needs-review rows carry no interactive control at all: a 待复核
// item can never be clicked into an allowance.
import { useSyncExternalStore } from 'react'
import {
  permissionsSettingsCopy,
  type PermissionsDecodedFacts,
  type PermissionsRegionState,
  type PermissionsSettingsRegion,
} from './settings-region'
import { ceilingRecordIsTrusted, ruleSourceSummaries } from './contract'

export interface PermissionsSettingsSectionViewProps { region: PermissionsSettingsRegion }

export function PermissionsSettingsSectionView({ region }: PermissionsSettingsSectionViewProps) {
  const snapshot = useSyncExternalStore(region.subscribe, region.getSnapshot, region.getSnapshot)
  const { state } = snapshot
  const sid = region.sectionId

  if (state.kind === 'absent') return null

  if (state.kind === 'provider-error') {
    return (
      <div className="permissions-settings-region" data-permissions-region="provider-error">
        <p role="alert" aria-live="assertive">
          {permissionsSettingsCopy.providerError(state.code)}
          <span className="permissions-settings-error-detail">{state.message}</span>
        </p>
        <button type="button" onClick={() => { void region.refresh() }}>重新读取</button>
      </div>
    )
  }

  const facts = state.facts
  const areas: Array<{ key: string; heading: string; body: React.ReactNode }> = [
    {
      key: 'rule-sources',
      heading: '规则来源',
      body: (
        <>
          <ul aria-label="规则来源">
            {ruleSourceSummaries(facts.ceilings, facts.intents, facts.approvals).map(source => (
              <li key={source} data-rule-source>{source}</li>
            ))}
            {facts.undecodableApprovals > 0 && (
              <li data-rule-source-unverified>
                {facts.undecodableApprovals} 条审批载荷未通过白名单校验：已按未证实处理，不作为事实呈现
              </li>
            )}
          </ul>
        </>
      ),
    },
    {
      key: 'ceilings',
      heading: '组织上限（只读）',
      body: <CeilingArea region={region} facts={facts} sid={sid} />,
    },
    {
      key: 'intents',
      heading: '用户默认意图',
      body: <IntentArea facts={facts} />,
    },
    {
      key: 'history',
      heading: '审批历史过滤',
      body: <HistoryArea region={region} snapshot={snapshot} />,
    },
  ]

  return (
    <div className="permissions-settings-region" data-permissions-region={state.kind} data-describe-ready={String(facts.ready)}>
      <p>{permissionsSettingsCopy.regionDescription}</p>
      {!facts.ready && (
        <p data-describe-not-ready role="status" aria-live="polite">{permissionsSettingsCopy.describeNotReady}</p>
      )}
      {areas.map(area => (
        <section key={area.key} data-settings-area={area.key} aria-labelledby={`${sid}-${area.key}`}>
          <h3 id={`${sid}-${area.key}`}>{area.heading}</h3>
          {area.body}
        </section>
      ))}
      {snapshot.lastCeilingOutcome !== undefined && (
        <p role="status" aria-live="polite" data-ceiling-outcome="refused">
          {permissionsSettingsCopy.appliedRefusal(snapshot.lastCeilingOutcome)}
        </p>
      )}
    </div>
  )
}

function CeilingArea(props: {
  region: PermissionsSettingsRegion
  facts: PermissionsDecodedFacts
  sid: string
}) {
  const { region, facts, sid } = props
  if (facts.ceilingCount === 0) return <p data-ceiling-none>{permissionsSettingsCopy.noCeiling}</p>
  const trusted = facts.ceilings.filter(ceilingRecordIsTrusted)
  const untrusted = facts.ceilings.filter(c => !ceilingRecordIsTrusted(c))
  return (
    <>
      {untrusted.length > 0 && (
        <ul aria-label="未通过可信来源校验的记录（非可执行）">
          {untrusted.map(ceiling => (
            <li key={`u-${ceiling.policyId}@${ceiling.revision}`} data-ceiling-non-enforceable>
              {ceiling.policyId}@{ceiling.revision}｜来源：{ceiling.source}｜{permissionsSettingsCopy.ceilingNonEnforceable}
            </li>
          ))}
        </ul>
      )}
      <ul aria-label="组织上限只读摘要">
        {trusted.map(ceiling => (
          <li key={`${ceiling.policyId}@${ceiling.revision}`} data-ceiling-row>
            <span data-ceiling-digest>{ceiling.policyId}@{ceiling.revision}</span>
            <span data-ceiling-scope>作用域：{ceiling.scope}</span>
            <span data-ceiling-exposure>
              最大暴露档位：{permissionsSettingsCopy.exposureLabel[ceiling.maximumExposure] ?? ceiling.maximumExposure}
            </span>
            <span data-ceiling-entries>
              硬性拒绝：{ceiling.hardDenies.map(entry => `${entry.key}${entry.pattern ? `(${entry.pattern})` : ''}`).join('、') || '无'}
              ｜需审批：{ceiling.requireApproval.map(entry => `${entry.key}${entry.pattern ? `(${entry.pattern})` : ''}`).join('、') || '无'}
            </span>
            <span data-ceiling-source>来源：{ceiling.source}｜生效于 {ceiling.effectiveFrom}</span>
            {!facts.ready && (
              <span data-ceiling-enforceability="non-enforceable">{permissionsSettingsCopy.ceilingUnproven}</span>
            )}
            <button
              type="button"
              data-ceiling-widen
              aria-disabled="true"
              aria-describedby={`${sid}-widen-reason-${ceiling.policyId}`}
              onClick={() => { region.attemptCeilingWidening({ policyId: ceiling.policyId }) }}
            >
              放宽该上限
            </button>
            <span id={`${sid}-widen-reason-${ceiling.policyId}`} className="permissions-settings-widen-reason">
              {permissionsSettingsCopy.ceilingReadonly}
            </span>
          </li>
        ))}
      </ul>
    </>
  )
}

function IntentArea(props: { facts: PermissionsDecodedFacts }) {
  const { facts } = props
  return (
    <>
      {facts.intents.length === 0 && facts.needsReview.length === 0 && (
        <p>当前没有已登记的用户默认意图记录。</p>
      )}
      <ul aria-label="用户默认意图">
        {facts.intents.map(intent => (
          <li key={`${intent.intentId}@${intent.revision}`} data-intent-row>
            {permissionsSettingsCopy.intentRow(intent)}｜规则数：{intent.rules.length}
          </li>
        ))}
      </ul>
      {facts.needsReview.length > 0 && (
        <ul aria-label="待复核项（不放行）">
          {facts.needsReview.map(review => (
            <li key={`${review.source}@${review.index ?? 'unnumbered'}`} data-needs-review>
              {permissionsSettingsCopy.needsReview(review)}
            </li>
          ))}
        </ul>
      )}
    </>
  )
}

function HistoryArea(props: {
  region: PermissionsSettingsRegion
  snapshot: ReturnType<PermissionsSettingsRegion['getSnapshot']>
}) {
  const { region, snapshot } = props
  const { filter } = snapshot
  const statusValue = filter.status ?? 'all'
  const decisionValue = filter.decision ?? 'all'
  const sessionValue = filter.sessionId ?? 'all'
  return (
    <>
      <div className="permissions-settings-history-controls">
        <label>
          状态
          <select
            data-history-filter="status" aria-label="按状态过滤审批历史"
            value={statusValue}
            onChange={event => region.setHistoryFilter({ ...filter, status: event.target.value as typeof statusValue })}
          >
            <option value="all">全部</option>
            <option value="open">待审批</option>
            <option value="settled">已决定</option>
            <option value="invalid">已失效</option>
            <option value="unknown">结果 unknown（未证实）</option>
          </select>
        </label>
        <label>
          决定
          <select
            data-history-filter="decision" aria-label="按决定过滤审批历史"
            value={decisionValue}
            onChange={event => region.setHistoryFilter({ ...filter, decision: event.target.value as typeof decisionValue })}
          >
            <option value="all">全部</option>
            <option value="allow">允许</option>
            <option value="deny">拒绝</option>
          </select>
        </label>
        <label>
          会话
          <input
            data-history-filter="session" aria-label="按会话过滤审批历史"
            value={sessionValue}
            onChange={event => region.setHistoryFilter({ ...filter, sessionId: event.target.value })}
          />
        </label>
      </div>
      {snapshot.history.length === 0 && <p data-history-empty>没有匹配的后端审批记录</p>}
      <ul aria-label="审批历史">
        {snapshot.history.map(view => (
          <li key={view.approvalId} data-history-row data-history-id={view.approvalId}>
            {permissionsSettingsCopy.historyRow(view)}
          </li>
        ))}
      </ul>
    </>
  )
}
