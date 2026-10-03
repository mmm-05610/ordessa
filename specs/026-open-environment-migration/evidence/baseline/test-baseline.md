# 001 T001-05 — 受控测试基线（逐 ID/原因）

日期：2026-10-03。执行目录：本 worktree 根。HEAD：`ebe712c796…`。
工具链：node v22.22.1 / npm 9.2.0；Python 3.12.14（.venv，未激活直调
`.venv/bin/python`）；Go 1.24.13 linux-amd64（钉版路径）。
全部命令离线受控：零真实模型调用、零真实用户数据、零用户服务操作。

## Python（串行，repo 根 cwd）

| suite | 命令 | exit | 结果 |
| --- | --- | --- | --- |
| packages/pacthold | `.venv/bin/python -m pytest packages/pacthold -q` | 0 | **218 passed / 0 failed / 0 skipped**（VERDICT=GREEN_NO_SKIPS） |
| plugins/harness | 同上 | 1 | **3 failed / 840 passed / 3 skipped / 37 subtests** |
| apps/server | 同上 | 1 | **76 failed + 2 errors / 1177 passed / 9 skipped**（78 个失败 ID 全列于 server-red-ids.txt） |
| plugins/runtime-compat | 同上 | 0 | 163 passed（单独跑） |
| plugins/server-compat | 同上 | 1 | **2 failed / 7 passed**（`test_controlled_peer_opt_in.py` 两参数例） |
| tests/integration/acp_orchestration | `--continue-on-collection-errors` | 1 | 28 failed / 31 passed |

### harness 3 红（与 known-issues 台账继承集一致，未新增）

1. `install/test_acp_schema_drift_target.py::test_a_root_override_of_the_schema_does_not_violate_a_declaration_in_the_closure` — 继承（npm closure override vs declaration 漂移，台账行）。
2. 同文件 `::test_the_acp_schema_a_closure_carries_satisfies_the_adapter_that_needs_it` — 继承（同上）。
3. `install/test_packaging_boundaries.py::test_the_run_chain_declares_no_byte_ceiling_of_its_own` — 继承（MAX_BYTES 政策冲突，台账行，需 owner 裁决）。

注：`test_native_verifier_deployment.py::test_wheel_contains_original_policy_without_source_tree` 在
setuptools 缺失时红（ModuleNotFoundError: setuptools）——**环境前置**，装入后消失，不计红。
venv 未激活直调 ⇒ 与台账"未激活"形态对应（不出现 external_adapter build-isolation 3 errors）。

### apps/server 78 红分类（逐文件计数见 server-red-ids.txt）

- **钉面漂移 10 ID（已验证机制）**：默认组合 live 广播 **88** 个 wire 方法，两处钉面按 86：
  `test_plugin_host_gate.py` 9 红 + `platform/test_platform_t023_wire_loopback.py` 1 红。
  实测 `build_runtime().wire.hello()` 返回 88 caps；`test_plugin_host_gate` 公式 70+2+11+2+1=86。
  与 known-issues"wire-surface pin 是持续义务"同类：**2026-10-02 复测（64F）之后的提交增加了
  方法未同步钉面**。多出的 2 个方法精确归因 UNKNOWN（候选：modelProvider next-turn 面新增，
  002 identity-map 将逐方法列表并闭合此问题；方法=合同台账 diff live caps vs T002 基线清单）。
- **worker-entry/sidecar 退役链继承**：test_cli_server_flags_s4(14)、test_sidecar_native_driver(11)、
  test_sidecar_upstream_cause_150(4)、test_first_run_lock(3)、test_terminal_reason_consumer_134(3)、
  test_native_cli_hd002(2)、test_delegation(2)、test_native_bootstrap_identity_hd002(1)、
  test_cancel_recall_flake_087(1)、test_import_asset_request_id_129(2) 等 —— 对应已知继承红
  台账（bc-native 冻结基线本身 97F+25E；hd004 裁决不复活 compat 链求绿）。
- **scope-reds（裁决保留）**：test_placement.py 4 ID（sandbox/WSL/SSH 退役插件缺席→typed refusal）。
- **其余单例**（test_wire_v1×3、wire_error_families×2、test_accounts、test_asset_hubs、
  capability_truth_table×2、harness_capability_projection×2、subagent_harness_round_086×2E 等）
  与迁移期继承台账类别一致；2 errors 在 subagent_harness_round_086（fixture 桥链）。
- 判定：与 2026-10-02 干净复测（64F/2E/1187P）相比 **+12F/−10P 全部由钉面漂移 10 ID +
  wire_v1/发现面漂移 2 ID 构成**，无环境性新红；精确逐 ID 逐一归因未完成（继承类别覆盖），
  缺口如实登记，不据此宣布任何通过。

### server-compat 2 红（已验证机制，真产品 HEAD 红）

`test_controlled_peer_opt_in.py::test_only_explicit_opt_in_forwards_fixed_test_mode[False/True]`：
生产侧 `composition.py:655` 以 `native_identity_for=` 调 `AcpChannelServerPlugin`，测试 capture
签名仍收 `native_identity=` → TypeError。归因：commit `69c0ea2818`（"Compose Pi Codex and Claude
in the native Desktop product"）改 kwarg 未同步该测试。

### acp_orchestration 28F/31P

与 2026-10-02 verify-clean 复测（31P/28F）**逐计数一致**——worker-entry 退役裁决红，保持可见。

## Go（桥）

`go test ./...`（acp-adapter）：7 ok / 3 no-test-files，exit 0。含 test/integration 60.9s。

## JS（根聚合 `npm test`）

环境修复后（见 suite-discovery.md 环境前置节）：**33/41 绿，8 红**：

| suite | exit | 原因（已验证/归因） |
| --- | --- | --- |
| node-test:products/desktop | 1 | 36P/1F：`native-profile-defaults.test.mjs` 钉 `profile-pi-registration-owner-bound`，实际默认 `profile-pi-startup-admission-v2`（`native-product-plan.mjs:9`）。**同提交 865f3ab45f 同时写入新 plan 值与旧测试钉值** —— 产品 HEAD 真 红 |
| rig:tests/integration/acp-connector | 1 | 80P/1F：`acp-conversation.test.tsx` U1 期望按钮 textContent '发送'，实际 '↑发送'（`chat-page.tsx:461` 改为 `↑ + sr-only 发送` a11y 标记，865f3ab45f）。rig 未跟 —— 产品 HEAD 真 红 |
| electron:test:electron/extensions/agent-ui/agent-shell/ui-service/ui-foundations | 1×6 | 统一根因：`resolveBundledRuntime` 报 `the bundled runtime is incomplete: python, bin` —— 本机 /opt/ordessa 仅有 harnesses/（无 python/、bin/）。**环境前置缺失**（需安装产品运行时=系统安装，001 未授权）；021 记录（2026-10-01 安装态）中这些腿为绿。ui-preview 绿（不依赖 server runtime） |

注：`node-test:plugins/harness/packaging` 初跑红（claude/provider-session ERR_MODULE_NOT_FOUND）
为本地闭包未装，`plugins/harness/packaging/claude` 内 `npm ci` 后 **exit 0 绿**，不计红。
ui-preview 本轮 PASS（021 记录中的已知红为截图字节不稳/预览时序类，DOM 断言权威不变）。

## 汇总判定

- 绿：pacthold、runtime-compat、Go 桥、JS 33 套件（含 packaging、ui-preview）。
- 产品 HEAD 真 红（继承，待后续工单在触碰对应区域时修复，不在此修）：
  apps/server 钉面漂移 10 ID + 继承台账 68 ID、server-compat 2 ID、products/desktop 1 ID、
  rig 1 ID、acp_orchestration 28 ID（裁决保留）。
- 环境前置缺失（本机不可验，非产品红）：electron 6 腿。
- **没有删除任何断言、没有 skip 求绿**；setuptools/闭包装入为环境修复非断言操纵。
