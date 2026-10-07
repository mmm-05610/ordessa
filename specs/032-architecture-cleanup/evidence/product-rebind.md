# 产品装配切核心公开绑定 — 验证证据（Phase 2c）

日期：2026-10-07。对应 plan.md §2/§5 与 migration-map §1/§2/§8。

## 变更

1. **产品 wire 绑定（不提供旧类名转发壳）**
   - `products/server/src/ordessa_server_product/agent_wire_plugin.py`：原 AgentDomainPlugin 的 14 个 `agent.*` wire 方法面移入产品，类名 `AgentDomainWirePlugin`，PLUGIN_ID `ordessa.agent` 不变；owners/journal/service/observation 全部改从 `pacthold.agents.submissions.*` 与 `pacthold.agents.configuration.observation` 导入；`agent.configuration-intent@1/-observation@1` 贡献声明并入本模块（产品装配数据）。
   - `products/server/src/ordessa_server_product/profile_wire_plugin.py`：ProfileServerPlugin → `ProfileWirePlugin`，id `ordessa.profile` 不变；`ProfileCore` 从 `pacthold.agents.profile_services` 取。
2. **组合装配切换**：composition.py、profile_sessions/profile_configuration/profile_preparation/skills.py、scripts/packaging/controlled_native_fixture.py 全部切核心路径；`NativeProfilePlugin(ProfileWirePlugin)` 子类关系保持。
3. **产品依赖清单**：`products/server/pyproject.toml` 删除 `ordessa-agent==0.1.0`、`ordessa-profile==2.0.0a1`。
4. **打包/验证脚本**：build-deb.mjs PRODUCT_PACKAGES 去除 `plugins/agent/backend`、`plugins/profile`；verify-clean.sh editable 列表去除 `plugins/profile`；closeout-controlled.py 退役 `ordessa-agent`/`ordessa-profile` 发行与 import 名单（`ordessa.profile`/`ordessa.agent` 插件 id 断言保留——绑定 id 不变）。
5. **前端归位**：`plugins/agent/{contracts,sessions,connections}` → `plugins/agent-ui/`；`plugins/profile/{api,frontend,integrations,README}` → `plugins/profile-ui/`。npm 包名、extension id 全部不变；root package.json workspaces、package-lock（重刷）、tooling/vitest-extensions.mjs、apps/desktop 与 chat/model-provider 的 tsconfig/vitest alias、desktop 测试路径同步；node_modules workspace 符号链接经 `npm install` 重建核对。

## 数据影响

- `plugins/agent/config.sqlite`、`plugins/agent/submissions.sqlite`、`plugins/profile/native-configuration.sqlite` 为 data-root 下运行数据路径标识，代码引用（含 `plugins/profile/native-configuration.sqlite` 字符串）原样保留，不做迁移。

## 实测（.venv-cleanup / npm，串行）

| 套件 | 结果 | 对照 |
| --- | --- | --- |
| `pytest products/server/tests -q` | 223 passed, 84 failed | 失败集合与重构前基线逐位一致（全部为 native-assembly 准入拒绝红，plan §5/3 处理对象）；其中 `test_q5_first_stage` 依赖清单断言按退役现实改写：新增"必须不声明 ordessa-agent==/ordessa-profile=="替代断言 |
| `pytest plugins/model-provider -q` | 270 passed, 36 failed | 与基线一致（stash 对比）；失败原因由"import 已删模块"变为预期的准入拒绝 |
| `pytest packages/backend/pacthold/tests/agents -q` | 223+41 全绿（profile 223 + submissions 41 等） | profile 的 6 项 harness_real_service 修复 fixture 深度后全绿 |
| vitest agent-ui sessions/connections | 47/13 passed | |
| vitest profile-ui api/frontend | 10/24 passed | |
| vitest profile-chat / model-provider-chat / model-provider | 94/122/46 passed | |
| vitest chat | 95 passed | |
| workbench layering+token-scan | 86 passed | |
| `node products/desktop/tests/model-selector-assembly.test.mjs` | 通过 | |

## 已知边界

- `test_confirmed_overlay_cleanup…`（subagents T10）基线即红，登记 known-issues 候选。
- products/server 的 84 项 native-assembly 红为基线继承，归 Phase 3（harness 拆分）处置；本轮未新增红。
