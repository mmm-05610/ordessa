# ledger.md — blocker/backlog 动态真相源

Lead 维护。每发现一个问题先入表再处置；"发现 blocker"不是完成。

优先级：**P0** deb/install/launch/core runtime 完全阻塞 · **P1** 普通 Harness
Desktop 主路径 broken · **P2** 重要已有产品能力 broken · **P3** UX/hardening/
secondary feature · **P4** architecture/cleanup/test quality。

状态：NEW → INVESTIGATING → ASSIGNED → FIXING → REVIEW → VERIFY →
DONE；特殊：BLOCKED_EXTERNAL / DEFERRED。

Lead 工作队列：NOW / NEXT / REVIEW / VERIFY / BACKLOG（NOW 快空时提前从 NEXT 拉）。

## Blocker / Issue 表

| ID | Priority | Area | Symptom | Reproduction | Root Cause | Owner | Branch | Status | Verification | Disposition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| W-001 | P1 | product-assembly | 默认桌面装配 `products/desktop/extensions.json` 仅 14 项，不含 skills/mcp/prompts/permissions/model-provider/memory/lsp/subagents/runtime-preferences 域 | Phase 1 盘点 assembly vs `plugins/`、`packages/desktop-platform` 能力域 | 未查（假说：桌面扩展缺装配 或 属 server 侧插件域） | Lead→Phase 1 核实 | — | NEW | — | 今晚 P1 接通候选；先核实性质再派 Integrator |
| W-002 | P4 | backend | harness 套件 2 inherited failures（npm closure：`@agentclientprotocol/sdk` override vs `@automatalabs/pi-acp` 声明） | `python -m pytest plugins/harness` | 依赖漂移（上游树继承） | — | — | DEFERRED | inherited（known-issues 登记） | 与 baseline 对比；非今晚新增不 block |
| W-003 | P4 | backend | server 套件 inherited-red 台账（783P/43F/10S/25E；59 同 ID inherited + 6 scope-reds） | `python -m pytest apps/server` | 见 `docs/migration/backend-build-test.md` 逐项裁定 | — | — | DEFERRED | inherited | 只对新增 regression 追 disposition |
| W-004 | P4 | backend | `tests/acp_orchestration` reds（worker-entry retirement 裁定） | 运行该套件 | hd004 裁定：不复活 compat chain | — | — | DEFERRED | inherited | 保持 visible；禁止 green-by-revival |
| W-005 | P3 | CI | `test_external_adapter_product.py` 干净 CI runner 上 error（pip 子进程构建 fixture 分布解析不同；本地 3/3 过） | CI ledger step | fixture 构建输入未钉死 | — | — | DEFERRED | CI-env（2026-09-29 登记） | follow-up：pin fixture 输入/offline wheelhouse |
| W-006 | P3 | desktop-UI | approval card 无 timeout 显示 | Round H 登记 | UI debt | — | — | DEFERRED | inherited | 今晚 UX 波次候选 |
| W-007 | P3 | desktop-UI | 输入框滚出视野（待确认） | Round H 登记 | UI debt | — | — | DEFERRED | inherited | 今晚 UX 波次候选 |
| W-008 | P4 | bridge | `TestE2EACPPlanUpdateMappedFromTurnPlanUpdated` flaky（2/3 失败曾观测） | Go 侧 e2e | Go-side flaky | — | — | DEFERRED | inherited flaky | 观测；不计 regression |
| W-009 | P4 | server-arch | `bootstrap/runtime.py` start/stop 仍达 Core 内部（configure_database/get_conn）而非实例级 Store；S1c 组合裁定未落 | specs/010 B lane T014-S1c | 架构搬家未完 | — | — | DEFERRED | registered | 仅当阻塞 P0/P1 才动；否则不碰 |

## Backlog（主动发现池，动态）

| 候选 | 来源 | 备注 |
| --- | --- | --- |
| installed-product smoke 脚本化（install→launch→project→session 链） | acceptance P0 | 服务于 C2 与最终 closeout |
| deb 资源完整性检查（icons/desktop entry/服务端 runtime） | acceptance Product Assembly | `scripts/packaging/clean-machine-accept.sh` 已有基础 |
| Profile facet 盘点（ owning plugin facet 列表 × Harness 支持矩阵） | acceptance Profile | Phase 4 输入 |

## 环境

- Live services 注册表：`docs/known-issues.md` §services —— **不 kill/restart**。
- 真实测试：隔离 data-root + 临时项目；用户登录态只读。
