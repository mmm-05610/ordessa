# wire 生命周期绑定＋apply_profile 核心派生（PARTIAL）

前置 `efb2b18dcf`。主会话唯一共享/Git/账本写者；wire 切片由品牌无关 slice-worker 完成（写权已释放，含一次只读 diff/status 申报），apply_profile 与客户端键集修复由主会话并行完成。真实模型 0；无用户数据/服务/push/主树合并。

## wire 生命周期绑定（评审 3 清单第 3 项）

`agent_core_wire.py`：stop/release/recover 处理器（`catalog.request_key(requestId)`＋nodeRef＋preconditions→`services.lifecycle.<action>`，直接返回 lifecycleOperation 投影）；**形状校验补 preconditions dict 检查**（原仅 context/options）；supportedMethods 门控 `(action∈{stop,release,recover} ∧ supports.nodeLifecycle is True)`；错误映射零新增。`schema.py` 管理块新增 `lifecycleOperation` 形状（operationRef/revision/status/action＋statuses 枚举）；镜像经生成器再生成并两次核验（新 digest 71113ddb…）。`test_management.py` 原"stop 必 CAPABILITY_UNSUPPORTED"守卫**改写而非删除**（评审红线）：未装配 lifecycle 端口时三方法仍 CAPABILITY_UNSUPPORTED、不广告、零 reserve，新增 supports.nodeLifecycle is False 断言；新文件 `test_wire_lifecycle.py` 8 项（未装配参数化守卫、已装配正例、preconditions 非 dict→INVALID_REQUEST、effectful 未知→OUTCOME_UNKNOWN 不授权重试、重放幂等）。

## apply_profile（评审 3 裁定签名）

`AgentConfiguration.apply_profile(request, node_ref, profile_ref, expected_configuration_revision, application_policy)`：声明**永远**取核心侧 `profiles.read(profile_ref).content["declarations"]`（正文无法携带——schema 必填集无 declarations 且 additionalProperties False）；构造 ConfigurationChangeRequest 后走既有 apply 幂等链。A11 天然满足。反例 `test_apply_profile.py` 6 项：声明来源＝核心快照、同请求异内容 CONFLICT 且不二次派发、目录零回写（A11）、版本不符 CONFLICT_VERSION 零派发、外域/坏引用拒、空声明派发前拒。

## 连带修复（主会话域，单根因）

客户端 `negotiate` 的 v2 supports 键集硬编码旧五键——契约合法扩展 `nodeLifecycle` 后 138 项连带红（CORE_RESPONSE_INVALID）。修复：client.py 键集补 `nodeLifecycle`（一行）＋两处测试夹具/断言的精确键集跟随契约（test_profile_cli 假服务、test_profile_service 精确断言补 `nodeLifecycle: False`，未装配语义不变）。断言未放宽、无 skip。

## 验证（串行、terminal；解释器 .venv-ordessa-py312/bin/python）

| 命令 | 结果 |
| --- | --- |
| `… -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests -q`（全产品含 CLI/契约/发行/真实 HTTP） | **689P/0F exit0** |
| `… test_management.py test_wire_lifecycle.py test_lifecycle.py test_apply_profile.py -q` | **65P/0F exit0** |
| `… -m pytest -c packages/backend/pacthold/pyproject.toml packages/backend/pacthold/tests -q` | 269P/3F（同三个已登记 kernel_direction 继承 ID，无新增） |
| `… test_native_unit_confirmation.py test_unit_records.py test_unit_configuration_records.py test_operation_journal.py -q` | 115P/0F |

wire 子代理独立报告：51P（management 43＋wire 8）先绿、全证据目录 391P 复核；镜像两次核验 exit0。失败账：wire 二次投影 OUTCOME_UNKNOWN 2 项（改为直接返回投影）、客户端键集连带 138 项（上述单根因修复）、两处测试夹具/断言键集跟随契约；均非断言放宽。

## 边界与剩余

C：真实临时 SQLite/Core/Issuer＋受控 owner；P/M 无新增。评审 3 清单剩余：CLI 生命周期命令（stop/release/recover/apply-profile 的薄客户端命令＋skills 同步）、三家消费终止族与停止/释放效果证据、preconditions 白名单扩展（acquireAccess 切片）。评审注记保留：lifecycleOperation 的 node 恒为核心 None 未入 required（如客户端需严格键集校验再补并再生成）；build/lib 过期副本不作发布依据。
