import { Button } from '@ordessa/ui'
import type { BoardSnapshot } from '../../contracts/client'
import { Empty, WorkRows } from '../../presentation/records'
export function Structure({ data, expanded, toggle, open }: { data?: BoardSnapshot; expanded: Set<string>; toggle: (id: string) => void; open: (id: string) => void }) {
  const nodes = data?.structure ?? []
  const render = (parentId?: string, ancestors: string[] = []): React.ReactNode => nodes.filter(n => n.parentId === parentId).filter(n => !ancestors.includes(n.id)).map(n => <div className="tree-node" key={n.id}><Button className="tree-heading" aria-expanded={expanded.has(n.id)} onClick={() => toggle(n.id)}>{expanded.has(n.id) ? '▾' : '▸'} {n.title}</Button><div className="state-triad"><span>设计<br/>{n.design}</span><span>实施<br/>{n.implementation}</span><span>验收<br/>{n.acceptance}</span></div>{expanded.has(n.id) && <div className="tree-children"><WorkRows works={data!.works.filter(w => n.workIds.includes(w.id))} open={open}/>{render(n.id, [...ancestors, n.id])}</div>}</div>)
  return <section><h2>已记录目标结构</h2><p className="note">这是目标设计，不是磁盘目录树。三项状态各自独立。</p>{nodes.length ? render() : <Empty>{data ? '当前范围尚未记录目标结构' : '目标结构查询尚未接通'}</Empty>}</section>
}
