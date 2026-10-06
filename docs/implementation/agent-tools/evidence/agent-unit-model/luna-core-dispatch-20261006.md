# 核心优先与 Luna 派工回执

2026-10-06，用户要求优先完成核心，核心不认识具体 Harness 但能通过公开契约使用；允许多个 Luna 子代理承担编码、验证，主会话指导、接口决策和整合。架构问题面向用户用自然语言说明行为与取舍。

接管 HEAD `26491dd180744d38dec4edb392fa59795ae476fe`。23 个 tracked dirty 文件、+513/-113 为上一执行者配置语义切片；另有 `.env` 未跟踪，不读取、不提交。没有其他活执行者。保留原成果，不 reset/stash/覆盖；已确认配置语义顺序与 AU 合同不重写。

按用户最新分工授权，在原树内明确单文件唯一写者；主会话不独立承担大部分实现。沿 incremental-work-order 管理写权和证据，不另开树、不创建第二队列或第二核心。测试由主会话统一串行启动收集；子代理写测试，但没有自行启动测试/Git的权限。阶段 A 全员只读，现有产品全套基线 terminal 后才开放阶段 B 写权。

| Luna | 阶段 B 唯一候选写域 | 可判定交付 |
| --- | --- | --- |
| luna_core_impl | pacthold/agents 的 configuration、profiles、assembly、management、nodes、lifecycle.py；新增本 evidence 内 test_core_profile_semantics.py | 新清单可原子准备，独立快照权限，同请求不重复作用，遗漏/转换/版本/未知反例不冒绿 |
| luna_wire_impl | apps/server/src/ordessa_server/agent_core_wire.py；新增本 evidence 内 test_core_profile_wire_v3.py | 仅解码转发，来源互斥、applyProfile 按能力广告和派发、具名遗漏错误；不自行 diff |
| luna_core_review | 初始只读；如追加写权仅独立 evidence 测试文件 | 独立审阅上述两切片，验证无品牌依赖；不同 provider 经同一核心，撤销/缺端口仍拒绝 |

共享 schema、public 导出、派工/状态账/Git 由主会话管控；若需代码变更由主会话串行追加给唯一 Luna 写者，其他代理不得顺手修改。各测试须能抓住相应失败正例，缺资源/权限则拒绝或 PARTIAL。不得删除原断言/skip掩盖失败，不调用模型、第三方安装或用户服务。C/P/M 分账。

核查发现（尚不当测试证据）：inline 快照尚未提交就被 assembly 读取；快照存储/权限类与最近裁定不一致；wire 尚未转发临时清单或 applyProfile，遗漏错误缺具名投影。由指定 Luna 修复与补反例，不先写快照绕过原子性，不新增 registry/dispatcher/实际配置缓存。

下一顺序：保留并验证/提交继承切片 → 核心配置缺陷与 PJ 核心反例 → 公开服务接缝 → 独立核心边界审查与多 provider 验证 → 原输入/任务读取接缝等核心剩余项。CLI/Skill/品牌扩展暂不抢先。此文件为执行分工与证据入口，不代替原规格或完成声明。

## 本轮实跑失败账（尚待末端复跑）

统一运行器：`PYTHONPATH=plugins/harness/codex/src:plugins/harness/pi/src:plugins/harness/claude-code/src:packages/backend/harness-transport/src:plugins/harness/records/src /home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml`。以下文件均在本 evidence 目录；不累计不同快照计数。

| 文件／阶段 | 结果 | 结论 |
| --- | --- | --- |
| test_core_profile_semantics.py 首红 | 8F、exit1、0.33s | inline 读取未提交快照、快照权限、无变化回执及公开错误缺口确实可抓住 |
| test_core_profile_wire_v3.py 首红 | 2P/2F/12E、exit1、0.23s | 12E 为跨模块 fixture 未注册依赖；由原测试作者修 fixture，不放宽断言 |
| 两文件联合，核心首修＋wire 尚未改 | 9P/15F、exit1、1.20s | 核心 6P/2F；2F 及多项 wire 红为测试直接序列化 mappingproxy；wire 真正缺转发亦保留红 |
| independence＋semantics 两文件 | 17P/2F/4E、exit1、1.67s | 核心 8 项全绿；新独立 fixture teardown 未定义变量、plan 顶层非 Mapping 错误待修。不能宣称多 provider 通过 |

追加写权仍互斥：core_impl 只追加现有 public 中两种错误同一性导出；review 仅写 test_core_harness_independence.py；其余共享契约没有代理顺手改动。根统一测试，Luna 编码；测试作者修上述夹具，生产代码不为错误夹具改变契约。

## 核心切片末端验证

本轮所有生产源码及新证据测试由三名 Luna 编写，主会话没有自行编写生产源码或测试。主会话负责读审、指导、统一运行、状态及显式 Git。独立审阅指出的具体反例已纳入：同 revision 下 actual/unknownItems 变化不得使用旧 applied；domain-only 请求不能被 OperationStore 的 UnknownResultError 当作新请求。

修改：inline 清单只在内存正规化参与原准备计划，快照与 reservation 同事务；快照独立命名空间/对象权限，读写权限均发前预检；omission 拒绝仅在原 env_requests 保存安全 ID 收据，不保存正文/快照，不占 scope fence；同请求重放先核原持久收据，同 key 修正正文拒绝；no-change 仅完整 owner 实际事实相符时使用 standing 证据，否则原 data-only unknown/refused；原 wire/1 薄绑定支持 /3 两种来源与 applyProfile，能力门控和具名错误保持原错误 family。

### 命令

在上文统一运行器后追加：

```text
docs/implementation/agent-tools/evidence/agent-unit-model/test_core_profile_semantics.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_core_profile_wire_v3.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_core_harness_independence.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_assembly.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_apply_profile.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_management.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_lifecycle.py
docs/implementation/agent-tools/evidence/agent-unit-model/test_wire_lifecycle.py
-q --tb=short
```

八文件串行联跑失败账：初 **126P/7F exit1、9.71s**（新 fixture 名称/冻结 JSON/ActivationReceipt、已用 data-only 请求误当 Operation 为主要失败）；追加边界反例后 **136P/1F exit1、10.07s**（新 ACL 发前零占用测试错误期待 Unknown，修为明确 None；已用拒单仍期待 Unknown）。末端 **137P/0F exit0、10.12s**，无 skip。新测试独立计数为核心16、wire16、两提供者及导入门11，共43；137 包含原测试，不累计快照。

独立两提供者测试使用真实临时 SQLite、单 Environment/CoreRegistry/AgentServices，提供者内部 record 与 positional command 格式不同；通过 prepare→配置作用→owner 读取，并验证一家 drain/retire 不影响另一家、错误身份/版本/缺能力均拒绝、静态禁导入扫描具注入正例。属于 C 契约证据；没有原生进程或真实模型，不能替代 P/M。

Luna 终审：三处 caught Unknown 后域读取 None 均重抛原异常，不进行空回退；旧确认与当前事实的完整通用比较闭合，无新增本切片阻断问题。旧 request identity／原 Store／原 owner／授权机制均沿用；未新建 registry、事实缓存、翻译层或 daemon。

当前剩余缺口（不报核心 DONE）：派发前重核失败仍可能留下 reserved 与已推进的基础快照；统一只读操作查询、托管输入公共装配与真实 writer/结果回写、required 材料装配、公开访问/连接等仍未闭环。统一查询范围与派发前拒绝的基础快照行为分别在 operation-read-proposal.md、pre-dispatch-refusal-proposal.md 提案，用户裁定前不实现。CLI/Skill、PJ 全矩阵、发行与真实任务继续 PARTIAL。

产品全套首轮回归（统一运行器＋`products/agent-tools/tests -q --tb=short`）**786P/1F exit1、215.71s**。唯一失败：test_lifecycle_cli.py 中旧测试断言健康 wire 不广告 applyProfile，本切片真实广告后 CLI 旧参数形状退出2。没有删掉该防线：授权 wire Luna 窄改原测试为真实 configuration 未装配情形，保留 capability refused／discovery-only／零副作用反例；另加健康 wire 广告而旧 CLI 参数被拒的反例。CLI 入口未改，不能据此宣布可用。末端尚待复跑。

本次追加唯一写域为 wire Luna 的 `products/agent-tools/tests/test_lifecycle_cli.py`，仅真实缺能力 fixture 和健康旧形状拒绝反例；生产 CLI 无写权，原核心及 wire 源码继续冻结。主会话没有自行改测试断言。

该 CLI 缺口的实际边界已核实：新 wire 广告 applyProfile，但 CLI 旧正文缺 baseProfileRef，WireClient 使用核心 schema 在发请求前返回 PARAMETER_INVALID／exit2；HTTP 只有 hello 和 capabilities，更新调用为零。新负例使用真实客户端，不改 client、不 stub 调用或伪造成功。原“未广告则 capability refused”防线改用首次真实无 issuer 装配，所有零占用／零作用断言继续保留。

定向 CLI（统一运行器＋`products/agent-tools/tests/test_lifecycle_cli.py -q --tb=short`）**99P/0F exit0、58.36s**。此句柄运行中作者在声明冻结后追加两条 provider 完全零调用断言，主会话明确停止其写入，未把这两条当作99项已验证证据；句柄终结后对最新文件按 `-k 'configuration_unassembled or healthy_wire_advertises_apply_profile'` 复跑 **2P、97 deselected、exit0、1.47s**。deselected 是定向选择，不是 skip；随后对冻结的最终文件再跑完整产品套件，才能收末端账。无生产源码在测试期间编辑。

测试修订独立 Luna 读审无阻断。末端测试完全真实客户端／HTTP，没有 core_call spy 或替身；先前审阅消息提及 wrapper 为已废弃的中间稿，主会话已纠正，不作为证据。

冻结最终源码／测试的产品全套：统一运行器＋`products/agent-tools/tests -q --tb=short`，**788P/0F exit0、217.70s**，句柄83852已terminal。相比前置787新增1个CLI反例；原负例保留并改为真实缺能力条件。137项 evidence 组合在前述源码快照已通过，之后仅改 CLI 测试及文档，生产源码未变。不能把这两组重叠测试计数相加作为独立验收数。

## 下一批依赖盘点（只读，不当实现／验收）

core Luna 核实：ResourceProvider／descriptor／CoreContributionSet及acquire/release/reconcile DTO已在原核心公共面，不能把 Agent 请求另包成CoreRuntime.submit，造第二 execution ledger。当前 Environment 缺 Agent 可消费的受控资源路由／声明到contract-provider映射。SecretRef／SecretPort短借契约已有，但 Agent 未组合其端口；现平台adapter也未证明按activation/target/generation的完整授权重核。解析后的材料传给 owner 的短生命周期、逐步权限与 unknown/crash/release 尚无闭环，暂只保持 required 拒绝／optional明确跳过。

wire Luna 核实：CapturedInputRef/Evidence、NativeInputState／SessionlessState、FirstInputObservation、ManagedInputReservations已存在，可在核心public面按同Environment一次性装配挂载；不能晚替换已有信任端口或另造issuer。生产捕获引用由原受控输入store负责；native state、原生帧、单次写入与回执解释由Harness/transport/records owner负责。claim_dispatch只发InvocationContext，未形成原生输入路由，Session关联也不是input effect证据。Production capture/state/writer/双来源恢复端口缺席时managedInput继续false；先挂类不等于端到端可运行。此盘点没有跑新测试、没有改源码、没有触及用户数据。
