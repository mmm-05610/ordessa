# Engineering schema7：提案与独立控制

当前实现使用原 EngineeringLibrary、原 SQLite 连接、锁、library_id、scope 与命令 journal。schema7 只追加 Change、Proposal、mutation 索引、ProposalControl 和不可变控制事件表；schema2/4/5 原 DDL 与 schema6 材料表、历史 revision/hash、方法快照、审核及旧升级回执保持。默认创建仍为 schema2，不在 open 时升级。

ProposalUseCases 在 schema7 上原子创建新 Change 或 CAS 已有 Change，冻结完整 Proposal 后展开非 deferred 审核要求，同事务保存初始 available 控制和命令结果。创建、展示选择和 supersedes_refs 均不改变 Artifact head，也不修改旧提案控制。withdraw/supersede 需要可信控制 owner 的 guard；ActorRef、客户端 evidence 与 selected 不产生权限。缺生产 owner 明确拒绝。

## 显式升级

以下操作仅适用于合成数据或另获明确迁移授权的数据库；本轮没有迁移用户数据库。先用既有 Library 打开并确认 schema6，再执行唯一迁移入口：

```python
from pathlib import Path
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.migrations import migrate_schema6

library = EngineeringLibrary.open(Path('/absolute/synthetic/library.sqlite'), library_id='synthetic-library')
try:
    receipt = migrate_schema6(library, backup_path=Path('/absolute/synthetic/schema6-backup.sqlite'))
finally:
    library.close()
```

原安全备份流程拒绝覆盖、inode alias、sidecar 和不匹配来源；逻辑摘要、备份物理摘要及目录同步先完成，原库写锁内重查来源后追加表、FK检查和唯一迁移回执。所有旧行参与保持性比较。若 COMMIT 已开始后丢失回复，连接关闭并返回 migration_commit_unknown；重开原库查询 schema/receipt，禁止凭 unknown 盲目重发。重复显式调用仅恢复原回执。

## 精确引用与预算

Proposal evidence link 使用完整 ClaimRef，主张解析到实际 owner revision/claim/digest；同名主张可属于不同修订。Mutation 和 claim_refs 的索引序列保持原次序。Review 模板只能使用封闭的 self/base/proposed/claim_owner/result_of_intent selectors。验收 spec 引用冻结 TemplateRef；result_of_intent 等真实 Submission 后展开，本阶段不能提前生成已验收的 Requirement。

同事务解析共享64MiB材料预算、私有精确 row/index 缓存和完整闭包证明；不产生新存储权威。supersedes 闭包上限4096个提案/10000条边。完整 ReviewSet、预期核验及替代控制也共享材料预算；外部定位和每条 exact digest 仍须校验。路径按段判断、排除优先、rename 两端均需允许，字符串校验不等于真实文件系统隔离。

完整 ActionScope/ImplementationIntentSpec 已有封闭纯值。生产仓库基线 owner 尚未装配，带 spec 的业务创建明确 IMPLEMENTATION_BASELINE_AUTHORITY_UNAVAILABLE；不丢弃该字段、不回退 prototype。版本来源、artifact 来源、生成 owner、生产 method/criteria/reviewer trust、Server 身份/ACL、apply/Grant/Consent/outbox/Submission/CLI 闭环仍未完成。W03/W04/W09 保持 PARTIAL/IN_PROGRESS，不能以本片替代全部 W00—W16。

当前证据入口：[Proposal 检查点](../implementation/nightly/evidence/W04/proposal-checkpoint.md)；[schema6](engineering-schema6-materials.md)。WAL/热 journal、原生 FD、OS ABA 和全产品发行验收仍未关闭。
