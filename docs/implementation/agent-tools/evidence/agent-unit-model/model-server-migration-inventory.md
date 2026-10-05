# AU003 Model/Server 迁移依赖盘点

核查基线 d7b99ac3c1（只读源码检索；不是验收成功）。主会话唯一写者；Codex代理只读盘点，不测试、不Git。

| 当前入口 | 现存依赖/效果 | 独立提供者承接状态 |
| --- | --- | --- |
| products/server/src/ordessa_server_product/composition.py native_runtime | 导入并有条件激活 ModelProviderAdaptersPlugin，组装原生旧通道 | 不是独立AgentUnit生产装配；不能视为新路径完成 |
| products/server/src/ordessa_server_product/native_configuration.py | NativeModelServices，现存owner/channel/carrier/journal组合 | 各独立provider的生产owner未完整供应；不能另建配置真值或操作库 |
| plugins/harness/src/ordessa_harness/configuration/model/plugin.py | 三家registration factories发布历史C2 point | 旧三家仍作为一个插件贡献，不符合最终独立所有权；稳定ID须保留迁移依据 |
| configuration/model/bridge.py | 三家pure compiler、C2 DTO转换、claim/schema/version range/secret slot | 独立包不能导入该旧内部模块；也不能靠复制bridge创建通用原生翻译层 |
| configuration/model/live_service.py | verified_installation、原C4 ConfigurationApplicationService＋OperationJournal＋ActionGrant | 当前Codex1.1.14/Claude0.81.2 ACP pins不是独立新通道的运行证明 |
| claude/configuration/model.py | model与endpoint分离、instance scope、SecretRef绑定、restart-resume同Session、无readback即unknown | SDK set_model ACK不等于配置生效；独立unit_port默认缺席，未承接生产语义 |
| configuration/model/live_runtime.py＋claude/configuration/runtime.py | capture原owner/digest、preflight及效果前重核、凭据检查、operation-bound observe | 依赖旧application/materialization/server_acp；不能把薄Claude子类搬走就宣称独立闭包 |

## 下一切片依赖和反例

先在现有装配入口核对旧三家可达性及当前缺资源行为，区分仅历史元数据与能进行作用的入口，不能以无调用搜索代替运行门。然后逐家将已有原生语义及对应测试迁入各自owner；共享纯契约仅复用公开包，原持久claim、授权、receipt、source revision和scope锁不变。最后换Server原装配的依赖，证明旧三家不能被大插件暗启用，才清理旧实现。

Claude必须保留：project scope拒绝；model-only不改endpoint；无原生request param pin拒绝；credential为引用、无明文；endpoint变更同Session恢复确认；原生ACK/配置文件不能充作applied；未知不自动重发。Codex必须核对managed-account/provider/endpoint/secret/restoration；Pi必须核对provider注册/catalog/retry/reverse restoration。现有纯compiler/配置测试与packaging probes在迁移期间保持，不删除断言或用新的窄测试替代。

生产owner缺席时typed拒绝，回执缺席或不确定作用保持unknown；不能用受控owner或历史ACP pin报新产品native就绪。其余七家成果保留。此盘点不授第三方安装、登录、模型调用或用户服务操作；完整生产配置/生命周期仍PARTIAL。
