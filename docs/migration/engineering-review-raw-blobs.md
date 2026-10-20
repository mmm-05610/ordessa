# Engineering 持久审核响应 — PARTIAL

此变更不修改 DB DDL、默认 schema2 创建或旧迁移回执。Blob 字节仍归原 EngineeringLibrary 的 eng_method_blobs，SQLiteBlobStore 和 SQLiteSnapshotStore 共用一个受限技术实现，连接、RLock、library_id、engineering-blob 标识保持。业务应用显式注入同 authority 的 BlobStorePort；不导入具体 SQLite，也不自动创建存储。该内部字节端口不授予读取权限，公开查询须先通过原应用权限和 scoped ReviewRef 解析；目前没有新公开 blob 下载入口。

ReviewRecord 的封闭记录版本新增 schema2（不是 DB schema2）：必须携带 raw_response_ref，绑定 Digest/长度/媒体和捕获证据摘要；记录 hash 排除可迁移 storage_object_id。wire 保存 locator，读取必须逐条核验原字节 authority，不能因为 hash 正确而接受外库定位。schema1 的原 canonical bytes/hash 精确保持，仍可历史读取；活动 schema1 不可通过当前应用 gate，不自动补引用或升级。

record_response 先授权、检查原 journal 重放和冻结请求，再在业务事务外校验并持久捕获原始 bytes。可信 verifier 消费 BlobRef、在事务外读 verified bytes；返回 schema2 record 必须绑定 exact captured ref/plan/request。method/trust guards 覆盖随后原 UoW 的实际 commit。原响应上限2 MiB，Blob技术上限16 MiB。

业务 insert/get/read_set 在同 UoW 连接核验真实 body/长度/SHA；完整集合先检查原 canonical 总量64 MiB，再检查 distinct raw 总量64 MiB，最多4096记录，超限拒绝而非截断。仅本次 read_set、本事务内去重 bytes 校验；每条仍验证 locator。公开 get_review 每次独立复验，不设跨事务缓存。

capture 的真实 commit 丢回复返回 BLOB_COMMIT_UNKNOWN/reconcile，原 Library 关闭；重开后核验 blob，不能据此认为业务完成。此阶段没有审核事实或 record journal。业务 commit 丢回复仍用原 COMMIT_UNKNOWN，重开查询原 command key；不换 key，不再次捕获/verify 已完成请求。失败捕获或撤回竞态可留下不可变孤立 bytes，不能作为 active审核事实；非active晚回事实尚未实现。

生产 auth/method/criteria/verifier/control owner、完整 method/trust ReadSet、Proposal/Consent/outbox、Server/CLI与旧 prototype 整组退役仍待实现。用户真实库和服务未操作。证据见[持久响应检查点](../implementation/nightly/evidence/W04/durable-raw-checkpoint.md)。
