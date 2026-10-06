# 同一操作记录分阶段准备（已裁定，待实现）

用户2026-10-06明确采用“分阶段处理”：原设计先解析材料后正式生成准备计划；同一记录核实材料后才原子补入后续步骤，原步骤不能修改，unknown不能推进，追加后旧授权失效，原调用方式保持。依据028 design §7第5→6步、contracts §4/5/7，而不是另起Agent ledger或第二执行操作。

现实现OperationIntent在reserve固定全部steps，Assembly在材料之前生成正式plan；材料回执的交付引用只能在获取后知道。因此要补原Store的可选版本化分阶段能力，不能伪造未来材料摘要或改写已派发step。

## 实施界限

先只实现原OperationStore的可选staged端口、SQLite同env_requests事务及独立反例；不在该切片接Assembly/material resolve/owner消费。旧reserve_operation完整intent相等语义不变；新reserve_staged_operation以原request输入摘要及root recipe摘要重放，返回追加后的同一operation；异root及旧调用碰到staged记录必须拒绝，不能放宽旧冻结规则。

追加CAS须匹配当前revision和intent digest，只增新step、新invocation binding与新计划事实，不改原request/operationRef/kind/Profile/node/epoch/目录、已有steps/bindings/事实。全部既有step必须concluded，pending/possibly-dispatched/unknown/refused都不能越关；optional拒绝后如何继续留作独立语义，不在这里猜。新step/correlation全recipe唯一，prerequisite只指先前step。seal后不能再追加，未seal不能publish。追加与seal同事务，失败无记录/Usage变化；不claim、不签发、不调用provider。

追加改变intent hash，旧InvocationContext自然拒绝；新query context仍能核原step/claim。前阶段没有未决作用才允许追加；冷启只能读最新recipe及原step，不能按初始recipe重新派发。旧provider generation失效不以同ID新activation代查。

同env_requests additive字段固定版本、root intent digest和phase事实（包含追加身份/摘要/前后intent hash/版本及sealed状态），不建第二操作表/索引/ledger。老记录字段NULL仍沿旧路径，新端口拒绝没有staged标识的记录。迁移只在拥有的隔离临时数据库验收，不打开用户数据库；新增格式与旧记录兼容说明另记docs/migration。

## 验证与未验

root replay/cold restart、异root或异输入、CAS冲突/重复phase不同输入、全步骤与授权绑定不可改、unknown不越关、未seal发布拒、seal后追加拒、旧Context失效/新query可查旧claim、失败回滚、缺optional能力发前拒。这里只是同账本扩展；材料resolve/release、Usage及owner真实消费后续实现，不报产品绿。M0/用户服务0，.env不读不入库。
