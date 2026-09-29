// migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (src/settings.tsx, verbatim)
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ELIGIBILITY_GLYPHS, ELIGIBILITY_LABELS, STATE_GLYPHS, STATE_LABELS,
         type Eligibility } from '../../contracts/index'
import type { ModelProviderService, ProviderConfigView, ProbeAnswer } from '../../contracts/index'
import { styles, tokens } from './styles'

interface Draft {
  displayName: string
  harness: string
  provider: string
  credentialId: string
  baseUrl: string
}

const EMPTY_DRAFT: Draft = { displayName: '', harness: 'pi', provider: 'custom', credentialId: '', baseUrl: '' }

/** One config's eligibility verdict is evidence-carried: it can only read
 * `ready` when the adapter proved same-session next-turn applicability; a
 * probe pass is at most `reachable` and never grants readiness. */
function configEligibility(config: ProviderConfigView): Eligibility {
  if (config.models.length === 0) return 'unknown'
  return config.models.every((model) => model.availability === 'available') ? 'ready' : 'unknown'
}

export function ModelProviderSettings({ service }: { service: ModelProviderService }) {
  const [configs, setConfigs] = useState<ProviderConfigView[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT)
  const [feedback, setFeedback] = useState<{ kind: 'saved' | 'probe' | 'error'; text: string } | null>(null)
  const [narrow, setNarrow] = useState(false)
  const listRef = useRef<HTMLDivElement | null>(null)
  const detailReturnFocus = useRef<HTMLElement | null>(null)

  useEffect(() => {
    // Load the saved list from the local Server (a wire read, not a probe).
    // No outbound request happens here - FR-STATE-3.
    service.list().then(setConfigs).catch(() => setConfigs([]))
  }, [service])

  const selected = useMemo(
    () => configs.find((item) => item.id === selectedId) ?? null,
    [configs, selectedId],
  )

  const probe = useCallback(async (config: ProviderConfigView) => {
    if (!config.provenance?.baseUrl) {
      setFeedback({ kind: 'error', text: '未填写端点：请在表单中补全 Base URL 后再测试连接' })
      return
    }
    try {
      const answer: ProbeAnswer = await service.testConnection(config.provenance.baseUrl, config.credentialId)
      if (answer.status === 'reachable') {
        setFeedback({ kind: 'probe', text: `${STATE_LABELS.reachable}；这不代表当前会话可使用` })
      } else if (answer.status === 'failed' || answer.status === 'unreachable') {
        const next = answer.code === 'PROBE_AUTH_FAILED'
          ? '凭据被端点拒绝：检查或更换凭据引用后重试'
          : answer.code === 'PROBE_TIMEOUT'
            ? '端点超时：稍后重试或检查网络边界'
            : '端点不可达：确认 Base URL 与协议拼写'
        setFeedback({ kind: 'error', text: `探测失败（${answer.code ?? 'unknown'}）：${next}` })
      } else {
        setFeedback({ kind: 'probe', text: `已获取模型 ${answer.models?.length ?? 0} 个（保存后生效）` })
      }
    } catch (error) {
      setFeedback({ kind: 'error', text: `探测失败：${String(error)}` })
    }
  }, [service])

  const save = useCallback(async () => {
    try {
      const body = {
        displayName: draft.displayName || '未命名配置',
        harness: draft.harness,
        provider: draft.provider,
        credentialId: draft.credentialId || null,
        configuration: [{ controlId: 'baseUrl', value: draft.baseUrl }],
        models: selected?.models ?? [],
        provenance: draft.baseUrl ? { baseUrl: draft.baseUrl } : undefined,
      }
      const stored = selected
        ? await service.save(body, { id: selected.id, version: selected.version })
        : await service.save(body)
      setConfigs((current) => [...current.filter((item) => item.id !== stored.id), stored])
      setSelectedId(stored.id)
      setAdding(false)
      // A save is a record fact: the state stays `saved` - never "enabled".
      setFeedback({ kind: 'saved', text: `${STATE_LABELS.saved}；要在会话下轮使用仍需适配器证明` })
    } catch (error) {
      setFeedback({ kind: 'error', text: `保存失败：${String(error)}；请检查字段后重试` })
    }
  }, [draft, selected, service])

  const onKeyDown = useCallback((event: React.KeyboardEvent) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const index = configs.findIndex((item) => item.id === selectedId)
      const next = event.key === 'ArrowDown'
        ? Math.min(configs.length - 1, index < 0 ? 0 : index + 1)
        : Math.max(0, index < 0 ? 0 : index - 1)
      if (configs[next]) setSelectedId(configs[next].id)
    }
    if (event.key === 'Escape' && selectedId !== null) {
      const returning = detailReturnFocus.current
      setSelectedId(null)
      setAdding(false)
      if (returning) returning.focus()
    }
  }, [configs, selectedId])

  return (
    <div style={styles.root(narrow)} data-testid="model-provider-settings" onKeyDown={onKeyDown}>
      <div style={styles.listPane} ref={listRef} role="listbox" aria-label="Provider 配置列表">
        {configs.map((config) => (
          <div key={config.id} role="option" aria-selected={config.id === selectedId} tabIndex={0}
            style={styles.listItem(config.id === selectedId)}
            data-testid={`config-${config.id}`}
            ref={(el) => {
              if (config.id === selectedId) detailReturnFocus.current = el
            }}
            onClick={() => { setSelectedId(config.id); setAdding(false) }}
            onFocus={() => detailReturnFocus.current = null}>
            <span aria-hidden="true">{STATE_GLYPHS[config.state]}</span>
            <span>{config.displayName}</span>
            <span style={styles.mutedText}>{config.harness ?? '共享'}</span>
          </div>
        ))}
        <button onClick={() => { setAdding(true); setSelectedId(null) }} data-testid="add-config">
          + 添加配置
        </button>
      </div>

      <div style={styles.detail} data-testid="detail-pane">
        {selected === null && !adding && (
          <p style={styles.mutedText}>选择一条配置，或添加新的 Provider 配置。</p>
        )}
        {(selected !== null || adding) && (
          <div>
            <h2 style={{ margin: '4px 0' }}>{adding ? '添加配置' : selected?.displayName}</h2>
            {!adding && selected && (
              <>
                <p>
                  <span aria-hidden="true">{STATE_GLYPHS[selected.state]}</span>{' '}
                  {STATE_LABELS[selected.state]}
                  <span style={styles.mutedText}>（已保存 ≠ 可用；探测通过 ≠ 会话可使用）</span>
                </p>
                <p style={styles.mutedText}>
                  认证：{selected.credentialId ? `凭据引用 ${selected.credentialId}` : '使用已有登录'}
                  {' · '}归属：{selected.managedBy === 'harness' ? '由 Harness 管理' : '由 Ordessa 管理'}
                </p>
                <div>
                  {selected.models.map((model) => (
                    <div key={model.modelId} style={styles.modelRow}>
                      <span style={styles.modelId}>{model.modelId}</span>
                      <span style={model.eligibility === 'ready' ? undefined : styles.warningText}>
                        <span aria-hidden="true">{ELIGIBILITY_GLYPHS[model.eligibility ?? 'unknown']}</span>{' '}
                        {ELIGIBILITY_LABELS[model.eligibility ?? 'unknown']}
                        {model.eligibilityReason ? `：${model.eligibilityReason}` : ''}
                      </span>
                    </div>
                  ))}
                </div>
                <div style={{ marginTop: 12 }}>
                  <button style={styles.button} data-testid="test-connection"
                    onClick={() => { void probe(selected) }}>测试连接</button>
                  <button style={styles.button} data-testid="edit-config"
                    onClick={() => {
                      setDraft({
                        displayName: selected.displayName, harness: selected.harness ?? 'pi',
                        provider: selected.provider, credentialId: selected.credentialId ?? '',
                        baseUrl: selected.provenance?.baseUrl ?? '',
                      })
                      setAdding(true)
                    }}>编辑</button>
                </div>
              </>
            )}
            {adding && (
              <div>
                <label>名称 <input value={draft.displayName} aria-label="名称"
                  onChange={(e) => setDraft({ ...draft, displayName: e.target.value })} /></label>
                <label>Harness <input value={draft.harness} aria-label="Harness"
                  onChange={(e) => setDraft({ ...draft, harness: e.target.value })} /></label>
                <label>凭据引用 <input value={draft.credentialId} aria-label="凭据引用"
                  onChange={(e) => setDraft({ ...draft, credentialId: e.target.value })} /></label>
                <label>Base URL <input value={draft.baseUrl} aria-label="Base URL"
                  onChange={(e) => setDraft({ ...draft, baseUrl: e.target.value })} /></label>
                <p style={styles.mutedText}>预设只填充初值，不是能力证据或密钥来源。</p>
                <button style={styles.button} data-testid="save-config" onClick={() => { void save() }}>
                  保存修改
                </button>
                <button style={styles.button} onClick={() => setAdding(false)}>取消</button>
              </div>
            )}
            {feedback && (
              <p data-testid="feedback" style={feedback.kind === 'error' ? styles.errorText : styles.warningText}>
                {feedback.text}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
