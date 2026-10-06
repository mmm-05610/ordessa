# AgentLifecycle 核心协调器（stop/release/recover）检查点（PARTIAL）

前置 `eb354763d0`。主会话唯一共享写者；实现严格按 architecture-reviewer 第 3 次咨询裁定（release 受控释放接缝落点、核验栈顺序、A13 同一性字段、apply_profile 签名与 wire 门控清单）。真实模型 0；无用户数据/服务/push/主树合并。

## 实现面

`pacthold/agents/lifecycle.py`：`AgentLifecycle(environment, nodes, *, invocation_issuer, observation_port)`＋`LifecycleObservation`（冻结 DTO）＋`LifecycleObservationPort`。operation kind 各一（agent-stop/agent-release/agent-recovery），单步（step_id=action）；stop/release 为 cleanup 调用（targetRef=nodeRef）、recover 为普通调用（binding 取 Node 持久绑定）；同 requestId 同内容重放只读原操作、异内容 CONFLICT；claimed 步永不重发。`capabilities()` 沿"issuer 同 store＋观察端口＋fingerprint"钉法产出 nodeLifecycle。public.py 的 AgentServices 增 lifecycle 字段并按 compose-once 守卫注册（lifecycle_observation_port 一次性注入，缓存后换口拒绝）。

核验栈（评审裁定顺序）：issue（invocationBindings 与 directoryBindingRef 取自 Node 持久绑定）→ provider 调用 → `verified_consumption` → 观察端口四元组（step/provider/inputDigest/recoveryCorrelation）＋ evidence owner 出处 → 终止投影比对（version/action/state=confirmed/identity.unitRef 与本 Node Unit/identity.inputDigest 与本 step）或 recover 的 A13 字段比对（harnessUnitRef/nativeSessionRefs 精确集合/configurationTargetRef/harnessProviderRef）→ 同事务 record concluded（release 附释放变更＋release_holder）；任一失败 step unknown 空证据、零释放。release 预检：释放集必须恰为 Node 的 active publication Usages（read_usages CAS 视图），不符在派发前拒绝。

## 反例（test_lifecycle.py，8 项，复用 test_assembly 真实装配＋受控 provider/owner）

stop 结论带属主终止证明＋同请求重放不重派；效果失败→unknown 且回执丢失不重发；错 correlation/错 unit→unknown 非 concluded；终止投影 unknown→step unknown；release 精确 active 集→释放并结论、重放幂等、新请求对已释放集派发前拒；recover 伪造 nativeSessionRefs（A13）→unknown、原绑定→concluded；preconditions 非 Mapping/未知键拒且零调用；未组装观察端口→nodeLifecycle=false 且 typed 拒。

实现修正（测试侧/结构侧）：context_ref 补 environmentNamespace 与 directoryBindingRef（签发器固定绑定要求）；幂等重放先短路于释放预检；unknown 效果的 operation 状态如实为 unknown。断言未放宽、无 skip。

## 验证（串行、terminal；解释器 .venv-ordessa-py312/bin/python）

| 命令 | 结果 |
| --- | --- |
| `… test_lifecycle.py -q` | **8P/0F exit0** |
| `… products/agent-tools/tests/integration -q` | 312P/0F exit0 |
| `… packages/backend/pacthold/tests -q` | 269P/3F（同三个已登记 kernel_direction 继承 ID） |

## 边界与剩余

C：真实临时 SQLite/Core/Node 发布/Issuer＋受控 provider/owner；P/M 无。按评审 3 清单剩余：wire 生命周期绑定＋schema lifecycleOperation 结果形状＋镜像再生成＋test_management 守卫**改写**（未装配仍 CAPABILITY_UNSUPPORTED 语义保留，不删）；apply_profile 核心派生＋CLI；三家消费终止族与停止/释放效果证据；preconditions 白名单随 acquireAccess 切片扩展。评审已注记的 build/lib 过期副本不作发布依据；release 不删 Node 发布行（消费面是 Usage 状态＋lifecycle operation）。
