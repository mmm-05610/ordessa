import type { BoardSnapshot } from '../../contracts/client'
import { Empty, WorkRows } from '../../presentation/records'
export function Overview({ data, open }: { data?: BoardSnapshot; open: (id: string) => void }) {
  return <>{(['pending', 'active', 'result'] as const).map((phase, i) => <section key={phase}><h2>{['待处理', '正在推进', '最近结果'][i]}<span>{data ? data.works.filter(w => w.phase === phase).length : '—'}</span></h2>{data ? <><WorkRows works={data.works.filter(w => w.phase === phase)} open={open} />{!data.works.some(w => w.phase === phase) && <Empty>当前范围没有此类工作记录</Empty>}</> : <Empty>尚未接通权威工作查询，数量未知</Empty>}</section>)}<p className="note">Agent 结束仅代表执行结束。验收以审核与采纳记录为准。</p></>
}
