# Engineering schema4：Artifact 与命令原子事务

这是实际实现的有界切片，不是完整工程应用验收。源检查点 `dd31c36ea5`，设计来源为夜间不可变 DESIGN。唯一 `EngineeringLibrary` 的 library ID、连接、RLock、原六表和 schema2 DDL 保留。schema4 在 schema3 方法快照之上增加 artifacts、immutable revisions、parent links 和 commands 四表；没有第二个数据库或 authority。

## 显式创建与升级

`EngineeringLibrary.create(..., schema_version=4)` 显式创建应用库；默认仍是 schema2。`open` 不升级；`SQLiteUoWFactory` 对 schema2/3 报 `APPLICATION_SCHEMA_REQUIRED`。已有 schema3 仅可显式 `migrate_schema3(library, backup_path=绝对路径)` 升为4；schema2需先 `migrate_schema2` 至3，再以另一备份路径迁4。真实用户数据库迁移未获本轮授权，所有已执行场景均为临时合成库。

升级先生成不覆盖的 schema3 备份，在读锁内核对 logical/raw SHA，同步文件及父目录；保持备份读锁至源库提交。写锁后重验原六表、全部 snapshot/blob/release 字节和所有已有迁移回执，DDL含trigger逐完整statement同事务执行。只有本次新回执从旧数据比较中排除。原数据或既存回执变化即回滚并关闭；失败证据和可用备份保留。相同已完成迁移只核对原回执/备份，不重做升级。

提交结果未知时库关闭，重新 `open` 并查 durable receipt/原 command key；不能因丢回复换 operation ID 或自动执行。WAL、热journal、原生SQLite FD证明及恶意OS ABA仍未支持。

## 实际用例与边界

`ArtifactUseCases(SQLiteUoWFactory(library), trusted_access_port)` 有 create/append/query。`CommandContext` 是内部可信装配输入；actor仅记录归属，`human`/issuer字符串不授予权限。缺 access port 在写库前失败。当前测试使用显式 SyntheticAccess，不代表Server生产认证已接通。

command key 为 `(realm_id, principal_id, request_id)`，摘要绑定 operation、project、输入schema id/精确摘要、interface version、参数和preconditions。同key改变身份拒绝；重放返回原operation和pending/terminal结果，pending不重新执行。artifact事实和command回执共享原连接、一个BEGIN/COMMIT。业务拒绝通过savepoint回滚局部事实后记录rejected回执；存储/损坏/未知错误使整个事务失败。savepoint清理未知会poison，禁止继续写或提交。

创建可原子包含初始修订；追加不移动head，只CAS推进artifact version。修订digest含scope、actor/time、payload、精确parents，父及全部祖先必须真实存在且摘要匹配。同字节已存在revision仅返回原ref，无版本写入。DFS限制10000访问边/栈项、10000唯一节点和64MiB累计编码字节，超限 `ANCESTRY_LIMIT`，不截断成功；已验证1105层链及密集图明确拒绝。未知stored kind可读，但写拒绝。只读UoW使用SQLite `query_only`，仓库不可跨线程或事务生命周期使用。

目前只实现inline payload；Blob/source/claim/metadata等完整设计输入尚未支持，未知字段明确拒绝。Review/Proposal/control/full ReadSet/outbox/consent/method adoption、公共output DTO/catalog、Server/CLI接线和旧prototype整体退役仍待实施。不能将本片视为完整 W03/W04/W09 或第一CLI闭环。

## 复验

```sh
.venv-nightly/bin/python -m pytest -q packages/engineering/tests
.venv-nightly/bin/python -m pytest -q tests/architecture/test_dependency_boundaries.py
.venv-nightly/bin/python tooling/checks/dependency_boundaries.py
```

最后一条整树门仍失败；负例绿不替代实际整树方向清理。实际命令、首次失败、精确源码摘要、安装wheel与独审见[application evidence](../implementation/nightly/evidence/W04/application-checkpoint.md)。源码与wheel计数重叠，不累加。未触碰用户库/凭据/服务，无新增模型请求、push或main合并。
