# Data model 与迁移

| 对象 | 所有者 | 字段/不变量 |
| --- | --- | --- |
| ProviderConfig | Model-provider | `providerConfigId`（沿用旧 provider ID）、`version`、`harnessId?`、`origin`、`displayName`、`authMode`、`credentialRef?`、`endpoint?`、`protocols[]`、品牌字段、`archivedAt?`；secret 永不入对象。已登录投影可为只读、非可归档记录。 |
| ModelOffering | Model-provider 目录投影 | `(serverInstanceId,harnessId,providerConfigId,modelId)`、`label`、facts/provenance、`observedAt`、`availability`；声称的模型不等于实测可用。 |
| ModelChoice | Profile facet 或会话覆盖 | 原子值 `(harnessId,providerConfigId,modelId)`；落会话时另绑定 server/session、配置修订。provider/model 不拆成两项分别继承。 |
| ConfigReceipt | Harness 应用记录 | operation/target/generation、provider revision、plan digest、verified native model/provider、native session identity、结果证据；不含 secret/正文。 |
| TurnFact | 会话/执行记录 | submission id、choice 与 profile revision、ConfigReceipt 引用、当轮实际生效结果；历史不被新版本编辑倒改。 |

`saved/reachable/ready-for-session/pending-next-turn/applied/refused/unknown-outcome` 是不同事件/状态；reachable 只证明一次受控请求，不证明当前 Harness/会话的认证及配置。新模型能力未知时不能靠 UI 默认值“补齐”。

旧表 `server_provider_models`、`providerModels.*` 幂等 scope、`opaque_id("provider")`、现有 JSON 对象摘要和字段保真；对 provenance 列保留 **omitted=KEEP，显式 null=clear**。迁移用 expand/compare/switch/contract：先新插件只读同表比对；一次装配只开一个方法所有者；切换产品清单；用旧记录读/写/归档回放和字节/行为差分；确认无旧写者后才退 compat 行，绝不双写。任何 schema 变更需显式迁移版本、备份/回滚与旧数据样本测试。

Profile facet `assets.model-provider` 只存 ModelChoice；Mechanism settings 和 ProviderConfig 存本业务库。供应商从 P1 编辑后，已引用会话下一轮读**最新配置修订**重新评估；正在输出维持冻结快照。P1 修改字段 A、会话覆盖模型 item 时，P1 其他 item 的新修订仍流入；成功主动切 P2 清全部旧覆盖，失败/unknown 不得把旧有效状态丢掉。
