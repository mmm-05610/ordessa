# 004 证据 — 激活与退出权威合入 Environment

2026-10-03。前序：003@ceca96799f。交付：`pacthold.environment` 生命周期与关系门扩展 +
`tests/environment/test_lifecycle.py`（12 测试）。

## 任务对照

- **T004-01** Environment 侧权威：激活拓扑/冲突/stage-commit 复用 CoreRegistry（003 已接）；
  本单补 published_revision（每次 committed batch +1，T004-02）与 drain/retire/closure/holds。
  **ServerPluginHost 物理转发属 006-02**（"变有限投影/forwarder"，写权与入口统一同批）——004 后
  Server 侧旧 registry 仍在运行，两套并存的状态如实登记，006 消除；不声称 004 已单 registry。
- **T004-02** 贡献事务+发布 revision：activate 一事务（stage→commit→索引+revision），失败零发布
  （003 冲突测试）；失败激活外部对象经 `register_settlement` 登记（"external-instance-orphaned"），
  不宣称无副作用（测试 test_failed_activation_registers_settlement…）。
- **T004-03** drain cut 原子关新准入：state 翻转=线性化点（对象本身按设计单线程索引）；
  drain 后 bind/invoke/instantiate(late open) 均 `AdmissionRefusedError`，query/lookup 存活；
  新 generation 正常 activate，旧 generation 的 mark_retired 无法影响新代 capability
  （test_new_generation_activates_after_drain…）。
- **T004-04** closure 规则：retire 必须 drain 先行；blockers=对象 unknown 状态/在途 usage/
  unclassified deliveries/被等待；owned 无退出证据 → retire-pending（M05/D5）；借据式收尾
  （settlement notes）与 ClosureContext 语义=查询只读面保留。
- **T004-05** owned/borrowed/static：owned 要 closure_evidence（缺→pending，unknown 不删）；
  borrowed/static 退役=关系 released（无 kill 路径存在）；static 内容永不删；handover usage
  在 owner 关闭时结算（_usage_object 链接）。
- **T004-06** 等待图：register_wait 拒自等待/闭环（WouldDeadlockError）——回调已返回也查边
  （V3-9 反例）；clear_wait 后合法重登。
- **T004-07** 受控双插件：A drain 后 B 正常 bind；错误 generation 的 IdentityMismatch；全部状态
  单 root（实例字段）。
- **T004-08** E5 关系门：publish_reference_set（按源版本全量替换、幂等、源不符=identity 错）；
  inspect_incoming（coverage known/unknown，声明缺失=unknown 不是"无引用"）；destructive 变更被
  published 关系拒绝；reservation 显式 evidence 释放（UI/TTL/进程死不自动）；新关系与破坏性
  reservation 同门互斥；**声明插件退役后 published 关系仍在且仍阻塞**（test_published_references_
  survive_retirement…）。

## 门对照

- G004-1 依赖/贡献一 revision 发布、drain/closure/owned-borrowed 一致 ✓（上述测试）；
  反例：A 半激活可见（stage 不发布+失败零索引）、旧 dispose 撤新贡献（generation 隔离测试）、
  borrowed 被杀（无 kill API，只 release）均被门抓住 ✓。
- G004-2 前序 SHA：003@ceca96799f 同树 ✓。G004-3：pacthold 241 绿（229+12 新，0 删）✓。
  G004-4：无凭据/数据/未授权操作 ✓。

## 命令与结果

| 命令 | exit | 结果 |
| --- | --- | --- |
| `.venv/bin/python -m pytest packages/pacthold -q` | 0 | 241 passed（GREEN_NO_SKIPS） |

## 边界与缺口（如实）

- ServerPluginHost 转发未落地（006-02；见 T004-01 说明）。holds/loader 校验的物理迁移随 006。
- 关系/等待图为内存实现（005 持久化+崩溃窗口测试）；Subscription/delivery envelope 属 007/008。
- ClosureContext 的跨插件收尾链（V3-6 全语义）在 004 提供 blockers/settlement 骨架，完整证据链
  归 007（Harness 参与者）与 011（真实链）。
