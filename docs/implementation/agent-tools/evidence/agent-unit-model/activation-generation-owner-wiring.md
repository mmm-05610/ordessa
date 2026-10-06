# 持久激活代次＋显式生产属主接线（PARTIAL）

前置 `344d58525431afdac87b7e61aae94b6979f9bdb7`，开工 clean（仅用户提供 .env 未跟踪、绝不入库）。用户已裁定：代数按 activation-generation-proposal.md 实现、Profile 一行 import 补丁可改、真实模型/Harness 调用授权。主会话唯一共享写者；architecture-reviewer 完成第 1 次架构评审（只读），test-author 只写指定反例文件；均无 Git 操作。

## 实现代数持久化（按已裁定提案）

新增 `pacthold/core/activation_generation.py`（门面链规则只许 core/environment，故落 core；纯 stdlib＋environment-api，无第二库/注册表/持久 ID）：
高水位记录 `pacthold.activation-generation/<owner>` 严格 schema（schema/environment/owner/highWater，`type(x) is int` 拒 bool/float）；fresh 依据 `core.environment/activation-generation-basis` 由部署在创建新持久 EnvironmentId 的同一 store 事务写入（seed_fresh_environment 走 store.transaction 原连接；commit_domain_change 拒嵌套事务）。分配＝单次原子 CAS（预留即确认，不做两状态记录）；请求身份为内核保留 principal `pacthold.internal`＋确定性键 `activation.generation.<owner>.<n>.<nonce>`，摘要覆盖 (owner,n,nonce)；冲突只重读重试（每代恰被一个实例取得），未知不发布不重发（ActivationGenerationUnknown），发布失败耗代、高水位不回退、staged batch 回滚无残留。缺依据/损坏拒绝，不 seed1、不猜代、不迁移历史。

Environment 增 `activation_generation="in-process"|"durable"`（默认 in-process 即提案"非持久环境保持明确进程内模式"；durable 要求 store 域面孔）。部署恒 durable。同修两处评审发现的现存缺陷：`environment.py` instantiate 代次默认 1 旁路（durable 下缺分配即 typed 拒）；`OwnedEnvironment.close` 吞错提前放锁（现改为 revoke→detach 重试→成功才放写锁，错误保留、重入重试不吞 pending、并发 close 串行且 store 只关一次、回调重入 close 以 "already in progress" 阻止递归）。

与评审 1 的一处保留分歧：评审建议确定性 (owner,n) 请求键＋replay 承担确认；同键同摘要会让并发第二实例经 replay 双得同代，违反必测"两实例CAS仅一个取得每一代"。采纳确定性键＋尝试随机数进键与摘要：不同尝试永不共享 replay，同尝试重放仍可显式判读。评审确认的单点分配（_commit_activation_stage）、单次 CAS、部署层一次性注入、close 修复、代次旁路修复全部采纳。

## 显式生产属主接线

`AgentToolsDeployment` 新增成对、显式、仅 agent-assembly/2 的 `policy_factory(EnvironmentId)`＋`owner_ports_factory(Environment)`；缺一/非 callable/旧版本/外域 policy 拒。`deployment/owner_ports.py` 是唯一 records 导入点（函数内懒导入），默认 Profile/发现部署不导入不创建 records owner。OwnerPorts 只含可信端口（authority/current_state/scope_authority/native session evidence/management epoch/Node evidence/preparation context+observation＋可选 configuration/unit/input association evidence＋可选 close 回调），不携带 issuer/verifier/records，结构上杜绝工厂混入第二存储/签发器。装配点唯一：issuer 用 environment.store_port 原对象、verifier 只建一次（records 与 provider 同实例）、原 canonical journal `root/plugins/profile/native-configuration.sqlite`＋原 OperationJournal/UnitRecords。journal 归属证据（`core.environment/native-journal-binding`）：新建才绑，已有 journal（含空文件）无匹配证据拒绝、绝不删除；journal/父目录/WAL/SHM 符号链接拒绝。wire 首次取服务前一次性注入 agent_services；owner 工厂提前缓存默认服务拒绝。重复接线拒绝；同 journal 异 scope authority 由原单属主 pin 拒。

冷重开守卫由"旧根一律拒"改为证据化：有 fresh 依据＋高水位才许带 provider 重开（历史根缺依据仍拒、不 seed）。原严格冷重开目标断言不删不改，现由实现真正满足。

## 验证（解释器均 .venv-ordessa-py312/bin/python，主会话串行，句柄全 terminal）

| 命令 | 结果 |
| --- | --- |
| `-m pytest -c packages/backend/pacthold/pyproject.toml packages/backend/pacthold/tests -q` | 269P/3F exit1 7.7s（同三个已登记 kernel_direction 继承 ID，无新增；中途曾因环境模块导入 activation_generation 触发门面链 AST 4F，移入 core 后恢复 269P/3F） |
| `PYTHONPATH=…codex/pi/claude-code/harness-transport… -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration -q` | **312P/0F exit0 16.6s**（原 311P/1F：冷重开严格断言现由持久代数真正通过；旧"一律拒"正例改夹具为真正无依据历史根，断言原文保留） |
| `PYTHONPATH=products/agent-tools/deployment:plugins/harness/records/src:packages/backend/harness-transport/src … test_activation_generation.py -q` | 13P/0F exit0（test-author 编写，主会话复跑核实） |
| 同上 … `test_owner_wiring.py -q` | 14P/0F exit0 |
| `PYTHONPATH=plugins/harness/records/src:… -m pytest -c plugins/harness/pyproject.toml plugins/harness/tests/test_native_unit_confirmation.py test_unit_records.py test_unit_configuration_records.py test_operation_journal.py -q` | 107P/0F exit0 |
| `PYTHONPATH=plugins/harness/records/src:… -m pytest plugins/profile/tests/test_harness_real_service.py -q` | 6P/0F exit0（已批准一行 import 补丁后原 2P/4F 恢复） |

反例覆盖（全部真实临时 SQLite＋受控端口，C 层）：冷重开不复用代次；两实例每代恰一次；发布失败耗代无残留；丢回执不发布不重发且不删高水位；高水位 bool/float/schema/owner/env/多余字段损坏拒绝且不改写；历史无依据拒绝不写；贡献冲突仍由 CoreRegistry 判定；factory 缺一/非 callable/v1/外域拒绝；端口方法不可调用（必需与可选）拒绝；owner 工厂预缓存 agent_services 拒绝且无 journal 残留；已有 journal（含空文件）无归属证据拒绝且不删除；journal/父目录/WAL 符号链接拒绝；第二 store 同库拒（WriterLockHeld）；同 journal 异 scope authority 与重复接线拒；单属主身份断言（issuer 原 store、records 同 verifier/journal、注入即缓存）；close 回调重入/并发/抛错语义（仍撤销许可、错误保留、store 恰关一次）；pending detach 保留写锁、重入重试不吞成功。

失败与修正（均测试侧，断言未放宽）：门面链 AST 触发→模块移 core；测试仓库根路径差两层；缺 records PYTHONPATH；symlink 子例误用另一 root；混用反例误用第二个 journal 对象（改为同对象 pin＋重复接线拒）；契约类缺 frozen dataclass；bind 误用带版本 surface id。test-author 两次夹具修正同为测试侧。

## 边界与剩余

C：真实临时 SQLite/journal/部署＋受控端口；P：无原生进程；M：0（本轮无模型调用）。未验证：三家 provider 消费生产 records/verifier 的纵向接线（下一切片）、真实 authority/目录/租约/回执 owner、配置事实确认、冷启动整链、生命周期/任务/结果。Core 三个继承方向扫描红与已登记 known issues 保持；无第三方安装更新、无用户数据/凭据/全局配置/服务操作、无 push/主树合并。费用：architecture-reviewer×1、test-author×1，token 用量见平台账，精确费用 unknown。
