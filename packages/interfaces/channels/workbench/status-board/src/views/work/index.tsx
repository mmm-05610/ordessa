import type { BoardSnapshot } from '../../contracts/client'
import { Empty, WorkRows } from '../../presentation/records'
export function Work({ data, open }: { data?: BoardSnapshot; open: (id: string) => void }) { return <section><h2>变更与工作记录</h2><p className="note">包含跨目录和无目录工作；步骤由绑定方法提供。</p>{data ? <><WorkRows works={data.works} open={open}/>{!data.works.length && <Empty>当前范围没有工作记录</Empty>}</> : <Empty>工作记录查询尚未接通</Empty>}</section> }
