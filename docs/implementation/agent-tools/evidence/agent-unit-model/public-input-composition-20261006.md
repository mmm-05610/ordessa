# 托管输入公共装配：核心增量批

前置 HEAD：`8900a56f2df6dfb960e74983f9fa824590b4e321`。开工已核对 tracked clean，仅 `.env` 未跟踪，不读取、不提交。沿原 AU 队列及用户要求继续核心优先，不创建新核心／registry／持久账。此记录为执行证据，不是新协议或完成裁定。

## 分工与冻结接口

用户要求主会话指导多个 Luna 完成编码、验证。主会话只指导、读审、串行执行测试、状态及 Git。三个现有 Luna 继续工作：

| 执行者 | 唯一写域 | 交付与反例 |
| --- | --- | --- |
| luna_core_impl | `packages/backend/pacthold/src/pacthold/agents/public.py` | 增量公开既有 DTO／ports 与 ManagedInputReservations，同 Environment／nodes 一次性装配；不同端口实例不得替换 |
| luna_core_review | 新增本目录 `test_public_input_composition.py` | 同公开服务的 Session／sessionless 原操作预留与单次授权 claim；缺端口、错 Store、重复未知、非空晚注入拒绝，真实临时 SQLite |
| luna_wire_impl | 所有源码只读 | 独立检查装配／授权／owner 边界，核对原合同，报告资源缺口，不修改 wire／CLI |

接口冻结：`AgentServices.managed_inputs`；`agent_services` 追加 `input_capture_port`、`native_input_state_port`、`first_input_observation_port`。原 `ManagedInputReservations` 方法签名、显式 issuer、reserve／claim／reconcile 和输入 namespace 均不变。DTO 直接重新导出原 class，不复制／包装。端口同一实例可重传；首次 None 后补非 None、或换其他实例均按既有 compose-once guard 拒绝。

`inputs.py`、schema、wire、CLI、capabilities、本轮生产 owner／native transport 都只读。没有原生 writer；managedInput 继续 false，缺任一原要求端口／可信 issuer／durable Store 则沿原 typed 拒绝。测试作者不能自行执行／编译／Git；被测文件 ready 后冻结，由主会话串行收终结结果，未经明确解除冻结不得再次编辑。

## 未决与剩余边界

统一操作读取和派发前拒绝的两提案仍待准确语义确认。用户本轮“继续”作为继续原实施的指令，不记为选择了提案选项；该批不实现依赖它们的行为。材料／SecretRef 受权路由、生产capture、native state、单次输入写入、双来源effect/association回写仍缺，不能以公开挂类算端到端任务可用。没有外部模型调用、用户服务／DB／凭据／全局配置操作或其他树写入。

工单结构校验：`python3 /home/maoqh/.agents/skills/incremental-work-order/scripts/validate_order.py docs/implementation/work-orders/agent-unit-model/orders --strict`，五单通过，exit0；仅材料检查，非产品验收。

## 验证账

统一运行器：`PYTHONPATH=plugins/harness/codex/src:plugins/harness/pi/src:plugins/harness/claude-code/src:packages/backend/harness-transport/src:plugins/harness/records/src /home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml`。

首轮该运行器＋下列五文件＋`-q --tb=short`：

```text
docs/implementation/agent-tools/evidence/agent-unit-model/test_public_input_composition.py
products/agent-tools/tests/integration/test_managed_input_reservations.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_sessionless_input.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_first_input_publication.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_first_input_journal_publication.py
```

**121P/0F exit0、9.74s**，句柄10173已terminal；新增11项，其余为原输入机制反例，不累计快照。真实临时SQLite＋受控port/authority，没有原生输入和模型调用，不能算生产writer/回执可用。根审新增测试，进一步要求“缺capture／缺native分别拒绝”和“有原attempt但缺first observation时核实拒绝”；原first observation不强加为reserve/claim前提，符合既有无native query也不一律封锁首输入的设计。

独立只读审阅：public接线没有新authority／registry／协议；现输入API显式接收issuer，核同Store，但本切片不新增canonical issuer对象绑定。宿主调用须继续传原装配issuer/verifier，不得把公开类可见当生产可运行。输入before-configuration evidence等opaque Mapping仍需生产owner遵守无秘密事实合同，不能直接回显任意context/evidence；本批不新增wire投影或秘密解析。此为限定范围，不声称相关生产接线已验证。

新增缺席反例后冻结，统一运行器＋上述五文件及下列八文件＋`-q --tb=short`：

```text
docs/implementation/agent-tools/evidence/agent-unit-model/test_core_profile_semantics.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_core_profile_wire_v3.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_core_harness_independence.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_assembly.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_apply_profile.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_management.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_lifecycle.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_wire_lifecycle.py
```

**261P/0F exit0、18.13s**，句柄40716已terminal。新增公开装配测试14项（其余247项为既有契约回归，不累计首轮快照）。缺capture／native分别验证零持久占用；缺first observation仍可reserve，reconcile明确拒绝且不签query、不改operation/step/domain/Usage。C级受控测试，P新增0、M0。独立复查建议进一步显式证明无观察端口的普通Session claim成功；源路径本身未要求此端口，尚不把该特定正例记为已跑。

生产源码及所有测试冻结后，统一运行器＋`products/agent-tools/tests -q --tb=short`：**788P/0F exit0、218.25s**，句柄16198已terminal。这是产品回归，不包含本目录14项新增证据；不把两个套件相加当独立场景数。无skip，无继承kernel_direction复验，无原生P／模型M。之后只开放新增证据的普通Session正例去掉first观察port，源码不变，定向验证另记。

普通Session正例改为不提供first观察端口后，统一运行器＋`docs/implementation/agent-tools/evidence/agent-unit-model/test_public_input_composition.py -q --tb=short`：**14P/0F exit0、0.51s**，命令已terminal。其余correlation、Session目标、单次claim及unknown不重发断言完整保留。生产源码未变，因此未重复产品全套。`git diff --check` exit0。
