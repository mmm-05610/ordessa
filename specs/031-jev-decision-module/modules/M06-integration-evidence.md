# M06 · Ordessa只读接入、证据与交接

## 组成
integrations/ordessa：observations/configuration/validation/capabilities/handoff。
evidence：filesystem/codec/redaction/reader。两者同一设计责任，但不相互成为生命周期中心。
组合根注入只读facade，不把包含prepare/apply的完整AgentServices交给图节点。
public默认导入不加载可选Ordessa适配。产品组合根创建SDK/client/writer并明确释放责任。

## 固定源码映射
参考提交577014c450b275faaf35d1e9c4b6cdbf9b6183de，与初次9e1a6d参考分开记录。
只读公开面profiles.list/read_entry/read、providers.list/describe、nodes.list/read、
configuration.describe/inspect。源码用git show固定读取；该SHA是否已推送未知，不伪造远端链接。
profiles.preview恒定unresolved；providers描述不是安装；nodes发布不是空闲/存活；
已有node的configuration.describe不能当创建前目录。
adapter只支持注册查询类型，不接受任意方法路径、SQL、URL或数据库文件。
来源原生引用、权限范围、分页/完整性、sourceRevision、未知和敏感性全部保留。
无公开连续性/占用事实时continue不可通过，不拿标题、PID或配置相似代替。

## 两个公开缺口：JD007在原机制补
G01 前实例配置目录：在已有Agent公共面补版本化描述转发，
输入provider definition及受控read context，返回纯读offer/schema/support/evidence。
G02 只读提案评估：结构、描述版本、材料可读性、owner纯读组合限制；
返回valid/invalid/unverifiable及范围，不reserve/prepare/start/apply/创建lease或用户文件。
配置知识仍归叶子provider，核心只按已接纳的真实owner路由，不导入decision类型/SDK。
如提供者评估需要真实副作用则unsupported，无权限则refused；不能把接口名assess当纯读证据。
接口DTO属于原Agent公开合同，再由adapter映射为decisionDTO；不存在跨层类型反依赖。
安装事实/未来占用/原生就绪不可纯读验证时保留MUST应用前checker；
必需的配置语义本身不可验证则不ready。
开始前检查当前owner是否已补，禁止重复造第二服务；缺口分单实现，不混进普通adapter工单。

## 文件证据实现
宿主传独立运行目录，非Git源码/原生Harness数据/用户配置目录。每run一写者，
目录以随机不可预测runId建立，权限0700、文件0600、拒绝符号链接/越界路径。
不把runId解释为任意文件路径。reader受宿主可见范围限制。
首版有界追加记录+原子终态文件：事件seq、prevDigest、payloadDigest、contractVersion、
run/flow/task摘要、阶段、预算尝试、安全代码和来源引用；不默认记录正文/Prompt/raw响应/header/异常repr。
run.started与结果还绑定RunManifest摘要及实际policy集合，不能只记录flow版本遗漏外部策略。
hash链仅检内部一致性，不宣称防有写权者篡改。
writer在开始后持有OS文件锁至释放；锁和随机writer incarnation是存活依据，不只看PID/mtime。

append_durable须完整写入、flush+fsync文件，首次文件/目录及原子rename后fsync目录；
返回带seq/digest/durability的ACK。无ACK不得跨模型网关。
call.intent须发前持久化，标“可能发出”，不依赖call.dispatched补写填crash窗。
响应到但记录失败：failed/unknown，不返回ready，不重发。
证据存储磁盘满、权限/损坏时fail-closed，不降级成无日志运行。

finish使用同run独占写者锁与单终态原子提交，expectedLastSeq/resultDigest绑定；
同一terminal重复幂等返回同ACK，不同terminal拒绝冲突。完成先commit后返回。
取消与完成竞态：以durable terminal commit为顺序点；
完成已提交则取消不得覆盖，调用者可能收到取消异常但查询读completed；
先接受取消则禁止提交completed。无法证明commit结果时query unknown，不能再写相反终态。
证据写入/清理使用有界shield，超时保留unknown，外部取消仍向上传播；不无限shield阻止退出。

## 中断查询
正常运行函数不返回interrupted。Reader看到started无terminal时，
只有宿主失活证据明确且取得原writer独占锁才能投影interrupted；
活writer、无法锁定、身份未知、日志损坏都不能宣称已结束。
call.intent无response永久unknown；没有自动resume/replay/retry API。
发起新run必须明确旧尝试可能有费用，不用相同requestId承诺去重。
第一版只对本地文件锁语义经过验证的文件系统提供此保证；远程FS不明则unsupported。

## 交接与产品
库、offline_assignment和alternate_flow为必交；Ordessa真实只读示例在接缝可用时必验。
可选独立ordessa-decision propose CLI默认offline，固定可信flow，无apply/prepare/submit/任意模块参数；
真实模式需另有授权/secret resolver/明确预算，不能凭CLI参数自授权。
第一版不新增MCP、改现有agent-tools默认命令或启动用户服务。
消费者接提案再核前置，通过既有核心管理路径实际应用，本包只测试交接不实现自动应用。
T21–T32/T55–T59/T61–T64覆盖证据、只读边界和真实公开核心接缝。
