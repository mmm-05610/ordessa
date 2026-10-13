# Profile definitions（候选／待用户代码审阅）

用户批准了新命名及外层内容类型化方向；实现/完整API尚待审阅。
models是唯一模型定义，validation校验自身结构/重复项/非法组合，codec转换已解析JSON。
不依赖management、Unit、具体Harness、apps；不文件IO、不存库、不应用原生配置。

| 内部模型/字段 | 原wire/持久化字段 | 实际含义 |
| --- | --- | --- |
| Profile.profile_id | profileId | 稳定预置身份 |
| Profile.name | displayName | 名称 |
| Profile.version | catalogRevision | 管理记录CAS版本 |
| Profile.archived_at | archivedAt | 原归档时间/null；archived为派生bool |
| Profile.current_revision | currentManifestRef | 当前固定内容修订引用 |
| ProfileRevisionRef.environment_namespace/profile_id | environmentNamespace/profileId | 精确环境/预置身份 |
| ProfileRevisionRef.revision/digest | manifestRevision/contentDigest | 内容版本/原摘要 |
| ProfileRevision.ref/content | ref/content | 固定引用/类型化内容；content_json仅派生 |
| ProfileContent.schema_version | schemaVersion | 原内容schema标识 |
| ProfileContent.harness_definition_ref | harnessDefinitionRef | 深度不可变的opaque引用 |
| ProfileContent.declarations | declarations | ConfigurationDeclaration tuple |
| ProfileContent.metadata | metadata | 原可选扩展元数据，省略和{}不同 |
| ConfigurationDeclaration.declaration_id/configuration_kind/schema_version | declarationId/configurationKind/schemaVersion | 原声明身份、种类、schema |
| ConfigurationDeclaration.action/requirement | action/requirement | 原value/reset/disabled与required/optional |
| ConfigurationDeclaration.payload/resource_refs | payload/resourceRefs | 冻结JSON值/opaque资源引用 |

配置值允许原有限JSON能力（包括有限float）；不硬编码所有provider设置。递归union定义实际支持类型，
冻结嵌套mapping/数组并防御复制，不以Any改名冒充类型化。原深度/字节/声明数限制与SecretRef约束保留。
模型直接构造也校验；codec对未知字段/非法输入拒绝。OMITTED与null不同；refs省略与[]不同；metadata省略与{}不同。

ProfileRevision.content是唯一内容权威；content_json从内容计算，不能独立传入或赋值。摘要按原canonical规则验证。
旧类ProfileCatalogEntry/ProfileRef/ProfileManifest退休，不提供别名。仓内Python导入已成组调整；
原JSON名称与历史数据保持，不把内部模型改名当成数据库迁移。

本轮小整理：JSON union、省略哨兵和冻结/解冻辅助的唯一定义在 `definitions/json_values.py`；
models只消费这些辅助，codec直接消费省略/解冻能力。业务模型/校验/协议行为未改。

codec函数使用Profile/revision/content名称；decode_*只接已解析dict/list JSON，encode_*返回独立dict/list。
完整content验证保留深度32、字节262144与声明256上限；单独值/声明辅助不额外施加完整内容字节上限。
跨发行包消费者使用ordessa_execution_agents.profiles显式公共入口；definitions仍不反向导入management。
