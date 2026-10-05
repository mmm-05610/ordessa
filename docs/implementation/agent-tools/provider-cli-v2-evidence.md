# Provider CLI 与显式 v2 服务证据（PARTIAL）

日期：2026-10-05。前置 c7ca893cbfa1b58eb5c543282788e6028f54384f。
主会话持有全部共享源码、测试、Git 与账本写权；au003_codex 仅只读终审，其他家族无在跑写者。保留原三家修复。没有更改 AU 合同或核心 wire 协议。

## 实现与边界

CLI 增加 providers list/describe；describe 接受完整 DefinitionRef JSON 或 @文件。先核验 agents.capabilities，再消费明确公开的 v2 方法。v1 Profile 行为保留，v1 Provider 查询拒绝，不回退旧接口。校验版本、digest、JSON 类型、advertised methods、完整环境/activation/generation/DefinitionRef、provider 方法闭集、重复引用及敏感 token。输出仅 providerRegistryObserved/runtimeVerified=false，不证明 native 二进制、执行授权、会话或模型可用。

构建时通过 pacthold.agents.public 生成 v1、v2 schema 和 public RuntimeProvider Protocol/Descriptor 的方法镜像；运行时 stdlib-only，未导入 Server/Harness/core。这里没有发布新核心合同。可选服务明确选择 agent-assembly/2，仅给 local 对精确 agents.runtime 对象读权限；不加载提供者、不发 Directory/Invocation 授权，不授 execute。默认 v1；未知版本或配置/装配版本不一致在数据根访问前拒绝。

CLI wheel 排除 native_clients；显式 package-data 保留三份 schema 和二进制发现目录。实际 bundle 从临时洁净源码构建，拒绝品牌客户端与后端依赖，验证三份镜像及校验和。产品源码旧 native_clients 仍保存，三家源码所有权迁移与另外七家成果核对尚未完成，不能以 wheel 排除替代 AU003 完成。三个 Skill 本轮未重写。

## 验证分类

下列命令中的 PY 是 /home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python。主会话串行执行，所有测试句柄 terminal。

- `PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_provider_cli.py products/agent-tools/tests/test_profile_cli.py products/agent-tools/tests/test_discovery.py products/agent-tools/tests/contracts/test_profile_wire.py products/agent-tools/tests/test_distribution.py products/agent-tools/tests/test_bundle.py -q --tb=short`：90 passed，exit0，34.26s。含实际 CoreRegistry/handlers 的受控 HTTP 契约；该 fixture 不算真实 Server。发行测试构建自己 wheel，fresh venv 无网络/no-deps 安装，再独立 CLI 进程查询，不安装第三方。
- `PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration/test_agent_deployment.py products/agent-tools/tests/integration/test_profile_service.py -q --tb=short`：17 passed，exit0，6.38s。含真实独立 Uvicorn Server、临时数据根、独立 CLI 进程。显式 v2 空 registry 成功，无效 token/缺席 DefinitionRef 拒绝，nodes/input/config/preparation 都 false。默认 v1 既有生命周期仍通过。自己启动的隔离服务由测试停止，不触及用户服务。
- 完整集成命令为下述代码块：511 passed，exit0，29.84s；原507+新4。Core/SQLite 与实际 Python pipes 以及受控 owner 证据，不等于真实 Harness P 或模型任务 M。
- 最后新增 @文件安装 describe 及缺席引用 AUTHORIZATION_REFUSED 严格断言后复验：`PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_distribution.py products/agent-tools/tests/integration/test_profile_service.py::test_real_http_v2_provider_discovery_has_no_native_readiness_or_execution -q --tb=short`：3 passed，exit0，5.76s。源码行为未再改变。

```sh
PYTHONPATH=plugins/harness/codex/src:plugins/harness/pi/src:packages/backend/harness-transport/src /home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration docs/implementation/agent-tools/evidence/agent-unit-model/test_assembly.py docs/implementation/agent-tools/evidence/agent-unit-model/test_codex_assembly.py docs/implementation/agent-tools/evidence/agent-unit-model/test_provider_discovery.py docs/implementation/agent-tools/evidence/agent-unit-model/test_preparation_holds.py docs/implementation/agent-tools/evidence/agent-unit-model/test_management.py docs/implementation/agent-tools/evidence/agent-unit-model/test_invocation_continuation.py docs/implementation/agent-tools/evidence/agent-unit-model/test_sessionless_input.py docs/implementation/agent-tools/evidence/agent-unit-model/test_input_session_association.py docs/implementation/agent-tools/evidence/agent-unit-model/test_first_input_publication.py docs/implementation/agent-tools/evidence/agent-unit-model/test_first_input_journal_publication.py docs/implementation/agent-tools/evidence/agent-unit-model/test_prepared_input_claim.py docs/implementation/agent-tools/evidence/agent-unit-model/test_codex_configuration_barrier.py -q --tb=short
```

本轮新增23项：Provider17、v2 Profile1、bundle反例1、部署3、真实隔离服务1；两个原发行测试加强，不额外计数。各组合快照不累加。首次发行排除只配置 package-find 时1P/1F exit1、1.11s，setuptools package-data 仍包含旧客户端；保留拒绝断言并设置 include-package-data=false 后2P exit0、4.54s。首次部署15P/1F exit1、6.68s，测试误期望缺席引用 NOT_FOUND4；实际核心 AdmissionRefused/FORBIDDEN 映射3，修为严格 AUTHORIZATION_REFUSED3，未改协议或放宽为多个错误。

公开镜像生成检查 exit0；五张工单 strict exit0；diff-check exit0。它们仅资料/格式门。本轮未改 core 或三家原生包，不声称历史 Core269P/3F 已解决；三个已登记 kernel_direction 具体SQLite导入扫描失败仍红。

## 剩余与禁止项

AU002/003/004/005 均未 DONE。生产 capture 保存/原字节读取、receipt/effect/Session owner、Directory/Invocation/lease 配置、材料/SecretRef、完整冷恢复/生命周期、三家旧 bundle/factory/Server 迁移、CLI 节点/配置/任务/结果与三个 Skill 仍继续。缺原生资源保持 ABSENT，真实 Harness P 未验证，真实模型 M0。未更新第三方、改用户数据库/凭据/全局配置、登录、重启用户服务、push 或合并主树。费用 unknown。检查点后继续，不因本切片验证通过收窄总目标。
