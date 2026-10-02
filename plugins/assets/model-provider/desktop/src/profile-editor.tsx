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
  return <section aria-label="默认模型配置" className="mp-profile-editor">
    <style>{`.mp-profile-editor{border:1px solid #e7e7e9;border-radius:12px;padding:16px;margin:12px 0;font:13px/1.5 system-ui,sans-serif}.mp-profile-editor h3{margin:0 0 14px;font-weight:500;font-size:15px}.mp-profile-editor label{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:10px 0;border-bottom:1px solid #eeeeef}.mp-profile-editor select{min-width:0;max-width:65%;padding:7px 10px;border:1px solid #dedee1;border-radius:8px;background:#fafafa;color:inherit;font:inherit}.mp-profile-editor button{margin-top:12px;padding:6px 10px;border:1px solid #dedee1;border-radius:8px;background:#fafafa;color:inherit;font:inherit}.mp-profile-editor p{color:#77777e;font-size:12px;overflow-wrap:anywhere}.mp-profile-editor :focus-visible{outline:2px solid #548fe5;outline-offset:2px}`}</style>
    <h3>默认模型</h3>
    <style>{`.mp-profile-editor,.mp-profile-editor label{border-color:var(--ordessa-color-border,#e7e7e9)}.mp-profile-editor{color:var(--ordessa-color-text,#202123)}.mp-profile-editor select,.mp-profile-editor button{background:var(--ordessa-color-bg,#fafafa);color:var(--ordessa-color-text,#202123);border-color:var(--ordessa-color-border,#dedee1)}.mp-profile-editor p{color:var(--ordessa-color-muted,#77777e)}@media(prefers-color-scheme:dark){.mp-profile-editor{color:var(--ordessa-color-text,#eee)}.mp-profile-editor select,.mp-profile-editor button{background:var(--ordessa-color-bg,#252526);color:var(--ordessa-color-text,#eee)}}`}</style>
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
