# AT-007 同 journal 具名步骤存储合同

本树实施冻结口径，消费028 V2.1 §7与R-0002；不是第二Agent执行账或网络协议。权威DTO为 `ordessa_environment_api.operations`，实现为现有 `SqliteStorePort` 的同连接扩展。

## 身份与知识

请求身份始终是 `(environmentNamespace, principalScope, requestId)`。操作类型、固定输入和目标进入摘要比较，不能以换操作类型复用已用键。`OperationIntent` 冻结 operationRef、kind、Profile snapshot、context、可选完整node holder、management epoch、有序具名steps；每步冻结provider ref、input digest、recovery correlation和前置步骤。operationRef在同Environment唯一。所有引用包含Environment；Usage holder包含完整operation请求身份或node instance/generation，target为完整scoped mapping。

`env_requests`仍是主账；`env_request_steps`是其子步骤；`env_usages`增量记录holder/target/revision。原有Outcome知识枚举只用unknown/concluded，reserved/running/unknown/published/refused/cancelled属于独立阶段status，不扩oe-contract/1。存储不签发授权，不验证原生证据真实性，不将epoch数字当transport fence。

## 原子边界

公开可选 `OperationStorePort`：reserve_operation、read_operation、claim_operation_step、read_operation_step、record_operation_step、publish_operation、record_operation_outcome。每次变更使用同连接BEGIN IMMEDIATE并拒绝嵌套事务；domain CAS、Usage CAS、步骤/主记录在同一事务提交或全部回滚。

reserve固定intent及独立canonical摘要。相同key/digest而intent不同仍拒绝；读回摘要不匹配拒绝，不为旧记录推测或回填成功。claim严格遵循完整有序配方，不只检查调用者提供的prerequisites；首次claim持久化possibly-dispatched后才允许上层作用，重复claim返回claimed=false。unknown不解锁后续step、不释放Usage、不自动重发。

步骤证据有独立内容摘要；publish要求完整配方的步骤均concluded，结果内容/证据摘要和固定node身份核验，Usage从完整operation holder原子转给固定node holder。重放比较实际冻结内容。摘要用于损坏检测，不是抵御攻击者同时重写数据与摘要的授权签名。

旧bare-id变更不能覆盖operation或domain result记录；旧Usage覆盖不能篡改具名holder。现存Usage的rights/target固定，holder/revision需要CAS。released关系不能复活或转为新占用；重新取得需要新Usage ID。资源真实释放仍须上层provider证据，存储状态不代造成功。

## 实测范围

真实临时SQLite、两连接CAS、自建进程SIGKILL覆盖claim后及未提交publish窗口、rollback、重复请求、跨scope、未知阻断、旧接口保护与损坏反例。没有Provider调用、节点发布、InvocationContext验证或原生服务保证。完整命令、退出码与数量记status及evidence；单测通过不能把nodes capability设为true。
