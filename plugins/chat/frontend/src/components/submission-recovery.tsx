import { useEffect, useState } from 'react'
import type { createSubmissionRecoveryClient, FrontendSubmissionKey, FrontendSubmissionRecord } from '@extensions/ordessa.agent-contracts/contract.js'

export type SubmissionRecovery = ReturnType<typeof createSubmissionRecoveryClient>

/** Query-only recovery never changes the current editor or resends input. */
export function SubmissionRecoveryPanel({ recovery }: { recovery: SubmissionRecovery }) {
  const [records, setRecords] = useState<readonly FrontendSubmissionRecord[]>([])
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    let active = true
    void recovery.list().then(result => {
      if (!active) return
      if (result.status === 'available') setRecords(result.records)
      else setMessage('恢复记录暂不可查询。')
    })
    return () => { active = false }
  }, [recovery])
  async function refresh() {
    const result = await recovery.list()
    if (result.status === 'available') { setRecords(result.records); setMessage('') }
    else setMessage('恢复记录暂不可查询。')
  }
  async function query(key: FrontendSubmissionKey) {
    if (busy) return
    setBusy(true)
    try {
      const result = await recovery.reconcile(key)
      setMessage(result.status === 'accepted' ? '原提交已接纳。'
        : result.status === 'refused' ? '原提交已拒绝。'
        : result.status === 'unavailable' ? '原提交暂不可查询。' : '原提交结果仍未知；未重新发送。')
      const latest = await recovery.list()
      if (latest.status === 'available') setRecords(latest.records)
    } finally { setBusy(false) }
  }
  return <section aria-label="提交恢复记录">
    <button type="button" disabled={busy} onClick={() => { void refresh() }}>刷新记录</button>
    {message && <p role="status">{message}</p>}
    {records.map(record => <div key={record.key.requestId}>
      <span>{record.key.requestId} · {record.results.at(-1)?.outcome ?? 'unknown'}</span>
      <button type="button" disabled={busy} onClick={() => { void query(record.key) }}>查询原提交</button>
      <details><summary>已记录事实</summary><pre>{JSON.stringify(record.results, null, 2)}</pre></details>
    </div>)}
  </section>
}
