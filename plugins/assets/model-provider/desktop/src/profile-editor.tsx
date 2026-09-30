import { useEffect, useState } from 'react'
import type { ProfileFacetEditorProps } from '@extensions/ordessa.profile-api/contract.js'
import type { ModelProviderService, ProviderConfigView } from '../../contracts/index'

/** Model-provider owns this editor; Profile only loads it through C7. */
export function ModelProfileEditor({ service, ...props }: ProfileFacetEditorProps & { service: ModelProviderService }) {
  const [configs, setConfigs] = useState<ProviderConfigView[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [retry, setRetry] = useState(0)
  const [candidate, setCandidate] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    setLoading(true); setError(null)
    void service.list().then(rows => { if (live) setConfigs(rows.filter(row => !row.archivedAt
      && (row.harness === null || row.harness === props.target.harnessId))) })
      .catch(e => { if (live) setError(String(e)) }).finally(() => { if (live) setLoading(false) })
    return () => { live = false }
  }, [service, props.target.harnessId, retry])
  const raw = props.items.find(i => i.itemId === 'choice')?.value
  const choice = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {}
  const providerId = candidate ?? (typeof choice.providerConfigId === 'string' ? choice.providerConfigId : '')
  const provider = configs.find(c => c.id === providerId)
  const modelId = candidate === null && typeof choice.modelId === 'string' ? choice.modelId : ''
  const supportedSchema = props.schemaVersion === '1'
  const disabled = !supportedSchema || loading || !!props.readOnlyReason || props.applicability === 'unsupported'
  return <section aria-label="默认模型配置">
    <h3>默认模型</h3>
    {!supportedSchema && <p role="alert">此版本的模型配置只读；请升级编辑器。</p>}
    {error && <p role="alert">{error}<button onClick={() => setRetry(n => n + 1)}>重试供应商加载</button></p>}
    <label>供应商 <select aria-label="预设供应商" disabled={disabled} value={providerId}
      onChange={e => setCandidate(e.target.value)}>
      <option value="">请选择</option>
      {providerId && !provider && <option value={providerId} disabled>已保存的供应商不可用</option>}
      {configs.map(c => <option key={c.id} value={c.id}>{c.displayName}</option>)}
    </select></label>
    <label>模型 <select aria-label="预设模型" disabled={disabled || !provider} value={modelId}
      onChange={e => {
        if (!provider || !e.target.value || !provider.models.some(m => m.modelId === e.target.value && m.availability !== 'unavailable')) return
        props.onPatch([{ facetId: props.facetId, itemId: 'choice', op: 'set',
          value: { harnessId: props.target.harnessId, providerConfigId: provider.id, modelId: e.target.value } }])
        setCandidate(null)
      }}>
      <option value="">请选择</option>
      {modelId && !provider?.models.some(m => m.modelId === modelId) && <option value={modelId} disabled>已保存的模型不可用</option>}
      {provider?.models.map(m => <option key={m.modelId} value={m.modelId} disabled={m.availability === 'unavailable'}>{m.displayName ?? m.modelId}</option>)}
    </select></label>
    <button disabled={disabled || raw === undefined} onClick={() => {
      setCandidate(null); props.onPatch([{ facetId: props.facetId, itemId: 'choice', op: 'unset' }])
    }}>清除预设模型</button>
    {props.readOnlyReason && <p>{props.readOnlyReason}</p>}
  </section>
}
