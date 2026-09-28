# Data Model：预设、覆盖、意图、运行事实分离

本文件定义逻辑模型。现有 SQLite 表可增量迁移，不要求把全部实体都新建同名表；物理 schema 在实施前绑定已审平台和已有数据库版本，禁止改写旧修订。

## 1. 实体

| 实体 | 关键字段 / 不变式 |
| --- | --- |
| Profile | stable profileId、不可变 harnessId、displayName、description、version、currentRevision、archivedAt；所属 Server 数据域由服务认证边界确定 |
| ProfileRevision | profileId/revision、item bindings、schema versions、timestamp；不可变，旧回合引用不回写 |
| ItemBinding | facetId/itemId/schemaVersion + `{kind: 'set', value}` 或 unset（无绑定）；null/[]/false 仍是显式值，不是删除 |
| MechanismPolicy | server realm、revision、facetEnabled map、allowUserOverrideWrites/global + per-facet；CAS；不含执行权限或秘密 |
| ProviderIntegrationSettings | 各提供者自行持久化的服务域内设置及 revision，供 Profile 设置贡献读写；不是某个 Profile 的字段或会话覆盖；参与编译时其修订进入 ConfigIntent |
| SessionBinding | canonical SessionRef、harnessId、selected intent + seq、lastApplied receipt、overlayRevision、transition state；不得只用 nativeSessionId |
| SessionOverlay | SessionRef + facetId/itemId/value/schemaVersion + version；只对当前 Profile binding 有效，成功切到另一 Profile 后清旧集 |
| ConfigIntent | operationId、requestHash、session target、selectionSeq、profileRevision、overlayRevision、policyRevision、provider generations、resolved items、desired digest；预检快照，不是应用成功 |
| AppliedReceipt | operationId、SessionRef、runtime generation、实际生效的 config digest、profileRevision/overlayRevision、策略和能力版本、证据类型、confirmedAt、可选 executionId |
| ApplicationJournal | planned/applying/confirmed/rejected/unknown、明确失败来源与已完成步骤的非秘密引用；崩溃恢复不靠猜 |

canonical SessionRef 必须使用现有会话领域稳定身份，至少区分 Server/连接归属、Harness 与原生会话；实际 channelId 是短期路由，不能独自充当持久会话 ID。若当前 API 没有持久身份映射，列接缝任务，由会话所有者提供，不在 Profile 发明跨服务猜测映射。

## 2. 解析算法

1. 在下一轮准入边界读取有效 selection：有 pending 则取 pending Profile，否则取绑定 Profile；非归档取最新 revision，既有归档绑定取归档时固定 revision。
2. 显式换成另一 Profile：解析时不带旧覆盖，但先保留旧覆盖数据；只在新配置确认生效后提交清理。
3. 同一个 Profile 的全局更新：按 itemId 覆盖；没有覆盖的项读新修订，不按整 facet 遮盖。再次选同一个 Profile 不清覆盖。
4. Profile 未声明、且没有 overlay 的字段交给对应提供者/Harness 的默认语义；默认必须来源可辨，不等于沿用“上一个 Profile 留在进程里的值”。
5. 所有显式引用检查 schema、存在性、权限、provider 代次与适用性。A→B 要同时校验移除项的 reset，缺提供者不能通过“先过滤字段”消灭差异。
6. 有效值携带来源：profile@revision / session-overlay@revision / target-default@fingerprint。每个配置面先校验，汇总后的运行配置再交 Harness 检查跨字段组合。

### 合并例子

P@1 = provider A、model M1、reasoning medium；会话 S 覆盖 model M2。
P@2 = provider A、model M3、reasoning high：S 期望 M2/high，未覆盖会话用 M3/high。
若 P@3 把 provider 改成 B 且 B 不支持 M2：S 显式冲突，不替用户删 M2，也不回写 P。用户改 model 或恢复跟随才能消除。

列表是否整体还是元素级覆盖由提供者用稳定 item 粒度声明，不能 Profile 自行对数组深合并。一个可独立开关的 Skill 可有独立 item；一个需要有序原子更新的规则列表可作为一个 item。增删 item ID 有 schema 迁移，不用 UI 索引作 ID。

## 3. 快速切换和并发

- 尚未应用的 B→C：seq 递增，C 替代 B，旧预检失效。
- B 已进入外部应用：不能假装取消已生效步骤。持会话配置/发送门完成 B 的确认或未知处理；C 排在其后。存在待应用 C 时不可在 B/C 之间放行新消息。
- 应用中会话编辑：拒绝新的 overlay 写入并显示“正在应用”；不丢输入文本。允许登记下一次 Profile 选择，后续单独处理。
- 全局 Profile 在应用中更新：当前 intent 固定旧 revision；在获得运行发送门时确定这一轮快照，后来的全局更新用于下一轮。不得持续追最新导致饥饿，也不能在 admission 与 send 之间换配置。
- 先 commit AppliedReceipt 与绑定/overlay 清理，再通过相同准入门放行一轮；外部已成功但本地 commit 失败 → journal unknown，不能回报已切换。

## 4. 秘密与引用

Profile 保存 credential locator/asset id 等受控引用，不保存 key/token/env map 明文、会话历史或文件正文副本。提供者声明允许字段和引用类型；未知字段拒绝。旧 sensitive-key regex 作为附加防线，不是唯一安全边界；合法 maxTokens 一类字段不能仅因名字含 token 被误禁，真正秘密也不能靠改名绕过 schema。

UI 只获得脱敏预览/能力和非秘密值；digest 不包含秘密值，不以简单秘密哈希泄露低熵信息。日志不记录完整配置 payload，错误用字段 ID 与安全说明。

## 5. 持久化与迁移

- 保留现有 profile_… ID、旧修订、归档与版本账；新增表/列通过可重跑版本迁移，不删除原库。复制只创建新 Profile，不改源修订。
- session_id 迁移为 canonical ref：必须有服务映射证据；无映射或碰撞进入待核对状态，不合并两个会话、不靠名称推定。
- 旧“settled + DB readback”标成 legacy-unverified，不直接升级为 AppliedReceipt；新准入前由真实 Harness 验证或重新应用。
- Facet schema 迁移纯函数产生新修订，原值保留；不得在 provider 注册时全量原地改旧 revision。无法迁移给出 blocked 原因。
- 机制策略默认对已有注册 facet 启用、允许用户覆盖写，保持既有行为；新字段仍需合法输入和真实能力，不因启用给任何权限。
- 归档不级联删 overlay/运行事实；引用检查与归档 CAS 在服务侧完成。首版无硬删与跨服务导入；备份/恢复不包含凭据内容。
