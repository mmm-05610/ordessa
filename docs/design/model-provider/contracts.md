# Contracts：业务服务与贡献入口

以下是**目标语义**，不是当前 main 事实。DTO 应用已有 Server 方法描述符/错误信封与前端 scope API；禁止新 ServiceLocator/第二 ACP client。

## 后端：`model-provider.service`

`providerModels.list/create/update/archive/probeModels/probeConnection` 保持旧外部命名、参数/响应兼容及单一注册所有者。新增能力使用**本插件拥有**的版本化方法，例如 `modelProvider.catalogue/inspectChoice/chooseForSession/queryChoice/reconcileChoice`，具体与旧 wire 命名冲突由 T00 审查后冻结。请求主体由服务端鉴权决定；target 采用 server/session/channel 原生身份，不信自报 harnessId 或 owner。

```text
ProviderCatalogPort.list(target, cursor) -> Page<ProviderConfigSummary>
ProviderCatalogPort.save(patch, expectedVersion, operationKey) -> ConfigRevision
ProviderCatalogPort.probe(configRef, expectedVersion, operationKey) -> ProbeFact
ProviderCatalogPort.inspectChoice(target, choice) -> supported | unsupported | unknown
ModelChoicePort.queue(target, choice, expectedOverlayRevision, operationKey) -> PendingChoice
ModelChoicePort.inspect(target) -> desired/lastConfirmed/unknown + revision
ModelChoicePort.reconcile(operationId) -> Confirmed | Refused | Unknown
```

`queue` 只记录下轮意图，不声称 applied。配置成功和 prompt 成功是两个结果；不可把“选中”返回值当应用回执。目录请求失败为 typed error，非空数组；手动 probe 对私网/重定向/协议/大小/超时 fail closed。存档前问 Profile/会话引用端口；端口缺席 `REFERENCE_STATE_UNKNOWN`，不猜无引用。Provider 卸载后设置贡献消失、数据保留，涉及它的下轮请求拒绝。

## Profile 与 Settings

Profile facet `assets.model-provider`，只有 `choice` 一个**原子 item**，值 `(providerConfigId,modelId)` 且 profile Harness 绑定不变。Profile 验证时检查 server scope、配置版本、未归档、品牌适用，敏感信息只引用 secret ID。Profile 自己管理 overlay precedence；本插件不另起覆盖表。前端通过 Profile 提供的 `addEditor`/可选 `addSettingsSection` 注册模型选择编辑器；纯业务机制设置（预设、探测设置）留本插件 Settings。Profile 缺席不影响目录。

Workbench Settings 注册“模型与服务”分区；无 Chat/Profile 装配也可 CRUD、手动探测。Chat 消费既定 `ChatContributionsToken` 的 `composer.footer` 模型选择器，且只选当前 Harness 的 Provider/Model；缺贡献点只缺 UI，不把业务导入 Chat 源码。Scope dispose 撤销贡献，晚到响应按 server/session/provider generation 丢弃。底层 UI 使用已审通用控件/Outlet，不新建浮层宿主。

## 下一轮提交接缝

唯一会话发送 owner 持有 submit permit：冻结输入摘要+attachment 摘要+choice/profile/config 修订，排除输出中 apply。Harness `harness.configuration` plan/apply/verify 使用 C2 adapter 产生的 typed intent；ACP config 调用只能经现有 channel/controller 的受限控制端口，绝不偷偷再建一个客户端。apply 被确认、原生会话 ID 相同、readback provider/model 与目标一致后，原 prompt 发一次。传输死/回执丢失先 query/reconcile；未判明绝不重发或“回退默认”。

失败码至少区分 `PROVIDER_NOT_FOUND/ARCHIVED`、`MODEL_NOT_FOUND`、`CREDENTIAL_UNRESOLVED`、`PROTOCOL_UNSUPPORTED`、`ADAPTER_MISSING`、`VERSION_UNVERIFIED`、`SELECTION_UNSUPPORTED`、`CONFIG_REVISION_CONFLICT`、`TARGET_STALE`、`RESUME_UNAVAILABLE`、`VERIFICATION_MISMATCH`、`OPERATION_UNKNOWN`、`REFERENCE_STATE_UNKNOWN`。映射现有 wire error family，不能只抛字符串。相同 operationKey+不同 payload 拒绝，同目标不同 key 串行。
