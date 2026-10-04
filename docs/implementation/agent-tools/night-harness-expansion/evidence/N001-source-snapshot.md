# N001 源码快照收口记录

记录时间：2026-10-04（Asia/Shanghai）。执行者：本实施会话（029/030唯一执行者续接，worktree `agent-tools-product`，分支 `codex/agent-tools-product`）。

## 快照基线

- 批准基线 HEAD：`adce734db21945181bf93da9720158d05e957654`（030各工单 frontmatter 指定，`baseline_status=approved-base-with-uncommitted-implementation`）。
- 树状态：dirty。HEAD 本身**不是**完整实施源码快照；未提交成果为029会话（AT-001..AT-013）实施产物，与本夜工作同属一条执行线（夜间README「写权与源码快照」：由原执行者在原授权覆盖下创建本树检查点，不得stash/覆盖，不得仅拿旧HEAD冒充全部实施源码）。

## 未提交成果来源与路径摘要（收口前）

修改（7文件，+317/-10）：

| 路径 | 来源工单（029） | 内容摘要 |
| --- | --- | --- |
| `apps/server/src/ordessa_server/bootstrap/runtime.py` | server接缝（evidence/server-seams-*） | ServerRuntime `core_method_factory` 字段与核心方法epoch栅栏绑定/解绑 |
| `apps/server/src/ordessa_server/plugin_host/host.py` | 同上 | 插件id `pacthold.agents` 保留给核心方法工厂路径 |
| `docs/known-issues.md` | 基线回归登记 | Agent Tools基线回归红账登记（327P/3F等继承红） |
| `packages/backend/pacthold/src/pacthold/environment.py` | AT-001/002接缝 | 通用instantiate/预约释放口支撑 |
| `packages/backend/pacthold/tests/platform/test_n4r1_kernel_direction.py` | 方向扫描探针 | 探针指回core/dtos.py |
| `packages/backend/persistence-sqlite/src/ordessa_persistence_sqlite/store.py` | AT-002/007 | operation列增量迁移、scoped activity写保护 |
| `packages/backend/server-plugin-api/src/server_plugin_api/selection.py` | server接缝 | `core_method_factory` 选择字段 |

新增（未跟踪）：

| 路径 | 来源工单 | 内容摘要 |
| --- | --- | --- |
| `apps/server/src/ordessa_server/agent_core_wire.py` | R-0003 | agents.* wire/1 方法投影 |
| `packages/backend/environment-api/src/ordessa_environment_api/{domain,operations}.py` | AT-002/007 | DomainStorePort / OperationStorePort 合同 |
| `packages/backend/persistence-sqlite/src/ordessa_persistence_sqlite/operation_records.py` + `tests/test_domain_records.py` | AT-007 | 具名operation/Usage CAS实现与测试 |
| `packages/backend/pacthold/src/pacthold/agents/` | AT-003/006/008A | ProfileCatalog、DirectoryBindingRef、InvocationIssuer、agent_services |
| `plugins/workspace/src/ordessa_workspace/{directory_binding,public}.py` | AT-006 | DirectoryBindingService（未生产注册，登记缺口） |
| `plugins/harness/api/src/ordessa_harness_api/command_discovery.py` | AT-013 | Harness公开命令发现目录 |
| `products/agent-tools/`（34文件，build/dist/egg-info不入库） | AT-005/013 | CLI+Skill产品、测试、打包 |
| `specs/029-agent-tools-product/` | 029规格 | 产品规格 |
| `docs/implementation/agent-tools/` | 029实施账 | 工单/status/evidence/合同 |

写权依据：029工单 frontmatter `write_paths` 明确覆盖上述 packages/backend 路径（007：operations.py、persistence-sqlite/**；008：pacthold/agents/**、plugins/harness/** 等），R-0001 赋予主执行者独占Git。本夜030写权（plugins/harness/**、products/agent-tools/**、docs/implementation/agent-tools/night-harness-expansion/**）从本记录提交后追加。

## 凭据与用户数据扫描

- 对全部dirty/新增路径扫描 `token|secret|password|api key|bearer|credential|BEGIN PRIVATE` 模式：仅命中正常代码符号（`CredentialRecords` 导入、`writer_token` 参数、wire认证字段），无实际凭据值。退出0。
- 二进制扫描：products/agent-tools 下 build/、dist/、*.egg-info 为构建残留，`.gitignore` 已排除，dry-run 暂存34文件无一落入排除区；无 whl/so/exe 入库（AGENTS.md 规则4）。

## 快照提交策略

1. 检查点提交A（本记录之前）：029实施成果按上表精确路径提交，保留原作者成果原样（不重排、不改写）。
2. 检查点提交B：030/本夜材料（specs/030、night-harness-expansion/**）。
3. tag：`checkpoint/agent-tools-native-030-N001`（不覆盖既有 v1.x/v2.x tag；只在本地，不push）。

## 快照后运行前置核对（设计§6要求）

| 029前置 | 状态 | 证据 |
| --- | --- | --- |
| 节点准备(node prepare) | **缺失** | `pacthold/agents/profiles.py` capabilities 硬编码 nodes:False；AT-004/010 `queued-on-dependencies` |
| 公开管理入口 | **部分**（仅Profile数据面） | `agent_core_wire.py` agents.capabilities/profiles.*；无 nodes/managedInput 方法 |
| 原生session reservation | **缺失** | OperationStorePort 基础在（007，34P）但无生产调用方；AT-008结论：native session reservation/transport fence/native journal 缺席 |
| InputAttempt | **缺失** | 全仓代码零匹配，仅029文档术语；011 `queued-on-dependencies` |
| transport fence | **缺失** | 同AT-008登记；核心方法epoch栅栏存在但不是原生transport fence |

结论：030运行接纳链（L2生产运行接入、runtimeReady）标**依赖阻塞**；按设计§6「十家资料研究、许可/version核对、纯协议/配置编译反例可以继续」推进，不另造core/ledger绕过，不发布runtimeReady=true。
