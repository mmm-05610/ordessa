// migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (src/settings.tsx, verbatim)
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ELIGIBILITY_GLYPHS, ELIGIBILITY_LABELS, STATE_GLYPHS, STATE_LABELS, ModelProviderWireError } from '../../contracts/index'
import type { ApiKeyImportResult, Eligibility, ModelOfferingView, ModelProviderService, ProviderConfigView, ProbeAnswer } from '../../contracts/index'
import { styles, tokens } from './styles'

interface Draft {
  displayName: string
  harness: string
  provider: string
  credentialId: string
  baseUrl: string
  modelIds: string
  protocol: string
  protocolExplicit: boolean
}

const EMPTY_DRAFT: Draft = { displayName: '', harness: 'pi', provider: '', credentialId: '', baseUrl: '', modelIds: '', protocol: '', protocolExplicit: false }
const PROTOCOLS = ['openai-chat', 'openai-responses', 'anthropic-messages', 'gemini-generate']
type KeyAttempt = { requestId: string; harnessId: string; generation: number; state: ApiKeyImportResult['state'] | 'pending' }
function validImport(result: ApiKeyImportResult, operationId: string): boolean {
  if (!result || result.operationId !== operationId) return false
  if (result.state === 'imported') return result.kind === 'api-key' && typeof result.credentialId === 'string'
    && !!result.credentialId && result.credentialId.length <= 256 && !/[\x00-\x1f\x7f]/.test(result.credentialId)
    && Object.keys(result).sort().join(',') === 'credentialId,kind,operationId,state'
  return ['unknown', 'not-found', 'refused'].includes(result.state)
    && Object.keys(result).sort().join(',') === 'operationId,state'
}

/** Settings has catalogue facts, without a specific native session's apply
 * and readback evidence. Manual availability and saved records cannot prove
 * same-session readiness; that verdict belongs to the submission flow. */
function catalogueEligibility(model: ModelOfferingView): Eligibility {
  return model.eligibility === 'unsupported' || model.eligibility === 'error' ? model.eligibility : 'unknown'
}

export function ModelProviderSettings({ service }: { service: ModelProviderService }) {
  const [configs, setConfigs] = useState<ProviderConfigView[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT)
  const [feedback, setFeedback] = useState<{ kind: 'saved' | 'probe' | 'error'; text: string } | null>(null)
  const [narrow, setNarrow] = useState(false)
  const [keyAttempt, setKeyAttempt] = useState<KeyAttempt | null>(null)
  const [keyBusy, setKeyBusy] = useState(false)
  const [saveBusy, setSaveBusy] = useState(false)
  const keyInput = useRef<HTMLInputElement | null>(null)
  const bindKeyInput = useCallback((input: HTMLInputElement | null) => {
    if (!input && keyInput.current) keyInput.current.value = ''
    keyInput.current = input
  }, [])
  const generation = useRef(0)
  const mounted = useRef(true)
  const draftRef = useRef(draft)
  const keyAttemptRef = useRef<KeyAttempt | null>(null)
  const keyBusyRef = useRef(false)
  const saveBusyRef = useRef(false)
  const saveAttempt = useRef<{ body: Record<string, unknown>; edit?: { id: string; version: number }; fingerprint: string; unknown: boolean } | null>(null)
  draftRef.current = draft
  const listRef = useRef<HTMLDivElement | null>(null)
  const detailReturnFocus = useRef<HTMLElement | null>(null)

  useEffect(() => {
    // Load the saved list from the local Server (a wire read, not a probe).
    // No outbound request happens here - FR-STATE-3.
    mounted.current = true
    let live = true
    service.list().then(rows => { if (live) setConfigs(rows) }).catch(() => { if (live) setConfigs([]) })
    const input = keyInput.current
    return () => { live = false; mounted.current = false; generation.current += 1; if (input) input.value = ''; if (keyInput.current) keyInput.current.value = '' }
  }, [service])

  const resetDraft = (next: Draft = EMPTY_DRAFT) => {
    generation.current += 1
    if (keyInput.current) keyInput.current.value = ''
    keyAttemptRef.current = null; setKeyAttempt(null)
    draftRef.current = next; setDraft(next)
    setFeedback(null)
    // An uncertain save cannot be replaced with a fresh mutation identity.
    if (!saveAttempt.current?.unknown && !saveBusyRef.current) saveAttempt.current = null
  }
  const changeDraft = (field: Exclude<keyof Draft, 'protocolExplicit'>, value: string) => {
    generation.current += 1
    if ((field === 'harness' || field === 'provider') && keyInput.current) keyInput.current.value = ''
    const next = { ...draftRef.current, [field]: value,
      protocolExplicit: draftRef.current.protocolExplicit || field === 'protocol' || field === 'baseUrl' }
    draftRef.current = next; setDraft(next)
  }
  const importKey = async (query = false) => {
    if (keyBusyRef.current) return
    const previous = keyAttemptRef.current
    if (query ? !previous || previous.state !== 'unknown' : previous?.state === 'unknown' || previous?.state === 'pending') return
    const apiKey = query ? '' : keyInput.current?.value ?? ''
    if (!query && (!apiKey || new TextEncoder().encode(apiKey).length > 8000 || /[\x00-\x1f\x7f]/.test(apiKey))) {
      if (keyInput.current) keyInput.current.value = ''
      setFeedback({ kind: 'error', text: 'API Key 不能为空或包含控制字符，长度须在允许范围内。' }); return
    }
    const attempt: KeyAttempt = query ? { ...previous!, state: 'pending' }
      : { requestId: `key_${globalThis.crypto.randomUUID()}`, harnessId: draftRef.current.harness, generation: generation.current, state: 'pending' }
    keyBusyRef.current = true; setKeyBusy(true)
    keyAttemptRef.current = attempt; setKeyAttempt(attempt)
    if (keyInput.current) keyInput.current.value = ''
    const current = () => mounted.current && keyAttemptRef.current?.requestId === attempt.requestId
    try {
      const result = query ? await service.queryApiKeyImport(attempt.requestId, attempt.harnessId)
        : await service.importApiKey(attempt.requestId, attempt.harnessId, apiKey)
      if (!current()) return
      if (!validImport(result, `key-import:${attempt.requestId}`)) throw new ModelProviderWireError('Unknown', 'modelProvider.importApiKey')
      const settled = { ...attempt, state: result.state }
      keyAttemptRef.current = settled; setKeyAttempt(settled)
      if (result.state === 'imported') {
        if (generation.current !== attempt.generation || draftRef.current.harness !== attempt.harnessId) {
          setFeedback({ kind: 'error', text: '凭据已导入，但表单已改变；未绑定到当前配置。' }); return
        }
        const next = { ...draftRef.current, credentialId: result.credentialId! }
        draftRef.current = next; setDraft(next)
        setFeedback({ kind: 'saved', text: 'API Key 已存入系统密钥库；当前表单仅保留凭据引用。' })
      } else setFeedback({ kind: 'error', text: result.state === 'unknown' ? '导入结果未知。请点击查询结果；不会再次导入。'
        : result.state === 'not-found' ? '未找到导入操作；未绑定凭据。' : '导入被拒绝。请检查系统密钥库是否可用并已解锁。' })
    } catch (error) {
      if (!current()) return
      const state = !query && error instanceof ModelProviderWireError && error.outcome === 'Refused' ? 'refused' : 'unknown'
      const settled: KeyAttempt = { ...attempt, state }
      keyAttemptRef.current = settled; setKeyAttempt(settled)
      setFeedback({ kind: 'error', text: state === 'unknown' ? '导入结果未知。请点击查询结果；不会再次导入。'
        : '导入被拒绝。请检查系统密钥库是否可用并已解锁。' })
    } finally {
      keyBusyRef.current = false
      if (mounted.current) setKeyBusy(false)
    }
  }

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
    } catch {
      setFeedback({ kind: 'error', text: '探测失败，请检查端点、凭据和连接后重试。' })
    }
  }, [service])

  const save = useCallback(async () => {
    if (saveBusyRef.current) return
    if (saveAttempt.current?.unknown) {
      setFeedback({ kind: 'error', text: '保存结果未知，已保留请求身份。请核实已保存配置；不会重复保存。' }); return
    }
    if (keyBusyRef.current || keyAttemptRef.current?.state === 'unknown') {
      setFeedback({ kind: 'error', text: '请先查询并确认 API Key 导入结果，再保存配置。' }); return
    }
    const capture = draftRef.current
    const writeProtocol = !!capture.protocol && (!selected || capture.protocolExplicit)
    const modelIds = [...new Set(capture.modelIds.split(/[\s,，]+/).filter(Boolean))]
    if (!modelIds.length || modelIds.some(id => id.length > 256 || /[\x00-\x1f\x7f]/.test(id))
        || !capture.harness.trim() || !capture.provider.trim() || (!selected && !PROTOCOLS.includes(capture.protocol))) {
      setFeedback({ kind: 'error', text: '请填写供应商、Harness 和至少一个模型 ID，并为新配置明确选择协议。' }); return
    }
    if (writeProtocol && (!PROTOCOLS.includes(capture.protocol) || !capture.baseUrl.trim())) {
      setFeedback({ kind: 'error', text: '请选择有效协议并填写对应 Base URL。' }); return
    }
    const capturedGeneration = generation.current
    saveBusyRef.current = true; setSaveBusy(true)
    try {
      const body = {
        displayName: capture.displayName || '未命名配置',
        ...(!selected ? { harness: capture.harness, provider: capture.provider } : {}),
        credentialId: capture.credentialId || null,
        configuration: [{ controlId: 'baseUrl', value: capture.baseUrl }],
        models: modelIds.map(modelId => {
          const existing = selected?.models.find(model => model.modelId === modelId)
          return { modelId, displayName: existing?.displayName ?? modelId,
            availability: existing?.availability ?? (existing ? 'unknown' as const : 'available' as const),
            unavailableReason: existing?.unavailableReason ?? null }
        }),
        ...(capture.baseUrl ? { provenance: { baseUrl: capture.baseUrl, fieldsSource: 'manual' } } : {}),
        ...(writeProtocol ? { protocols: [capture.protocol], endpoints: { [capture.protocol]: capture.baseUrl } } : {}),
      }
      const edit = selected ? { id: selected.id, version: selected.version } : undefined
      const fingerprint = JSON.stringify([body, edit])
      if (!saveAttempt.current || saveAttempt.current.fingerprint !== fingerprint)
        saveAttempt.current = { body: { ...body, requestId: `save_${globalThis.crypto.randomUUID()}` }, edit, fingerprint, unknown: false }
      const attempt = saveAttempt.current
      const stored = await service.save(attempt.body, attempt.edit)
      if (!mounted.current) return
      setConfigs((current) => [...current.filter((item) => item.id !== stored.id), stored])
      if (generation.current !== capturedGeneration) return
      setSelectedId(stored.id)
      setAdding(false)
      saveAttempt.current = null
      // A save is a record fact: the state stays `saved` - never "enabled".
      setFeedback({ kind: 'saved', text: `${STATE_LABELS.saved}；要在会话下轮使用仍需适配器证明` })
    } catch (error) {
      const unknown = !(error instanceof ModelProviderWireError && error.outcome === 'Refused')
      if (saveAttempt.current && unknown) saveAttempt.current.unknown = true
      if (mounted.current && generation.current === capturedGeneration) setFeedback({ kind: 'error', text: unknown
        ? '保存结果未知，已保留请求身份。请核实已保存配置；不会重复保存。' : '保存被拒绝；草稿已保留，请检查字段和版本后重试。' })
    } finally {
      saveBusyRef.current = false
      if (mounted.current) setSaveBusy(false)
    }
  }, [selected, service])

  const onKeyDown = useCallback((event: React.KeyboardEvent) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const index = configs.findIndex((item) => item.id === selectedId)
      const next = event.key === 'ArrowDown'
        ? Math.min(configs.length - 1, index < 0 ? 0 : index + 1)
        : Math.max(0, index < 0 ? 0 : index - 1)
      if (configs[next]) { resetDraft(); setAdding(false); setSelectedId(configs[next].id) }
    }
    if (event.key === 'Escape' && selectedId !== null) {
      const returning = detailReturnFocus.current
      resetDraft()
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
            onClick={() => { resetDraft(); setSelectedId(config.id); setAdding(false) }}
            onFocus={() => detailReturnFocus.current = null}>
            <span aria-hidden="true">{STATE_GLYPHS[config.state]}</span>
            <span>{config.displayName}</span>
            <span style={styles.mutedText}>{config.harness ?? '共享'}</span>
          </div>
        ))}
        <button onClick={() => { resetDraft(); setAdding(true); setSelectedId(null) }} data-testid="add-config">
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
                      <span style={styles.warningText}>
                        <span aria-hidden="true">{ELIGIBILITY_GLYPHS[catalogueEligibility(model)]}</span>{' '}
                        {ELIGIBILITY_LABELS[catalogueEligibility(model)]}
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
                      resetDraft({
                        displayName: selected.displayName, harness: selected.harness ?? 'pi',
                        provider: selected.provider, credentialId: selected.credentialId ?? '',
                        baseUrl: (selected.protocols?.length === 1 ? selected.endpoints?.[selected.protocols[0]] : undefined) ?? selected.provenance?.baseUrl ?? '',
                        modelIds: selected.models.map(model => model.modelId).join(', '),
                        protocol: selected.protocols?.length === 1 ? selected.protocols[0] : '',
                        protocolExplicit: false,
                      })
                      setAdding(true)
                    }}>编辑</button>
                </div>
              </>
            )}
            {adding && (
              <div>
                <label>名称 <input value={draft.displayName} aria-label="名称"
                  onChange={(e) => changeDraft('displayName', e.target.value)} /></label>
                <label>Harness <input value={draft.harness} aria-label="Harness" disabled={selected !== null}
                  onChange={(e) => changeDraft('harness', e.target.value)} /></label>
                <label>供应商 <input value={draft.provider} aria-label="供应商" disabled={selected !== null}
                  onChange={(e) => changeDraft('provider', e.target.value)} /></label>
                <label>凭据引用 <input value={draft.credentialId} aria-label="凭据引用"
                  onChange={(e) => changeDraft('credentialId', e.target.value)} /></label>
                <label>API Key <input type="password" autoComplete="off" aria-label="API Key" ref={bindKeyInput} /></label>
                <button style={styles.button} data-testid="import-api-key" disabled={keyBusy || keyAttempt?.state === 'unknown'}
                  onClick={() => { void importKey() }}>导入 API Key</button>
                {keyAttempt?.state === 'unknown' && <button style={styles.button} data-testid="query-api-key-import" disabled={keyBusy}
                  onClick={() => { void importKey(true) }}>查询导入结果</button>}
                {keyAttempt?.state === 'unknown' && <p>导入操作：key-import:{keyAttempt.requestId}</p>}
                <label>Base URL <input value={draft.baseUrl} aria-label="Base URL"
                  onChange={(e) => changeDraft('baseUrl', e.target.value)} /></label>
                <label>协议 <select value={draft.protocol} aria-label="协议" onChange={e => changeDraft('protocol', e.target.value)}>
                  <option value="">明确选择协议</option>
                  {PROTOCOLS.map(protocol => <option key={protocol} value={protocol}>{protocol}</option>)}
                </select></label>
                <label>模型 ID <input value={draft.modelIds} aria-label="模型 ID" placeholder="多个模型用逗号分隔"
                  onChange={e => changeDraft('modelIds', e.target.value)} /></label>
                <p style={styles.mutedText}>手动声明模型和协议；保存不会探测网络，实际会话支持由 Harness 核验。</p>
                <button style={styles.button} data-testid="save-config" disabled={saveBusy || keyBusy || keyAttempt?.state === 'unknown'} onClick={() => { void save() }}>
                  保存修改
                </button>
                <button style={styles.button} data-testid="cancel-config" onClick={() => { resetDraft(); setAdding(false) }}>取消</button>
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
