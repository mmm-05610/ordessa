# 非秘密材料的受权调用接缝（已裁定，待实现）

2026-10-06 用户明确答复“采用这个受权扩展”。采用本文建议边界；裁定不是代码或生产验收完成。

## 事实与边界

028 contracts §3–5/7/9已经要求：同Registry可信贡献、有作用材料沿原Agent Operation/Step/Usage、权限重核、精确版本、unknown保留占用、Harness owner实际消费材料，秘密正文不入持久账。AU interface-map进一步明确复用C1 ResourceProvider，不能转调CoreDispatch另起执行账。

当前C1 acquire只接收operation_key/execution_id/contract/provider/ownership/输入摘要，不接Agent授权上下文或完整材料引用；UNKNOWN可能没有lease/handle，而现reconcile又要求已知lease/handle。故直接接旧方法既不能证明原Agent作用授权，也不能核实回执丢失。三名Luna只读核对，不把此结论当生产试验。

## 建议裁定范围

在同一已注册资源provider上添加版本化、可选的受权材料能力，保留原C1调用合同；Agent材料路径只消费新能力，不以无授权上下文的旧方法填空。原部署InvocationIssuer/Verifier是唯一权限签发与检查来源，没有新authority或注册中心。

获取必须绑定：当前可信调用者、精确资源版本、用途、拟消费的Node/Unit/配置目标、当前DirectoryBinding及管理epoch、原operation/step/recovery correlation与输入摘要。读取资源元数据不是获取许可；每次获取、查询、释放都通过原authority按对应action/target重核。缺能力或许可，必需项发前拒、可选项具名省略。本首片不处理SecretRef或秘密正文。

获得材料后交给Harness owner的是不可变、类型化材料引用及摘要，不是核心执行的脚本或原生路径。成功receipt按028固定exactResourceRef/immutableMaterialRef/digest/schema/lease/host activation/provenance/evidence；不带正文、凭据或任意callable。资源引用到provider/contract的选择必须由领域的可信引用提取/路由提供，不从任意payload猜测，也不自动选第一provider。

回执丢失只按原operation/step/精确资源/原correlation查询；缺查询覆盖即unknown并保留Usage，不能重新获取或盲释放。原C1字段可以作为只读关联投影，不能把execution_id伪造成Node/Unit身份、不能启动C1另一个ledger。实现应优先保留独立Agent typed关联DTO，不依赖旧字段语义获得授权。

生命周期沿原设计：copyComplete需唯一配置owner的实际消费证据才能具名释放；runtimeRequired转入Node Usage直到已证实停止/替换；dynamic保留旧effective集合，新candidate确认后同事务切换，partial/unknown保留必要两集。首个执行切片只选已有明确owner消费证据的非秘密材料；缺实际消费证据不启用该寿命保证。配置owner始终是实际配置唯一权威。

## 技术形状及验收准备

具体DTO编码和可选能力名字由主会话指导Luna按上述逻辑合同实现，既有C1 DTO、二元registry lookup及原调用签名保持；能力缺省表示不可用于Agent材料。新方法必须显式接InvocationContext，provider用原Verifier核对应action/provider/target/digest。查询须不依赖已知lease/handle，能找回唯一原获取关系；release用新具名cleanup step及受限上下文，不复用旧获取票据。

反例必须覆盖：仅有metadata read、错用途/目标/版本/activation、缺部署authority、claim后权限变更、lost acquire receipt、query unsupported/覆盖不足、跨请求换key、未知释放、消费证据缺失、旧新Usage不提前释放、密文/明文canary不持久化；单测/真实临时SQLite契约/真实资源消费者分账，缺资源不算绿。

用户已采用；先收口014只读准入元数据，再冻结可选受权能力的实现合同，沿原账逐阶段实施与验证。
