import { useCallback, useEffect, useRef, useState } from 'react'
import type {
  AgentProfileCatalogClient,
  AgentProfileCatalogEntry,
  AgentProfileManifest,
} from '@extensions/ordessa.profile-api/contract.js'
import { profileSettingsCss } from './styles'

type DetailState =
  | { readonly kind: 'idle' }
  | { readonly kind: 'loading'; readonly profileId: string }
  | { readonly kind: 'ready'; readonly profileId: string; readonly manifest: AgentProfileManifest }
  | { readonly kind: 'unavailable' | 'refused' | 'unknown'; readonly profileId: string; readonly reason: string }

function refKey(ref: AgentProfileManifest['ref']): string {
  return JSON.stringify([ref.environmentNamespace, ref.profileId, ref.manifestRevision, ref.contentDigest])
}

function failureText(kind: 'unavailable' | 'refused' | 'unknown', reason: string): string {
  if (kind === 'unknown') return `读取结果未知：${reason}。不会自动重发；可手动刷新核实。`
  if (kind === 'refused') return `核心拒绝了只读请求：${reason}`
  return `Profile 只读目录不可用：${reason}`
}

/** Minimal, read-only consumer of the Agent-owned catalog and exact manifests. */
export function ConnectedProfileManager({ client }: { client: AgentProfileCatalogClient }) {
  const [entries, setEntries] = useState<readonly AgentProfileCatalogEntry[]>([])
  const [selected, setSelected] = useState<AgentProfileCatalogEntry | null>(null)
  const [detail, setDetail] = useState<DetailState>({ kind: 'idle' })
  const [catalogState, setCatalogState] = useState<'loading' | 'ready' | 'unavailable' | 'refused' | 'unknown'>('loading')
  const [message, setMessage] = useState<string | null>(null)
  const request = useRef(0)

  const refresh = useCallback(async () => {
    const sequence = ++request.current
    setCatalogState('loading')
    setMessage(null)
    setSelected(null)
    setDetail({ kind: 'idle' })
    const result = await client.list(false)
    if (sequence !== request.current) return
    if (result.kind === 'ok') {
      setEntries(result.value)
      setCatalogState('ready')
      setMessage(null)
    } else {
      setEntries([])
      setCatalogState(result.kind)
      setMessage(failureText(result.kind, result.reason))
    }
  }, [client])

  useEffect(() => {
    void refresh()
    return () => { ++request.current }
  }, [refresh])

  const open = async (entry: AgentProfileCatalogEntry) => {
    const sequence = ++request.current
    setSelected(entry)
    setDetail({ kind: 'loading', profileId: entry.profileId })
    const result = await client.read(entry.currentManifestRef)
    if (sequence !== request.current) return
    if (result.kind !== 'ok') {
      setDetail({ kind: result.kind, profileId: entry.profileId, reason: result.reason })
      return
    }
    if (refKey(result.value.ref) !== refKey(entry.currentManifestRef)) {
      setDetail({ kind: 'unknown', profileId: entry.profileId, reason: '核心返回的 ProfileRef 与请求不一致' })
      return
    }
    setDetail({ kind: 'ready', profileId: entry.profileId, manifest: result.value })
  }

  return <section aria-label="Profile 只读目录" className="profile-settings-surface">
    <style>{profileSettingsCss}</style>
    <header className="profile-reader-heading">
      <div><h2>Profile</h2><p>由 Agent 核心提供的只读目录与精确版本详情。</p></div>
      <button type="button" disabled={catalogState === 'loading'} onClick={() => { void refresh() }}>刷新</button>
    </header>
    {message && <p role="alert">{message}</p>}
    {catalogState === 'loading' && <p role="status">正在读取核心能力与目录…</p>}
    {catalogState === 'ready' && entries.length === 0 && <p role="status">核心目录当前没有可列出的 Profile。</p>}
    {catalogState === 'ready' && entries.length > 0 && <ul className="profile-reader-list">
      {entries.map(entry => <li key={`${entry.profileId}:${entry.catalogRevision}`}>
        <button type="button" aria-current={selected?.profileId === entry.profileId ? 'true' : undefined}
          onClick={() => { void open(entry) }}>
          <span>{entry.displayName}</span><small>{entry.profileId} · 目录修订 {entry.catalogRevision}</small>
        </button>
      </li>)}
    </ul>}
    {selected && <article className="profile-reader-detail" aria-label="Profile 精确版本详情">
      <h3>{selected.displayName}</h3>
      <p>清单修订 {selected.currentManifestRef.manifestRevision} · {selected.currentManifestRef.contentDigest}</p>
      {detail.kind === 'loading' && <p role="status">正在读取精确清单版本…</p>}
      {detail.kind === 'ready' && detail.profileId === selected.profileId &&
        <pre><code>{JSON.stringify(detail.manifest.content, null, 2)}</code></pre>}
      {detail.kind !== 'idle' && detail.kind !== 'loading' && detail.kind !== 'ready' &&
        <p role="alert">{failureText(detail.kind, detail.reason)}</p>}
    </article>}
    <p className="profile-reader-boundary">创建、编辑、归档、会话选择与配置应用目前不可用。</p>
  </section>
}
