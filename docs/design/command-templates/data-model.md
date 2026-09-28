# Data model：内容、分配、展开

所有数据属于 `ordessa.assets.command-templates` 的服务域数据根，不写到 Server core DB 的业务表或 Profile 正文列。真实表/字段名实施时按现有数据根 API 冻结；以下是语义 schema。

```text
Template(id, ownerPrincipal, displayName, slug, description,
         origin=user|imported, createdAt, archivedAt?, entityVersion)
TemplateRevision(templateId, revision, bodyUtf8, parameterSchema,
                 contentDigest, approvedAt?, createdAt, immutable=true)
Assignment(scope=user-global|user-harness|project|project-harness,
           scopeIdentity, harnessId?, templateId, state=enable|disable,
           pinnedRevision?, expectedVersion, updatedAt)
ProfileFacet(assets.command-templates: templateId -> inherit|enable(revision)|disable)
ExpansionReceipt(operationId, principal, targetFingerprint, templateId,
                 revision, argumentDigest, renderedDigest, renderedBytes,
                 draftId, draftRevision, createdAt, expiresAt)
```

正文与参数不进入普通列表或诊断日志。receipt 不必长期保存渲染正文，可返回一次性受限响应；若需崩溃恢复，以受控时限/配额加密保存，另验收。模板文本是用户输入，不是 secret 存储；引用秘密参数禁止填入常规占位符，需经未来专门接口设计。

## 参数语法 v1

Ordessa 自有确定性语法 `{{name}}`。name 为受限 ASCII 标识，`{{`、`}}` 的字面表示使用固定转义 `\{{`、`\}}`；不解释其他语法。参数 schema 是 `{name, kind, required, default?, maxLength?, choices?}`，kind 首版为 string、enum、integer、project-ref。无未声明占位符、无未使用必需参数；重复同名引用同一值。字符串按原样 UTF-8 替换，不按 shell 引号执行，也不递归展开。`project-ref` 由授权项目服务解析成明示的显示值/稳定 id，不能接受用户伪造绝对路径。缺参数、类型不符、输出过大都在插入前拒绝。相同输入/修订必须产生相同字节与 digest。

这套语法故意不复刻 Pi `$1`、Claude `$ARGUMENTS` 或 Codex `$FILE` 的不同索引/语义。导入器只能在可无损证明映射时转换；含命令执行/动态 include 的原生文件不以“部分成功”导入。

## 解析顺序与快照

按用户全局通用 → 用户全局某 Harness → 项目通用 → 项目某 Harness → Profile 的顺序，同一 templateId 的后层明确 enable/disable 覆盖前层，未声明继承。会话临时选择只是**一次调用**，不保存到 Profile 或默认分配；Profile 的通用临时覆盖端口若被使用，须符合其已有覆盖/清除语义，不能新造表。不同 ID 的同名 slug 必须在有效目录计算时检测，不能按层级悄悄删一份。强制策略独立校验且最高优先。内容版本发布、绑定审批、Profile 修订、目标身份和贡献代次分别有独立 revision；preview 与插入均重检，旧异步结果不得写入新目标。

插入时将服务端重算的 renderedBytes 放进当前 draft，附可选 provenance `templateId/revision/renderedDigest`；用户一旦编辑，发送权威就是当前草稿文本，不是模板。不得在真正 send 时根据最新模板再次展开，也不得因后端模板服务暂时断开抹去已合法插入的普通草稿。若在预览之后、插入之前内容/目标变化，要求刷新预览而非偷偷重算。

## 数据升级与回滚

首版新私有 schema；旧 `plugins/commands` 没有模板持久数据，不迁为内容库。用户明确导入 Pi/Claude/Codex 现有模板时只读原件并建立 Ordessa 修订，不覆写原件、不自动启用。Schema migration 在合成副本 dry-run，可前向升级；旧版本无法读新 schema 则类型化拒绝，不删数据。归档仍保留历史修订与审计引用，删除需另定保留期和授权流程。
