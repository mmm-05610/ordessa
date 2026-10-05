# Provider 发现接缝

本接缝使用已有 Agent RuntimeProvider descriptor 与当前 host activation，服务入口为 `agent_services(environment).providers.list()/describe(definition_ref)`。Environment 的 `agent_runtime_contributions()` 返回当前唯一 CoreRegistry 的 active 接纳对象；没有第二个 provider 清单、缓存或安装注册中心。

公开投影为 `{descriptor: RuntimeProviderDescriptor.to_dict(), providerRef: admitted.provider_ref}`；list 返回这些投影的 tuple，wire `agents.providers.list` 包装为 `{providers: [...]}`，`agents.providers.describe` 返回单项投影。definitionRef 必须是完整 environmentNamespace/definitionId/revision；owner 身份只能来自 host。每次调用检查当前授权、activation 和接纳后 descriptor/方法完整性；staged/draining 不出现在列表，active 篡改不静默忽略。返回值是脱离权威的 JSON 副本。

不调用品牌生命周期方法，不运行二进制或探测安装，不将 supportedMethods 声明当作安装、ready 或真实验证。仅显式 `agent-assembly/2` 发布这两个已冻结方法；默认 `agent-assembly/1` 保持 Profile 面。capabilities 的 supportedMethods 只增加这两个实际绑定，仍不宣称 nodes.prepare 可用。这里不是 leaf 的 describe_definition 原生知识替代品。

代表性反例及缺席行为：权限缺席/撤销即拒绝，即使 registry 为空；跨环境或不完整引用拒绝；active 提供者篡改拒绝；退役后重新接纳返回新 generation，不能使用旧 generation；没有 active 提供者时只返回空发现结果，不能视为运行能力通过。

测试 `test_provider_discovery.py` 是受控 Provider + 真实 Registry/Environment/wire handler 证据，未启动 Server 网络服务、品牌进程或模型。生产准备协调仍须固定 Profile、Provider generation、安装/目录许可、材料与原操作步骤，并核实真实 owner 回执，不能靠这两个观察入口完成准备。
