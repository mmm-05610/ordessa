import { useState } from 'react'
import { Button } from '@ordessa/ui'
import type { WorkRecord } from '../contracts/client'
import type { BoardStore } from '../state/store'
export function Detail({ work, revision, store }: { work: WorkRecord; revision: string; store: BoardStore }) {
  const [busy, setBusy] = useState(false), [message, setMessage] = useState('')
  async function confirm() { if (busy) return; setBusy(true); try { await store.confirm(work.id, work.version, work.scope, revision); setMessage('权威确认已返回，请检查更新记录') } catch (e) { setMessage((e as Error).message) } finally { setBusy(false) } }
  return <article><p className="eyebrow">工作详情 · {work.status}</p><h1>{work.title}</h1><p className="note">{work.scope || '无目录绑定'} · 版本 {work.version}</p><section><h2>变化</h2><p>{work.change}</p></section><section><h2>绑定方法 · {work.method?.name ?? '未绑定'}</h2>{work.method?.steps.length ? <ol>{work.method.steps.map(s => <li key={s.id}>{s.label} <small>{s.status}</small></li>)}</ol> : <p className="empty">没有已记录的方法步骤</p>}</section>{(['basis','review','approval','execution','evidence'] as const).map((key,i) => <section key={key}><h2>{['依据','审核','批准','执行','证据'][i]}</h2>{work[key].length ? <ul>{work[key].map((s,j) => <li key={j}>{s}</li>)}</ul> : <p className="empty">未记录</p>}</section>)}<section><h2>可信确认</h2><p className="note">绑定此版本、范围与快照。内容变化会拒绝旧确认。</p><Button disabled={!store.source?.confirm || busy} busy={busy} onClick={confirm}>确认版本 {work.version}</Button>{!store.source?.confirm && <p className="empty">后端可信确认未接通，当前不可用</p>}<p role="status">{message}</p></section></article>
}
