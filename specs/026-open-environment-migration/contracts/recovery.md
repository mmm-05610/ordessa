# C2 恢复、请求身份与效果边界（联合合同强制补充）

优先级：本文件是对E1/F1/C1缩写的补全；发生冲突以本文件及后续review处置为准。必须002冻结、005/006/011验证，不能只实现各包接口而跳过接缝。

## 请求命名空间与数据根writer

logical-request key固定为环境持久命名空间+授权principal作用域+requestId。环境重启、activation generation、transport种类、raw/reliable保证等级不产生新key。target/binding/guarantee/input摘要为同key的比较字段；变化不得当新请求。同key已spent/unknown永不再次派发，无法比较只可authorized lookup或typed comparison-unavailable。用户显式新意图可新requestId使用raw，不能自动替旧unknown换key。

同数据根仅一个效果性writer有有效所有权。002冻结实例锁/所有权token与dispatch claim校验方式；OS/进程lease失联或超时不证明原writer已失效。不确定时阻新准入、保unknown，禁止另进程抢着补发。真正持独占锁的暂停进程未退出，第二进程应拒打开effects；重启只有证实原writer失效后可读旧intent，仍不重派旧unknown。若原生侧不支持fencing，内核不能声称强行接管安全。

## 跨Store握手，不假装跨库事务

1. 前端领域持久journal先写不可变submission与稳定requestId映射，包括draft revision/opIds/target/guarantee/输入引用；安全标记失败则未派发。
2. 标记possiblySubmitted并保恢复查询ID；此状态写成功后才允许向后端提交。backend-reservation前失败也不得先丢关联。
3. 后端Store同事务登记key/intent/绑定与责任，再调用native；native配置效果与输入效果分别回执，不用网络回执证明业务成功。
4. 前端根据同request查询后端事实，与native配置journal关联核对；不得为补关联再apply/send。配置journal本身不能成为环境投递主写。
5. 能证明零派发（包括无配置外部效果）时，可靠写not-dispatched释放相应reservation；若marker更新失败仍保unknown。配置已部分生效不能将操作退回ready并无提示再次应用。
6. 恢复读取原映射→查原request→核对证据。无mapping/decoder/key能力不创建新request补救，只保可读缺口；result-unavailable、comparison-unavailable、execution-unknown三种状态分开。

故障测试在领域mapping落盘、possiblySubmitted后、backend intent后、配置生效后输入前、native接纳后领域结果前逐窗真kill。不要求业务库和环境库事务合并。

## 内容冻结与最终打开

可靠提交的文本/配置为不可变编码快照；附件是不可变内容引用或经安全打开保留的受限句柄，绑定内容digest、资源身份与授权。指纹计算与native实际读取必须指向同一内容。
路径不是内容冻结，保留文件句柄也不能阻止同一inode原地改写或截断。可靠路径必须消费不可变内容快照/真正不可变内容对象，或原生可证明绑定同一内容的原子入口；仅文件句柄或stat相等不够。不能hash后跨await重新按路径打开；regular→symlink/同路径替换/原地改写/附件对象变更需原内容发送或发前typed拒。资源借用持到dispatch完成/明确释放，不能关闭UI后消失。

## 密钥与墓碑

key_id/算法/规范编码版本与comparison scope保留。轮换不改变原Activity/Receipt知识，也不删spent key墓碑。正文到期、decoder卸载、旧MAC key不可取仅相应payload/比较不可用，authorized历史中性事实仍可读；拒绝读取不等请求不存在。墓碑保留策略必须002安全确认，不允许自动TTL删后同key再派发。

## 效果fence与回退

effects fence不以input-send为唯一界点。activation创建资源、instantiate、配置apply、原生回答控制请求均可能已产生效果。只要有accepted/possibly-effectful/unknown的外部责任，即走迁移后的保留事实/关准入/只读或兼容新事实恢复路线。

真正“零效果回退”必须所有相关参与者报告未创建/未配置/未回答/未派发并取得足够证据；没有证据按有或未知效果处理，不能git revert/旧writer热切。暂留closure实现仅承接原责任，身份/grant/cut/预算固定，不能接新业务。

## 源快照封闭

001批准对象是不可变来源manifest及导入内容，不是变化中的工作树路径。manifest包含允许源码的类型、mode、摘要、链接类型/目标；不follow越界链接，不读取秘密正文。清点前后、导入前后重算；新增/删除/类型/内容变化均拒并重新提交差异，不能暂停或改写他人会话换稳定性。最终合成SHA有manifest可重算关系。

实施基线的源码/合同/数据能力不同，均要独立证据，不能拿一个Git SHA替实际安装资产和credential许可。
