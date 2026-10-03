# 005 证据 — SQLite 持久化、秘密与数据空间

2026-10-03。前序：004@7c94ec8140。委派模式：T005-01/T005-11 由 slice-worker 两个切片交付，主代理复核+复跑+修正（B 切片 post-publish 窗误用同版本重发布，按 E5 全量替换语义改 v2）。

## 交付
- **ordessa-persistence-sqlite**（新包）：SqliteStorePort（E1 StorePort；同根写者排他=显式证据接管、请求 key 原子占位/同digest重放/异digest KeyConflict、response slot 单消费、回执 append-only+current 修订、key 墓碑）、ProtectedFingerprintHmac（HMAC-SHA256，轮换→ComparisonUnavailable+墓碑仍阻塞）、LegacyCompatReader（封存 schema 只读：immutable 打开、agentbox_product_schema 21 版、future 拒、字节不变）、SqliteRelationshipStore（E5 持久关系：全量替换幂等/跨重启 published 仍在/同门互斥/reservation 持久仅显式释放/epoch 持久单调）。
- **ordessa-platform-services**（新包）：FileDataAreaAdapter（稳定 namespace→目录、close 保字节、purge 须显式授权、旧二进制对超范围 schema 拒写）、SecretRefAdapter（借出逐次校验、locked 拒无 fallback、轮换新 revision、删除拒在途借用+墓碑永存）。
- **pacthold seam**（切片A）：CoreStoreProtocol（真实使用面 4 方法）；CoreRuntime 注解+运行时校验改协议；CoreStore docstring 机制归属说明；旧构造兼容（CoreStore 仍满足协议）。**记账偏差**：test_public_contract 钉子 `store is CoreStore`→`is CoreStoreProtocol`（精确度不降，必要平移）。
- **T005-08**：evidence/order-005-schema-risk.md（风险/备份恢复提案；零真实数据操作）。

## 测试（主代理串行复跑）
| suite | exit | 结果 |
| --- | --- | --- |
| packages/pacthold | 0 | 246（241+5 seam） |
| packages/backend/persistence-sqlite | 0 | 20（10 store + 10 relationships，含 5 个真 SIGKILL 窗） |
| packages/backend/platform-services | 0 | 7 |
| packages/backend/environment-api | 0 | 33 |
| plugins/runtime-compat | 0 | 163（未回归） |
| apps/server/tests/platform | 1 | 5F/226P——stash 对照确认全为继承红 |

崩溃窗（真 SIGKILL 子进程，flush 握手）：store pre-intent（零记录）/post-intent（claim 在、unknown 不重发）；relations pre（零）/mid（半集回滚，恢复上一完整集）/post（跨 kill 全量在）。

## 边界与缺口（如实）
- CoreBinding/产品 Store 构造消费者未物理迁移（006 入口统一时随 dispatch claim 切换；防双写）。
- 五窗完整提交链 kill（外部接纳后回执前等）随 011 真实链；本单为端口级。
- env_requests 的 reserve 不含指纹校验（指纹在 Environment.invoke 层；端口层只保 key/digest 纪律）。
- dispatch.py 内旧 CoreStore 注解残留（切片A 范围外，无运行时影响，006 清）。
