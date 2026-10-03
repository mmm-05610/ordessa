# A1 — Agent领域公共合同（不进入核心）

R4设计。提供者Agent插件；消费者Chat、Profile、Model-provider、其他资源或独立视图。Harness是原生能力提供者。Pacthold只管理能力访问/身份/Usage，不理解以下字段。

## 唯一所有者与执行位置

SessionOwner、SessionConfigOwner、SubmissionOwner、RunOwner、InteractionOwner是同Agent领域按事实职责划分的内部模块，不是五个独立核心/调度器。每个Canonical AgentTarget仅一个对应owner；默认Desktop生产目标以后台Agent能力为权威，前端客户端是代理/投影，不另持可写pending/confirmed/send-state。确实独立纯前端Agent提供者可另声明不同target，不能与后端同实体双writer。

AgentTarget由可信逻辑会话/来源映射定义，native alias按E2核验；socket/window/provider schema不创造新实体。Draft在第一句前可以存在，不强制创建native空会话；已有会话历史/恢复归原native owner，产品逻辑映射由Agent维护。

## 公开读写与观察

- readConfig(binding,target) → ConfigSnapshot（ownerRef、revision、observedEvidence、operations、resolved摘要、字段known/unset/unknown）。版本来自同owner，不从UI日期合成。
- observeConfig(binding,target,cursor,credits) → E3连续snapshot/变化；控件只订阅，不赋值owner内部对象。
- submitConfigOperation(binding,target,operationId,patch,sourceRef,baseRevision?) → ConfigOperationReceipt。patch只含present/unset字段；点击时确定操作顺序，异步解析完不重排。资源schema由资源公开合同提供。
- queryOperation(binding,operationId) / listOperations(target) → 安全状态及可核对关联；历史只读权独立，不拿旧operation重新发。
- submitInput(binding,target,submissionId,draftCapture,throughOperationSequence,guarantee) → SubmissionReceipt。捕获文本/附件/精确配置版本/绑定；遵守C1/C2，不因当前UI选中改变路由。

DomainAccess dispatch是一切修改入口。Profile与model控件都是操作源：后提交只覆盖它携带的字段；Profile不含model不变更model；同Profile重选新operationId，是真正重新应用而非no-op。资源目录/认证引用留资源owner，Agent不拥有Provider全业务。

## Harness专属接入，不给普通插件setCurrentConfig

原生应用通过Harness受管理能力。reportConfigEvidence、reportInputReceipt、reportNativeEvent等接入面只能由与当前target绑定的可信Harness来源调用；校验native owner/generation、operation/submission关联、版本、字段证据与支持声明。公共普通consumer API不开放任意“设置已确认状态”。

原生自主变更可以更新确认投影；未消费用户操作仍按声明字段顺序形成待应用值。已消费操作不能永久盖住原生新事实。证据不全保lastObserved/unknown；矛盾可比revision标conflict并阻所需依赖操作，不能把选中label当生效。

ConfigSnapshot把确认与意图作为同owner状态链，Resolved纯派生不持独立store。所有选择位置投影这一份状态；显示名、目录查询缓存和表单草稿合法但不是发送输入权威。

## 提交与生命周期

输出过程中配置操作只入序列，不打断原生输出；下一次用户发送时捕获相应操作边界。应用确认与输入接纳不同：apply-success/input-rejected保草稿，apply-unknown不续发，input-unknown只查原ID不重发。无配置改动普通原生输入可按raw能力工作，不要求虚构强一致保证。

UI关闭释放观察；已接纳提交归Activity/SubmissionOwner。资源插件卸载不删已捕获资源版本/关联；依赖确实缺失则typed拒绝或保unknown，不新建第二owner补位。领域owner停用需E3/C2收口，重启只能按可信证据恢复。

DraftProvider是公开编辑对象合同：draftId/revision、不可变捕获及consumeExactRevision。Chat实现Chat草稿，非Chat可以实现自己的编辑对象，不要求Chat；平台只提供编辑lease/scope原语，不理解消息正文。成功仅消费捕获revision，晚编辑不能被文本相等清空。

## 接入资源插件示例

Model-provider读取自己目录→用户选模型→Agent.submitConfigOperation→所有控件看到同Resolved→下次输入Agent捕获→Harness原生应用→可信确认回Agent→输入送原生。Profile同路径但patch多字段；未选Profile不影响普通模型切换。

不得出现：Profile glue私有binding被model控件读取；两个控件各存lastConfirmed；frontend与backend都判unknown解除；provider目录服务调用品牌文件写入；Pacthold新增model字段；查询配置触发apply/probe/login。
