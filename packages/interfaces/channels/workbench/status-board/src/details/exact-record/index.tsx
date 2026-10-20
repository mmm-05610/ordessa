import { useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react'
import { Button, Input, Select, Textarea } from '@ordessa/ui'
import type { QueryClient } from '@ordessa/system-access-client'
import type { ExactQueryAccess, ExactQueryDefinition } from '../../contracts/exact-query'
interface Selection { note?: string; fields?: ExactQueryDefinition['fields']; client: QueryClient; method: string; label: string; realm: string; project: string; parameters: Readonly<Record<string, unknown>> }
function QueryResult({ selected, open }: { selected: Selection; open: () => void }) {
  const state = useSyncExternalStore(selected.client.subscribe, selected.client.getSnapshot)
  return <section><h2>精确查询结果</h2><p className="note">{selected.realm} / {selected.project} · {selected.label}</p><div role="status">{state.refreshing ? '正在读取' : state.stale ? state.result?.kind === 'Refused' ? '查询被拒绝；不存在或 owner 不可用会返回错误，不是空成功' : '查询结果未知或数据已过期' : '已读取原记录'}</div>{state.result && state.result.kind !== 'Accepted' && <p className="note">{state.result.reason}</p>}{state.lastUpdated && <p className="note">最后成功读取 {new Date(state.lastUpdated).toLocaleString()}</p>}{state.data && <Button onClick={open}>查看原记录详情</Button>}<Button busy={state.refreshing} disabled={state.refreshing} onClick={() => void selected.client.refresh()}>刷新此查询</Button></section>
}
function RecordDetail({ selected, back }: { selected: Selection; back: () => void }) {
  const state = useSyncExternalStore(selected.client.subscribe, selected.client.getSnapshot)
  const record = state.data?.data
  const fields = record !== null && typeof record === 'object' && !Array.isArray(record) ? record as Record<string, unknown> : undefined
  return <article><Button className="back" onClick={back}>← 返回精确查询</Button><h1>{selected.label}</h1><p className="note">{selected.realm} / {selected.project}</p><p className="note">以下为权威原记录；查询成功不等于执行完成、批准或验收通过。</p>{state.stale && <div className="availability">数据已过期，保留最后成功读取。{state.result?.kind === 'Refused' ? '最新查询被拒绝。' : '最新结果未知。'}</div>}<p className="note">最后成功读取 {state.lastUpdated ? new Date(state.lastUpdated).toLocaleString() : '尚无'}</p>{selected.note && <p className="note">{selected.note}</p>}<section><h2>已读取的精确参数</h2><pre>{JSON.stringify(selected.parameters, null, 2)}</pre></section>{fields && selected.fields?.filter(field => field.key in fields).map(field => <section key={field.key}><h2>{field.label}</h2><pre>{typeof fields[field.key] === 'string' ? fields[field.key] as string : JSON.stringify(fields[field.key], null, 2)}</pre></section>)}<section><h2>原返回记录</h2><pre data-testid="exact-record">{JSON.stringify(state.data, null, 2)}</pre></section><p className="note">此记录不创建 Work，也不提供可信确认。方法、依据、证据等仅按原记录已有字段显示。</p><Button busy={state.refreshing} disabled={state.refreshing} onClick={() => void selected.client.refresh()}>刷新此记录</Button></article>
}
export function ExactRecords({ access }: { access: ExactQueryAccess }) {
  const [realm, setRealm] = useState(''), [project, setProject] = useState(''), [method, setMethod] = useState(access.queries[0]?.method ?? ''), [input, setInput] = useState(''), [selected, setSelected] = useState<Selection>(), [detail, setDetail] = useState(false), [error, setError] = useState(''), [busy, setBusy] = useState(false)
  const guard = useRef(false), panel = useRef<HTMLDivElement>(null), position = useRef(0)
  useLayoutEffect(() => { const main = panel.current?.closest('main'); if (main) main.scrollTop = detail ? 0 : position.current }, [detail])
  const definition = access.queries.find(q => q.method === method)
  async function read() {
    if (guard.current) return
    guard.current = true; setBusy(true); setError('')
    try {
      const parameter = definition?.parameter
      const value = parameter?.json ? JSON.parse(input) : input.trim()
      if (parameter && (!input.trim() || (parameter.json && (value === null || typeof value !== 'object' || Array.isArray(value))))) throw Error('请填写精确 ID 或引用对象 JSON')
      const parameters = parameter ? { [parameter.key]: value } : {}
      const client = access.createQuery(method, { realm_id: realm.trim(), project_id: project.trim() }, parameters)
      setSelected({ client, method, label: definition!.label, fields: definition!.fields, note: definition!.note, realm: realm.trim(), project: project.trim(), parameters })
      await client.refresh()
    } catch (e) { setError(e instanceof SyntaxError ? '引用 JSON 格式无效' : (e as Error).message) }
    finally { guard.current = false; setBusy(false) }
  }
  return <div ref={panel} className="exact-queries">{detail && selected ? <RecordDetail selected={selected} back={() => setDetail(false)}/> : <><section><h2>Engineering 精确记录查询</h2><p className="note">按已知 ID 或完整引用读取。没有工作列表或目标结构查询；这里不会生成 Work。</p><label>Realm ID<Input value={realm} onChange={e => setRealm(e.target.value)}/></label><label>Project ID<Input value={project} onChange={e => setProject(e.target.value)}/></label><label>查询<Select aria-label="查询" value={method} onChange={e => { setMethod(e.target.value); setInput('') }}>{access.queries.map(q => <option key={q.method} value={q.method}>{q.label}</option>)}</Select></label>{definition?.parameter && <label>{definition.parameter.label}{definition.parameter.json ? <Textarea value={input} onChange={e => setInput(e.target.value)} rows={5}/> : <Input value={input} onChange={e => setInput(e.target.value)}/>}</label>}{definition?.note && <p className="note">{definition.note}</p>}<Button busy={busy} disabled={busy || !realm.trim() || !project.trim()} onClick={() => void read()}>读取精确记录</Button><p role="alert">{error}</p></section>{selected && <QueryResult selected={selected} open={() => { position.current = panel.current?.closest('main')?.scrollTop ?? 0; setDetail(true) }}/>}</>}</div>
}
