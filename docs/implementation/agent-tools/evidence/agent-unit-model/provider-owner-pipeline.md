# 属主→provider 管线合同与三家家族接线（PARTIAL）

前置 `3f40afad33`。主会话唯一共享写者；architecture-reviewer 第 2 次咨询（只读，四问全答），三个 slice-worker 并行家族切片（接口冻结后放行，各写各包，均声明写权释放）。真实模型 0；无用户数据/凭据/服务操作、无 push/主树合并。

## 冻结合同（按评审 2 裁定，含一处对评审 1 的延续分歧记录）

- factory 合同扩为 `provider_factory(environment_id, owner_view)`，恒两参；`owner_view = AssembledOwner.provider_view`＝仅 `OwnerProviderView(records, verifier)`，**绝不含 issuer**（评审高优先修正：插件代码永不获得签发权；capability 分离——provider 只消费 verify）。缺 `owner_ports`/`provider_view`（旧产品部署）→ 显式 None → discovery-only 降级，不抛 AttributeError、不伪造。
- 家族 `build()` 在既有 family/definition/环境一致性检查后追加同一性断言：provider 消费的必须正是 `owner_view.records`/`owner_view.verifier`（codex 用公开 records/verifier，pi 用 records/_verifier，claude 用 _records/_verifier），不满足抛 GuaranteeUnavailableError。零 owner 不断言。
- `UnitRecords` 新增免调用属主读：`owner_read_unit/owner_read_session/owner_read_unit_confirmation`——属主受信投影不消耗任何 invocation/claim/ticket；原授权读面（要求 context+input_digest）不变。这解开三家 P 级投影端口的共同阻塞（评审高优先修正 #2）。
- `acquireAccess` wire 契约补 `requestId`（评审中优先 #4）：租约签发幂等可重放，effectful 统一由 requestId 驱动（applyConfiguration 的内嵌 change 保留特判）。客户端构建期镜像经 `packaging/generate_schema.py --write` 从核心契约重新生成并复验，仅 schema-management.json 变化。
- 沿评审 2 对旧消费者的裁定：不整体迁移——endpoint/credential/restart-resume/附件四类**语义**由新 owner 承接（connect+lease、受权 SecretRef、provider.recover、input_association_evidence），代码按家族加 typed 退役闸；sidecar 转入 server-compat 共享域，负退出条件"不存在第二解析者"由 import 边界锁死。records 终止方法族（评审 #3）按依赖序在生命周期切片冻结——三家现均 typed 拒 stop/release，冻结先于实现的约束成立。

## 三家家族切片（并行，各写各包）

- codex：server_plugin 传 view＋公开属性同一性断言＋7 新测试；全包 210P/0F（原 203）。
- pi：同模式（records/_verifier）＋**构造期拒绝新旧双路混用**（unit_records 在场且 owner/confirmations 在场即拒，理由：冻结合同无法表达旧路，混用会让旧路遮蔽新路）＋9 新测试；全包 271P/0F（原 262）。
- claude-code：同模式（_records/_verifier）＋6 新测试（含 records/verifier/双替换三参数化反例）；全包 200P/0F（原 194）。
- 三家均保留既有断言、无 skip；失败修正均为测试替身问题（EnvironmentId 类型、真实 InvocationVerifier isinstance、provider_view 每访问新建视图——身份不变量在原始 records/verifier 对象上）。

## 集成复跑（主会话串行，句柄全 terminal；解释器均 .venv-ordessa-py312/bin/python）

| 命令 | 结果 |
| --- | --- |
| `… -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration -q` | **312P/0F exit0** |
| `… test_owner_wiring.py test_activation_generation.py -q` | 28P/0F（15＋13） |
| `… -m pytest -c plugins/harness/codex/pyproject.toml plugins/harness/codex/tests -q` | 210P/0F |
| `… -m pytest -c plugins/harness/pi/pyproject.toml plugins/harness/pi/tests -q` | 271P/0F |
| `… -m pytest -c plugins/harness/claude-code/pyproject.toml plugins/harness/claude-code/tests -q` | 200P/0F |
| `… -m pytest -c packages/backend/pacthold/pyproject.toml packages/backend/pacthold/tests -q` | 269P/3F（同三个已登记 kernel_direction 继承 ID，无新增） |
| `… test_native_unit_confirmation.py test_unit_records.py test_unit_configuration_records.py test_operation_journal.py -q` | 107P/0F |

集成失败账（均夹具侧，断言未放宽）：三处单参 factory/lambda 与一处 `cls` 默认参数被 owner_view 顶位（两参化后 TypeError/NoneType）；客户端镜像过期（acquireAccess 契约变更后未再生成）→ 真实服务客户端拒服务 schema，`generate_schema.py --write` 刷新并复验后恢复。

## 边界与剩余

C：真实临时 SQLite/journal/受控端口＋家族 Python 实现；P：无原生进程；M：0。未验证：三家消费生产 owner 的纵向端到端（下一 codex C→P）、projection/channel_factory/lease_port 三只适配器的生产装配、records 终止方法族与 AgentLifecycle、acquireAccess 的 wire 绑定（schema 已声明、wire 尚未广告）、旧消费者退役闸逐家落地、真实进程/模型。Pi 只读申报一次 git status 越界（无暂存/树变更）；codex 同类申报见其报告。架构评审累计 2/3 次；子代理本轮 slice-worker×3，费用精确值 unknown。
