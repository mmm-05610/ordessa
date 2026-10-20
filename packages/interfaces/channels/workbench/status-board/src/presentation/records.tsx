import { Button } from '@ordessa/ui'
import type { WorkRecord } from '../contracts/client'
export function WorkRows({ works, open }: { works: readonly WorkRecord[]; open: (id: string) => void }) {
  return <div className="work-rows">{works.map(w => <Button key={w.id} className="work-row" onClick={() => open(w.id)}><span className="row-title">{w.title}<span aria-hidden="true">↗</span></span><small>{w.scope || '无目录绑定'} · {w.status}</small></Button>)}</div>
}
export function Empty({ children }: { children: React.ReactNode }) { return <p className="empty">{children}</p> }
