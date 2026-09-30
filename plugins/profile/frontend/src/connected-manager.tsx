import { useEffect, useMemo, useRef, useState } from 'react'
import type { WirePort } from '@extensions/ordessa.contracts/contract.js'
import type { ProfileIdentityDto, ProfileServiceClient } from '@ordessa/plugin-profile-api'
import type { UiScope } from '@ordessa/ui-components/api'
import { ProfileConfigurationPane } from './configuration-pane'
import { profileCall } from './wire-client'
import { ProfileManagementView } from './management-view'
import { ProfileDraftStore } from './stores'

/** Connected management surface. No picker/application until a real runtime
 * application port is bound: persisting a preset is not applying it. */
export function ConnectedProfileManager({ client, wire, ui }: { client: ProfileServiceClient; wire: WirePort; ui?: UiScope }) {
  const [profiles, setProfiles] = useState<readonly ProfileIdentityDto[]>([])
  const [harnesses, setHarnesses] = useState<readonly string[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [harness, setHarness] = useState('')
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [search, setSearch] = useState('')
  const [showArchived, setShowArchived] = useState(false)
  const [draftGeneration, setDraftGeneration] = useState(0)
  const generation = useRef(0)
  const mounted = useRef(true)
  const saving = useRef(false)
  const current = profiles.find(p => p.profileId === selected)
  const draft = useMemo(() => current ? new ProfileDraftStore(client, current) : null, [client, current])

  async function refresh() {
    const request = ++generation.current
    setBusy(true)
    try {
      const [rows, ids] = await Promise.all([
        client.listProfiles('local', true), profileCall(wire, 'configuredHarnesses', {}),
      ])
      if (request !== generation.current) return
      setProfiles(rows)
      setHarnesses(ids as readonly string[])
      setError(null)
    } catch (e) {
      if (request === generation.current) setError(String(e))
    } finally {
      if (request === generation.current) setBusy(false)
    }
  }
  useEffect(() => {
    mounted.current = true
    void refresh()
    return () => { mounted.current = false; ++generation.current }
  }, [client, wire])

  async function mutate(action: () => Promise<unknown>) {
    setBusy(true)
    try { await action(); if (mounted.current) await refresh() }
    catch (e) { if (mounted.current) { setError(String(e)); setBusy(false) } }
  }
  const key = () => `profile-ui:${crypto.randomUUID()}`
  const mayLeave = () => !busy && (!draft?.dirty || window.confirm('放弃未保存的预设配置？'))
  async function save() {
    if (!draft || busy || saving.current) return
    saving.current = true
    setBusy(true)
    const result = await draft.save(key())
    saving.current = false
    if (!mounted.current) return
    if (result.ok) await refresh()
    else { setError(result.conflict ? '预设已被修改；本地输入已保留，请放弃后刷新再编辑。' : result.reason); setBusy(false) }
    setDraftGeneration(n => n + 1)
  }
  return <section aria-label="Profile 管理" style={{ padding: 16 }}>
    <h2>Profile</h2>
    <button disabled={busy} onClick={() => { if (mayLeave()) void refresh() }}>刷新</button>
    {error && <p role="alert">{error}</p>}
    <div>
        <label>名称 <input value={name} onChange={e => setName(e.target.value)} /></label>
        <label>Harness <select value={harness} onChange={e => setHarness(e.target.value)}>
          <option value="">请选择</option>{harnesses.map(id => <option key={id}>{id}</option>)}
        </select></label>
        <button disabled={busy || !!draft?.dirty || !harness || !name.trim()} onClick={() => void mutate(() =>
          client.createProfile(key(), { realm: 'local', harnessId: harness, displayName: name }))}>新建</button>
        {!harnesses.length && <p>后端尚未配置 Harness；不能新建预设。</p>}
    </div>
    <ProfileManagementView profiles={profiles} selectedId={selected} search={search}
      showArchived={showArchived} onSearch={setSearch} onShowArchived={setShowArchived}
      onSelect={id => { if (id !== selected && !mayLeave()) return; setSelected(id); setName(profiles.find(p => p.profileId === id)?.displayName ?? '') }}
      onCreate={id => { setHarness(id); setName('') }} draft={draft}
      onSave={() => void save()} onDiscard={() => { if (busy) return; draft?.discard(); setDraftGeneration(n => n + 1) }} categoryContent={{
        '预设配置': current && draft && ui ? <ProfileConfigurationPane key={`${current.profileId}:${current.version}`}
          client={client} profile={current} draft={draft} ui={ui} generation={draftGeneration}
          changed={() => setDraftGeneration(n => n + 1)} busy={busy} /> : null,
        '预设属性': current ? <>
          <button disabled={busy || !!draft?.dirty || !name.trim()} onClick={() => void mutate(() => client.renameProfile(key(), {
            profileId: current.profileId, expectedVersion: current.version, displayName: name }))}>保存名称</button>
          <button disabled={busy || !!draft?.dirty} onClick={() => void mutate(() => current.archivedAt
            ? client.restoreProfile(key(), { profileId: current.profileId, expectedVersion: current.version })
            : client.archiveProfile(key(), { profileId: current.profileId, expectedVersion: current.version }))}>
            {current.archivedAt ? '恢复' : '归档'}</button>
          <p>会话应用尚未接线；此处保存预设，不改变当前 Agent。</p>
        </> : null,
      }} />
  </section>
}
