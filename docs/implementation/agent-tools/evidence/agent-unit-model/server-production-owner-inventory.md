# 三家纯迁移之后的生产owner接线盘点

基线 `66936bcedf`，Pi检查点后 clean。主会话read-only核对，Codex代理read-only审查。未启动服务、写用户数据、测试或模型。本文为下一正向实现证据，不是生产验收。

## 已有公开接缝

三家ServerPlugin以 `context.ports["core.binding"].environment.environment_id`为唯一身份，并让factory显式构造独立RuntimeProvider；原Registry阶段/提交及冲突仍由Server/Core持有。Codex现有 UnitProjectionPort、ChannelFactoryPort、ConnectionLeasePort、ConfigurationEvidencePort 和 verifier/records入口已定义；default没有真实ports不发布start/apply支持。AgentToolsDeployment显式选择能做Registry discovery，policy仍只授Profile和registry read；不授节点执行/配置，不可用Bearer或可读路径代替。

## 不能机械替换的旧消费者

`products/server/src/ordessa_server_product/composition.py` native_runtime已拒三家；后面的NativeConfigurationPlugin/ModelProviderAdaptersPlugin/旧Profile chain仍为旧消费者，不能通过换import把旧C4确认当新Unit事实。`native_configuration.py`把ACP channels＋ProfileSessionOwner＋NativeModelServices连接原历史native-configuration.sqlite。profile_preparation/profile_sessions/turn_application仍按原native target/generation/session/secret/restoration管理，未映射新Node/Unit完整refs及操作scope。

sidecar_runtime仍委托server-compat，且先建product_secret_store；部署解析与实际装配属于共享server-compat域。禁止产品重复解析再相信另一份结果（TOCTOU），也不复制parser或擅自在AU003越域改共享契约。此旁路未退役，原consumer目标仍待后续工单。

## 实际持久owner依赖缺口

实核 `UnitRecords`位于 `plugins/harness/src/ordessa_harness/application/unit_records.py`，不是公共transport。其真实实现要求同一个原 `OperationJournal`，并依赖scope_authority/native_evidence/verifier/epoch_port；原表名/codec/票据身份不改，configuration_evidence/native_unit_evidence/input_association_evidence必须显式注入。只有tests有构造；production Server/AgentTools deployment搜索无UnitRecords工厂。

独立provider的测试 Records不是这份持久owner，不能以fixture方法匹配当持久接线完成。下一切片须先核完整journal/authority消费者，再复用原持久owner与既有issuer，不创建第二库、第二actual cache或第二Registry。必要公共提取须证明复用边界和原表/操作语义，不能为了避开旧private import复制UnitRecords。

## 下一正向切片

优先Codex：明确Server的新opt-in独立装配factory，沿core.binding/同journal注入真实projection/verifier/evidence和每写lease；无安装/版本/授权/材料/SecretRef即typed拒。先prepare/start/inspect、现codex.defaults model/effort scope/readback/query原操作，再接provider/endpoint/credential/restoration。defaults与thread actual分开，纯ACP compiler不授native配置权限。七家旧成果保留，不启用三家旧batch或fallback。

冷generation仍待既有proposal初始化边界裁定，不实现依赖的counter。可继续不依赖它的owner/新root受控接缝，但不能称冷恢复完成。native安装缺席/真实任务无授权，P/M继续未验证。CLI/Skill只消费公开核心/授权通道，bundle安装资产仍需后续显式服务closure，不将七own wheel成功升级成产品全纵向可用。
