# 待冻结的接口语义
接口名为逻辑命名；AU001映射现有snake_case方法并发布唯一Python/公开wire契约，禁止保留两个同义权威。

## 注册
现有AgentContributionSet.agent_runtime_providers进入Environment同一CoreRegistry。
descriptor包含providerId/contractVersion/definitionRef/implementationDigest；保留既有完整引用与host activation身份。
configuration-kind注册复用已有契约或既有registry扩展；不新建ConfigurationMaterialProvider独立注册中心。AU001必须核对资源acquire/release/reconcile及配置适配claims的现有入口。

## Provider方法
describe_definition(definition_ref)
inspect_installation(binding)
assess_configuration(manifest, installation, context)
plan_preparation(snapshot, context, correlation)
prepare(plan, invocation_context)
start(prepared_unit, invocation_context)
query_step(correlation, authorized_read_context)
describe_access(unit_ref)
connect(unit_ref, authorized_lease)
inspect_configuration(unit_ref)
stop(unit_ref, invocation_context)
release(unit_ref, invocation_context)
recover(native_binding, invocation_context)
新增管理语义：describe_configuration、apply_configuration、query_change；复用既有配置适配入口后确定准确签名及contractVersion处理，不能静默改变已发布版本。
不支持能力提供明确typed拒绝而非空返回成功。

## 配置描述
每项configurationKind/schemaVersion/inputSchema/supportedActions/scope/applicationModes/confirmation。
scope由插件解释实例/session/下次输入；core将scope绑定到已有规范target引用，不建立另一套scope身份。
支持值随固定native/adapter版本描述。声明支持和实测证据分开。

## 修改请求
requestId + expectedConfigurationRevision + declarations[] + applicationPolicy。
declarations复用Profile配置声明：declarationId/configurationKind/schemaVersion/action/requirement/payload/resourceRefs。
applicationPolicy包含allowDeferred、allowRestart。默认都false。
node/unit目标与principal来自受控context，正文不能授予权限。
允许新增普通native配置schema版本，但已支持的旧schema不能无声重解释；未知required声明拒绝，可选跳过必须逐项报告。
SecretRef解析受授权，秘密不进入Profile、快照、operation日志、stdout或恢复记录明文。

## 修改结果
operationRef + overallOutcome + itemResults[] + confirmedSnapshot（可缺席）。
item outcome：applied/deferred/restartRequired/rejected/conflict/unknown。
applied必须附与请求内容、scope和操作身份匹配的确认依据。
accepted/协议ACK不是默认生效证据；readback不可得且ACK仅确认接收时返回unknown/deferred。
多项部分应用必须逐项报告；默认不承诺原子性、不自动回滚。提供者明确声明atomic才可要求。
unknown不可换requestId重试；queryChange仅查询已有操作。
请求同ID同内容复用既有幂等契约；同ID异内容/版本前置拒绝。

## 版本与并发
expectedConfigurationRevision指插件在明确scope内确认的版本，不是Profile revision、catalog revision或全局节点状态版本。
核心不得自行推算actual版本。版本未知时拒绝要求版本比较的修改。
提供者管理写入串行且在副作用前检查版本。native有外部修改者/无原子compare时声明保证范围；无法满足调用方要求就typed拒绝，不伪造native CAS。
延迟旧回执不能覆盖较新观察；版本不可比较则保留独立证据并标未知，不按收到顺序假装最新。

## 快照
unit/scope引用、sourceRevision、observedAt、配置事实、未知项、确认依据。desired与pending不能混入actual。
不承诺所有native配置可枚举。未能观察的字段显式unknown，不用Profile填空。

## 生命周期与恢复
connect需要指定unit/current provider activation/lease；平台终止写权限时旧连接立即拒绝后续dispatch。
stop、release、disconnect不同：stop工作单元，release本方使用关系/拥有资源，disconnect仅关闭连接。
停止效果必须有证据；borrowed不允许当owned删除或kill，unknown不自动释放破坏性资源。
recover保留原Node/Unit/nativeSession绑定，重新授权与核实安装和版本。凭据/恢复路径不暴露消费者，不能自动选择最近session。
