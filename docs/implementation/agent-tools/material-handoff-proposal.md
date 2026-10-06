# 材料与配置结果交接提案（第一项已批准，第二项待澄清裁定）

2026-10-06：用户明确采用第一项受权交接；第二项澄清后用户指出不能把全部能力下放Harness，Harness应暴露控制能力由Agent模块掌握实际控制。第二项原提案不得直接视为批准，须按此控制边界修订。具体DTO/作用路径仍须冻结、编码与验证，不以批准冒完成。

## 用户补充的控制边界（优先于下方原提案）

Agent核心掌握配置选择、required/optional决策、路由、顺序、不可变intent、目标/版本前提、授权、Operation/Step/Usage、调用与恢复/停止时机。ConfigurationProvider提供领域解释/有界纯编译；Harness暴露可调用的原生控制端口，执行核心指定且持久登记的动作，重核真实目标/版本/原生字段并返回证据。Harness不得自行换清单、追加步骤、重发未知输入或推进整个流程。准备材料引用只负责数据交付，不携带调度权；不可据此让Harness接管Agent控制。核心同样不实现原生codec或第二actual账。

前置4107c32678，非秘密材料受权获取/原query已受控验证；不是实际消费完成。028规定ConfigurationProvider独立领域、纯引用提取与compile、Runtime/Harness保原生执行与唯一actual真值；但当前实际材料只得到opaque MaterialObjectRef/lease，未有配置解释者或运行owner受权读取内容入口，CompiledFragment到原生owner认可边界也未冻结。

## 建议一：原提供者给指定消费方受权读取

不让核心搬运材料正文或解释native路径。原材料提供者沿同服务器Issuer/Verifier与原操作关系，为指定配置解释者/运行owner提供受权读取；绑定已取得immutable材料、资源版本、用途、Node/目录/epoch、可信消费方provider pin及原取得证据。没有许可/受权入口/原取得关系即拒；未知不重新取得，不把opaque引用当内容已读。核心仅协调固定引用/摘要/安全证据、原Step/Usage，领域方理解材料内容。读取不等于已安装/消费；消费及三寿命释放仍需原Runtime owner明确证据。

这不是新authority/注册中心或通用代理翻译器。实际读取可由现Server提供者的领域端口处理，客户端不接raw bytes/句柄权威，不启动后台服务；首片非秘密。具体闭合DTO及授权目标在裁定后由root指导Luna冻结，现阶段不写这条作用路径。

## 建议二：原生owner认可的准备引用交接编译结果

ConfigurationProvider返回不可变、类型化且由目标Runtime owner认可的准备材料引用；核心固定kind/schema、来源/输入/目标摘要、provider pin、atomic groups及材料关联，不执行编译脚本，不把秘密/原生配置正文写核心Operation。Runtime owner最终核实引用格式、目标/claims、before revision、权限并沿原生协议应用，真实结果仍归其确认。无法认可该引用或缺来源证据即拒，不将提供者的compile输出自证为native成功。

不追加第二份实际配置账。引用的原生准备内容由原领域/Runtime管理机制持有，不在core创建新的对象内容存储或通用指令解释器。实际对运行owner交接的版本化合同需裁定后再冻结，不往旧ConfigurationChangeRequest.payload塞临时新协议。

## 等待期间可推进

独立配置贡献的纯Descriptor、精确路由、逐声明引用/coverage闭合合同及准入元数据；原Registry唯一、core零Harness依赖、不解析payload。SecretRef授权、真实cold activation恢复、实际consumer/释放都不凭上述两项裁定自动冒完成。
