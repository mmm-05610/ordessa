# W1 证据：零配置启动 + 身份 + Profile 远程生命周期（2026-10-21）

状态：**W1 基础门已复现通过（源码/可执行层）**；尚未做非 editable 安装闭包门（见 §5）。
基线：`codex/agent-cli-server-20261020` @ `cc16115811` + 本轮工作区改动（未提交）。
环境：`.venv-w1`（Python 3.12.14，52 个本仓发行，其中 `ordessa-interfaces`/`ordessa-interfaces-contracts` 以 wheel 安装，原因见 §4 缺陷 B）。

## 1. 零配置启动（真实命令与输出）

```
$ .venv-w1/bin/ordessa-server --data-root /tmp/w1-e2e/root --port 48765
stdout: {"event":"listening","origin":"http://127.0.0.1:48765","pid":...,"serverId":"ordessa-c2bd0ffb"}
stderr: ordessa-server: data root /tmp/w1-e2e/root
        ordessa-server: instance token /tmp/w1-e2e/root/secrets/http-token (generated, 0600)
        ordessa-server: capabilities profiles
        ordessa-server: harness admitted kilo, pi, claude, codex, hermes, dsh
```

生成的文件（未预置任何配置）：

```
/tmp/w1-e2e/root/.agentbox-server-root
/tmp/w1-e2e/root/secrets/http-token          (0600, 自动生成)
/tmp/w1-e2e/root/server.lock
/tmp/w1-e2e/root/state/profiles.sqlite
/tmp/w1-e2e/root/state/profile-fingerprint.key (0600)
/tmp/w1-e2e/root/state/agent-owner/agent-instances.sqlite
```

## 2. 零配置客户端（无配置文件、无环境变量、无 token 操作）

| 命令 | 退出码 | 结果 |
| --- | --- | --- |
| `ordessa --data-root <root> agents profiles list --json` | 0 | `completed`, `entries: []` |
| `ordessa --data-root <root> call profiles.capabilities --input {}` | 0 | `completed`，返回 profile 契约与支持方法 |
| `ordessa --data-root <root> agents profiles create demo --name Demo --manifest <m1>` | 0 | `catalogRevision: 1` |
| `ordessa --data-root <root> agents profiles edit demo --manifest <m2> --expected-catalog-revision 1 --base-manifest-ref <ref1>` | 0 | `catalogRevision: 2`（CAS 生效） |
| 第二个独立进程 `agents profiles list` | 0 | 读到 revision 2（跨进程一致） |
| `ordessa --data-root <root> environments list --json` | 4 | `CAPABILITY_UNSUPPORTED`（未注册能力不可发现/不可调用） |

Profile manifest 使用 `environmentNamespace=server, definitionId=kilo, revision=0.1.0a1`，由**已安装并 pin 的 Kilo provider** 校验通过 —— 说明 harness catalog 与 Profile 校验链在 Server 侧真实工作。

## 3. 身份与生命周期

| 场景 | 结果 |
| --- | --- |
| 错误 token（显式 client 配置，`tokenEnv` 指向错误值） | 退出码 2，`PERMISSION_DENIED` |
| 删除 `<root>/secrets/http-token`（运行中） | 退出码 4，`AUTHORITY_UNAVAILABLE`（无需重启即撤销） |
| 恢复 token 文件 | 立即恢复 `completed`（覆盖即轮换） |
| 同根第二个 `ordessa-server` | 退出码 2，`DATA_ROOT_IN_USE`（无 traceback） |
| SIGTERM 第一个实例 | 进程退出（3 秒内） |
| 同根重启 | 成功，banner 显示 token `(reused, 0600)`，`serverId` 稳定（由根路径派生） |
| 重启后 CLI | `completed`，数据保留 |

## 4. 本轮发现并处理的 HEAD 缺陷

**A. 安装命令在 HEAD 上直接失败（已修）**
`python_workspace.py --install` 报 `workspace metadata drift: apps/cli`：`apps/cli/pyproject.toml=0.1.0a3` 而 `python-workspace.json=0.1.0a2`。已把 workspace 清单同步为 `0.1.0a3`；修复后 52 个发行全部安装成功。

**B. `ordessa_interfaces` 命名空间在 editable 安装下被劫持（未修源码，已用 wheel 规避 + 登记）**
`ordessa-interfaces` 与 `ordessa-interfaces-contracts` 同时提供 `ordessa_interfaces.*`（后者提供 `system_access/contracts`）。editable 安装时 setuptools 的映射 finder 让其中一份不可见，`system_access` 落到错误片段 → `ImportError ... (unknown location)`，7 个测试模块无法收集。
本轮处理：验证 `ordessa-interfaces`/`ordessa-interfaces-contracts` 改用 **wheel 非 editable 安装**后全部子包可导入（本证据即在该环境取得）。源码层修复（让 `ordessa_interfaces.system_access` 及其 `contracts` 子包归属单一发行）留到 W8 发行收敛，已登记 `known-issues`。

## 5. 仍未完成 / 不宣称

- **非 editable 安装闭包门（S-09/T04-A 发行门）**：尚未对"默认安装闭包不含 Units/Engineering/bindings"构建独立 venv 并跑正例+植入反例。当前仅完成源码层装配与运行验证。
- 尚未把本仓库的 `apps/server` 依赖切割结果放进安装产物验证（editable 环境里 units/engineering 仍装在同 venv）。
- Profile 的 `preview` 仍为 `unresolved`（设计如此）；archive/restore/clone 未逐项跑（W1 只要求 create/edit/read/list）。
- 工具权限、长操作、environments、decisions 均未在本轮验证。
- `apps/server/tests` 收集仍有 96 个 error（基线 96，未新增）；`tests/architecture` 3 个收集 error、`apps/cli` 1 个既有失败（`test_decisions_validate_run_query_evidence`）均与基线一致，未修。

## 6. 回归数字（同一 venv）

| 集合 | 本轮 | 基线（HEAD） |
| --- | --- | --- |
| `packages_convergence` 3 文件（entrypoint / default_agent_registry / registry_http_unblocked） | **6 passed / 0 failed / 0 skip**（VERDICT=GREEN_NO_SKIPS） | 6 passed |
| `apps/cli/tests` | 91 passed / 1 failed（既有 `decisions` 失败） | 91 passed / 1 failed |
| `tests/architecture` | 3 collection errors（既有） | 3 collection errors |
| `apps/server/tests --collect-only` | 916 collected / 96 errors（既有） | 916 / 96 |

本轮为迁移旧前提而更新的测试：`test_server_http_entrypoint.py` 的"无配置即拒绝"改为"显式配置非法即拒绝且零写盘"（零配置已成为默认路径）；`test_lower_cli_flow.py` 的"无模式选择器报错"改为"默认目标不可达的确定性拒绝"。断言未删除、未加 skip。

## 7. 原始输出

`raw/`：`s1.*`（首启）、`s2.*`（同根第二实例拒绝）、`s3.*`（重启）、`cli.json`、`c1.json`（capabilities）、`c3.json`（create）、`n1/n2/n3.json`（错 token / 删 token / 恢复）。

## 8. 附：与本轮改动无关的既有运行时红

- `apps/server/tests/test_data_root_c01.py::test_the_kernel_clis_do_not_resolve_a_server_data_root` 因 `pacthold`
  在本树不存在而失败（HEAD 既有，属退役后遗留引用）。
- `apps/server/tests/test_brand_boundary_core.py::test_no_host_source_names_a_harness_brand_outside_the_registered_debt`
  报告 `apps/desktop/packaging/build-deb.mjs` 含 `claude`（HEAD 既有，desktop 未改）。
两者都不由本轮改动引入；未修改测试、未加 skip。
