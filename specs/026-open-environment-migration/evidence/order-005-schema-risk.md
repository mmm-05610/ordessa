# 005 T005-08 — 新 schema 说明与真实数据迁移风险/备份恢复提案

日期：2026-10-03。前提：**本轮零真实用户数据操作**（M09 未授权）；以下仅为 fixture 验证过的
设计与提案，真实迁移须单独授权（compat-retirement §1.7、M07）。

## 新增 schema（environment 层，与业务 DDL 分离）

`ordessa-persistence-sqlite` 的 `_SCHEMA`（SCHEMA_VERSION=1）只建环境事实表：

| 表 | 用途 | 身份规则 |
| --- | --- | --- |
| env_meta | schema 版本点 | 键值 |
| env_writer_lock | 同根写者排他（C2） | singleton 行，owner_token |
| env_requests | 请求 key 占位/回执/当前事实 | (environment, principal, request_id) 主键；digest 为比较字段 |
| env_objects / env_usages | 对象/使用关系投影 | 全键（A-01） |
| env_response_slots | 控制应答单消费 | (control_id, delivery_revision) |
| env_relations | E5 持久关系声明 | (relation_id, source, revision) |
| env_key_tombstones | MAC key 墓碑（C2，不自动清） | key_id |

业务 schema（server_profiles/server_sessions/server_provider_models…，21 版链）**不进环境层**：
封存于既有 9 份 SQL + Python 迁移链，读侧经 `LegacyCompatReader` 只读映射
（immutable=1 打开、future 版拒绝、表标识不变）。

## 真实迁移风险（按影响排序）

1. **21 版链与 Python 迁移耦合**：迁移逻辑在 runtime-compat storage/database.py 内
   （_migrate_N_to_N+1），非纯 SQL。风险=拆包时顺序/上下文漂移。对策：012 前保持链原位，
   仅注册点显式化（products/server 装配），九份 SQL 字节不变（已 fixture 化）。
2. **同根双写者**：旧 Server 进程与新 Environment 同时开同一 data root。对策：env_writer_lock
   仅保护新表；旧库无此锁。006 切换期须"冻结旧 writer→取得最后状态→启新 owner"（execution-detail
   §4 转换序列），不允许双写；切换演练仅在受控 fixture。
3. **WAL 文件遗留**：旧实现 WAL 模式下 -wal/-shm 伴生文件。对策：备份必须包含三者；
   恢复后先只读校验（LegacyCompatReader）再决定写入。
4. **namespace 映射**：DataArea 目录映射（ns.replace('.', '/')）为新约定；旧数据根布局
   （docs/migration/data-root-layout.md）不变。风险=插件误把物理路径当身份。对策：claim 校验
   namespace 模式（禁路径/窗口 ID，已测）；007 迁资源消费者时逐域核对映射表。
5. **key 轮换跨库**：指纹 key 墓碑在 env 库；若真实部署把秘密与 env 库分离存放，删除秘密不删
   墓碑（已按合同）。风险=运维误清 env 库。对策：备份恢复提案中把 env_key_tombstones 列为
   不可清理表（除非显式授权操作并留审计行）。

## 备份/恢复提案（真实数据获批后执行）

1. 备份：停写 → `sqlite3 .backup` 三件套（主库+wal+shm 或先 checkpoint）→ 记录逐文件 sha256 +
   schema 版本 + data-root 清单。
2. 恢复：新位置只读打开（immutable）校验版本与表计数 → 一致才允许新写入；版本超支持 → 拒绝并
   保留原字节（不自动降级，已测）。
3. 回退：恢复备份后旧 writer 重启前，必须确认新 writer 已显式 release（env_writer_lock 残留时
   按证据接管，不允许 lease 超时抢锁——已测语义）。
4. 演练状态：以上均只有 fixture 证据（test_store_port.py / legacy_read 测试）；**未触任何真实库**。
