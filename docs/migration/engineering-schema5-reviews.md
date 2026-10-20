# Engineering schema5 审核存储（PARTIAL）

默认创建仍为 schema2。打开旧库不升级；`SQLiteUoWFactory` 支持显式 schema4/5，schema4 访问 reviews 抛 `REVIEW_SCHEMA_REQUIRED`。
以下接口只针对调用者明确拥有的库；本轮仅使用临时合成库，没有迁移用户数据库。

```python
from pathlib import Path
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.migrations import migrate_schema4

library = EngineeringLibrary.open(Path("/absolute/owned/library.sqlite"), library_id="owned:library")
receipt = migrate_schema4(library, backup_path=Path("/absolute/owned/library-v4-backup.sqlite"))
library.close()
```

源必须是 schema4；2→3 和 3→4 按原说明逐步显式执行，各有不同备份路径。4→5 新增七张审核表及不可变触发器，不改变原14表的既有行、Artifact/command/method正文或旧迁移回执；只更新 schema 元数据和追加本次 receipt。旧回执摘要算法保持原有 SQLite i64 编码。备份不覆盖、不接受同inode、受限读取与 file/parent fsync；其 SQLite 读锁保持到源提交。失败回滚；COMMIT 回复不确定须关闭、重开并检查原 receipt，不能直接重发。备份和先前回执需保留，重复迁移读取同一份备份复核。

ReviewRequirement 的 scope/id/version 冻结完整 canonical 内容，不能用未纳入 SetKey 的 phase/roles/checks 替换它。Plan 在检查前冻结；Record seal 重算 complete/verdict。仓库重新解析目标及全部证据引用，读前 SQL 限制每个正文 2 MiB，完整集合有 4096 records/64 MiB 上限；超限拒绝，不返回截断集合。当前真实解析仅支持 ArtifactRevision；其他 Subject/Claim owner 尚未实现并拒绝。

读集包括全部失败/未知/通过记录与 active/voided/replaced 控制，首空集合 version0；插入 +1，整组 void/replace +1。记录和控制历史不删改，投影必须与事件一致。请求撤回推进 fence/version，检查后的晚结果在原 UoW 中拒绝。各低层仓库 mutator 必须由同一 UoW 的 `isolate()` 包裹，应用命令同时提交 journal；不另开连接或自动提交。

ReviewUseCases 只接受注入的可信权限、方法/审核能力、控制端口。原始 bytes 与冻结计划绑定，方法/信任 guard 在事务外取得、持有到提交。公开 ActorRef/VerifiedReviewerEvidence/CurrentReviewTrust 是值，不自授权限；合成端口只用于机制测试。durable raw_response_ref 已通过同字节权威接入 schema2 ReviewRecord，见[当前说明](engineering-review-raw-blobs.md)。生产 owner、完整 method/trust ReadSet、Proposal/Consent/outbox、真实方法桥及 Server/CLI 未接线。GateDecision 是提案及版本预期，不能当 Grant。旧 prototype 业务组仍待整体退役，不是新路径 fallback。

证据与实际缺口：[审核检查点](../implementation/nightly/evidence/W04/review-checkpoint.md)。WAL/热 journal/恶意 OS ABA 仍未关闭；不将上述路径保护声明为原生 FD 证明。
