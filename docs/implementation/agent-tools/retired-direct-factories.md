# 三家旧直接工厂退役证据

2026-10-05；前置 `7f7332b288ec6d0bd353245286d9ae4075b67d25`。AU003 局部结果，整体 PARTIAL。

本树现存 factory/plugin/test_retired_direct_factories 修改均为主会话上一切片未提交成果，保留后继续；live agents 均 completed，没有另一共享写者。主会话唯一源码、测试、Git、账本作者，Codex 只读复查。未改合同、稳定 family/provider/data 标识或三家独立协议实现。

## 行为与范围

自动 entrypoint 删除不足以退役直接调用。旧 `generic.factory.build_registration(context, family)` 对 codex、pi、claude-code 在 registry/context/storage/runtime 构造前抛公开 `GuaranteeUnavailableError`。原 named factories 与默认 create_plugin 经该口拒绝；HarnessesPlugin.build 显式拒绝，退出原 credential 注册旁路。没有 fallback、shim、新 provider 字典或原生副作用。

旧 descriptor 与 continuation 合同仍可读取，已有标识不改。未迁移 opencode/hermes/dsh/kilo 的四条旧 generic factory 和 ProfileStore 入口保持原注册行为；测试正控只证明构造，不宣称这些家族生产可用。它们不是 products/agent-tools 内暂存的另外七家客户端，两种计数不能混用。

旧 Codex 两个正注册测试要求退役的 compat ExecutionProvider、control、selector 仍然注册，与 AU003 目标冲突。测试改为稳定 descriptor、typed refusal、无任何目录写；continuation 两个正例不变。新独立 Codex 的正注册/Unit/Node 发布通过原 CoreRegistry/Sqlite/UnitRecords 测试复跑，不能以旧注册替代新提供者，也不能靠禁用全部路径获得绿。

## 实际测试（主会话串行）

解释器 `<PY>` 为 `/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python`。所有命令终态，无尚在运行的测试句柄。

1. 退役反例初始、源码 guard 前：

   `<PY> -m pytest -c plugins/harness/pyproject.toml plugins/harness/tests/test_retired_direct_factories.py -q --tb=short`

   0P/8F，exit1，0.20s。八条旧路径访问 agent_box_home，触发 NoContextAccess；这是修改前证据。

2. guard 后、旧正注册测试尚未调整：

   `<PY> -m pytest -c plugins/harness/pyproject.toml plugins/harness/tests/test_retired_direct_factories.py plugins/harness/tests/test_core_identity.py plugins/harness/tests/test_codex_plugin.py plugins/harness/tests/test_codex_wiring.py -q --tb=short`

   38P/2F，exit1，0.61s。两个旧 Codex positive registration 用例被 typed refusal 拒绝，其旧期待按上述架构迁移；没有 skip 或恢复 compat。

3. 加四个未迁家族及 ProfileStore 正控、调整旧测试后，同上一命令：

   41P/4F，exit1，0.76s。主会话新正控误用不存在的 HarnessDefinition.provider_id；按原 GenericExecutionProvider 稳定 ID family+'-execution' 修正，未修改运行源码或宽化断言。

4. 最终定向组合（上一命令增加 `plugins/harness/tests/test_generic_profile_store.py`）：

   47P/0F，exit0，0.70s。包含13项新 factory 门（8拒绝、4未迁家族构造、1ProfileStore），既有身份/import-order、迁移后的旧metadata/continuation、原Profile修订与secret拒绝。

5. 新提供者实际正向与反例、wheel metadata：

   `PYTHONPATH=plugins/harness/codex/src:plugins/harness/pi/src:packages/backend/harness-transport/src <PY> -m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_codex_assembly.py docs/implementation/agent-tools/evidence/agent-unit-model/test_retired_family_discovery.py products/agent-tools/tests/integration/test_runtime_admission.py -q --tb=short`

   33P/0F，exit0，5.09s。包含真实 Core/SQLite/UnitRecords + 受控 native client 的原Unit与Node对应、unknown不二次launch、请求身份冲突、撤权；以及 fresh 自有旧包 wheel/venv 的自动 entrypoint 缺席和公开 runtime admission。没有安装或运行第三方 native binary。

以上快照不累加，都是 C；wheel 构建/安装亦不能证明 native P 或任务 M。M0。

只读审阅发现 GenericExecutionProvider 构造器还允许绕过 factory 直接传三家 definition。主会话补同型拒绝及3条实际 builtin definition 反例；全树直接构造消费方只有 generic.factory。最终复跑第4条组合：50P/0F，exit0，0.67s（新16门）；其他33项在此额外构造器修改前已跑，不冒充修改后的完整组合。审阅者未运行测试或写文件。

## 剩余与退出条件

旧 configuration/model plugin/bridge/live_service、Server.native_runtime 与 server_acp 的三家路线仍待迁；本门不证明它们已经关闭。旧品牌配置、附件、材料和生产模板有独有能力，不整目录删除或冒认新包已承接。后续先迁这些消费者到独立提供者所有权，再删除旧执行路线。

生产 Directory/Invocation/lease/capture/receipt/effect/Session owner、SecretRef材料、冷恢复与完整生命周期、节点公开绑定、未知操作按请求键恢复、tasks/results、三个Skill及全纵向发行验收仍缺。历史 Core269P/3F 未本轮修复或复跑；资源缺席仍 ABSENT。不能以定向47/33通过声明 AU003_DONE。

未改用户数据库、凭据、全局配置、登录、用户服务；无模型调用、第三方安装更新、push 或合并主树。成本 unknown。
