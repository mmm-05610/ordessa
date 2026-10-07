# Harness 拆分：根超级包退役 — 验证证据（Phase 3a/3b）

日期：2026-10-07。对应 plan.md §3、retirement-map 的 Harness API/Go 桥节、migration-map §3。

## 已完成

1. **Harness API 整包并入核心**（3a，提交 1773423c）：`ordessa-harness-api` → `pacthold.harness_contracts`（10 模块 + py.typed，与 READY checkpoint 字节一致，由 C3 守卫逐文件证明）；184 处消费者切换；各插件边界守卫改为“点级许可”（裸根仍禁、契约边可入，反例保留）。
2. **根 `ordessa_harness` 超级包退役**（3b）：
   - **通用机制 → `pacthold/harness_kit/`**：resources、importers、materialization、configuration 的 profile 侧模块、verifier_deployment（+ `_deployment/native-artifact-policy.mjs` 进 pacthold 包数据，源回退指向 `plugins/harness/runtime/`）、harnesses.toml/launch-descriptors.json（声明数据）。
   - **品牌/宿主持有面 → `products/server/src/ordessa_server_product/harness_adapters/`**（仅产品绑定归产品）：contributions、entrypoints、plugin、_compat、adapters/、application/、generic/、registry/、configuration/model/、native_materialization.py。registry 的资源定位改为 `pacthold.harness_kit` 包内声明数据。
   - **ACP 通道 → `products/server/src/ordessa_server_product/acp_channel/`**（宿主持有面；中立 codec/transport 抽到 harness-transport 仍为后续项）。
   - **品牌知识 → 独立品牌包**：`plugins/harness/{codex,pi,claude-code}` 合并根目录内容（pi 的 legacy provider 与 claude 重复 native_channel 删除，落实“一套 provider”）；`hermes/opencode/qwen/kilo/dsh/kimi/copilot/goose/gemini_cli/vibe/qoder` 各自新建最小包（pyproject + src/ordessa_harness_<brand>，无自动注册 entry point；品牌知识原样搬迁）。品牌包 `__init__` 不 re-export 会拉入 pacthold_runtime_compat 的 legacy provider（其模块仍可按名导入）。
   - **根壳删除**：`plugins/harness/{pyproject.toml,setup.py,MANIFEST.in,src/}`；`api/` 目录；旧 entry points（harness-profile-store/opencode/hermes）随之退役。产品清单改为显式品牌依赖。
   - **测试随职责迁移**：根 harness 测试（1207 项）→ `packages/backend/pacthold/tests/harness_kit/`，路径/根常量按新布局重写；`test_core_identity` 重写为“kit 为唯一源码、retired 树必须缺席、registry 单对象跨导入序”；`test_core_boundaries` 重写为“根超级包退役、品牌各自独立发行、无自动注册”；packaging/acp/边界守卫按新根改写。

## 实测（.venv-cleanup，串行；/tmp tmpfs 满时先清理 pytest 临时目录）

| 套件 | 结果 | 对照 |
| --- | --- | --- |
| `pytest packages/backend/pacthold/tests/harness_kit -q` | 1191 passed, 6 failed, 27 errors | 基线 1186 passed/10 failed/27 errors；现存 6 项失败与 27 errors 全部 ⊆ 基线集合（byte-ceiling、acp schema drift×2、adapters_conformance bridge purity、brand_org×2；pi_live_runtime 27 errors） |
| `plugins/harness/codex|pi|claude-code/tests` | 278 / 318 / 255 passed | 全绿（含各自 wheel 闭包，`ordessa_harness` 缺席断言替代旧 `pacthold.harness_kit` 缺席断言） |
| `plugins/harness/records` | 1 passed（闭包补内核链） | |
| `plugins/sandbox` | 299 passed | |
| `plugins/mcp` / `plugins/runtime-preferences` | 526 / 151 passed | |
| `plugins/model-provider` | 270 passed, 36 failed | 与基线一致 |
| `plugins/skills/tests` | 437 passed, 1 failed | 基线红（overlay cleanup） |
| `plugins/subagents/tests` | 889 passed, 1 failed | 基线红 |
| `products/server/tests` | 223 passed, 84 failed | 与基线逐位一致（native-assembly 准入红） |
| `packages/backend/pacthold/tests/agents|decision` | 264 / 363 passed | 全绿 |
| `packages/backend/harness-transport/tests` | 103 passed | |
| `apps/server/tests` | 1307 collected，1202 passed / 98 failed / 2 errors | 3a 基线为 13 个收集错误（不可运行）；3b 后大幅改善，余红为沙箱 provider/sidecar 环境类与继承红 |
| `tests/boundaries` | 9 passed | |

## 明确剩余（如实登记，不得当作完成）

- **Go ACP 桥拆分（3c）未开始**：`plugins/harness/adapters/acp-adapter` 仍为单模块 `--adapter codex|pi`；acp-common/codex/pi 三拆与品牌构建清单未做。
- **server_acp 的中立通道抽取**：现落在产品 `acp_channel/`（宿主绑定），retirement-map 要求的 `packages/backend/harness-transport/adapters/acp-common` 中性抽取未做。
- **deploy/、harnesses/、packaging/、runtime/、third_party/、tools/** 仍在 `plugins/harness/` 组级目录，未逐品牌拆入品牌包；`harnesses/index.mjs` 的 descriptor 引用已指向内核数据。
- **legacy 品牌运行时代码**（codex/app_server、remote、credentials、managed_account；pi/native、native_channel；claude 遗留）随包保留但无产品消费者（AU003 准入拒绝）；按 plan「没有消费者的旧模型删除」的逐项删除与替代测试说明待做。
- **根 harness 的历史过程文档**（CONSOLIDATION/REFACTOR-PLAN/T01/T02 等 MD）保留在组目录，未清理。
- 基线红：byte-ceiling、acp schema drift ×2、brand_org ×2、adapters_conformance bridge purity、model-provider 36、products/server 84、apps/server 98、skills/subagents 各 1。

## 数据影响

无：harnesses.toml 声明数据、deploy 模板、runtime 资产字节未变；未触碰任何运行数据。
