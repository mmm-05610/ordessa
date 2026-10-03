# T012-03 构建/typecheck/聚合验证（2026-01-04 夜班实测）

| 检查 | 结果 |
| --- | --- |
| `npm run typecheck` | ✅ **绿**（全 workspace 无 error；夜班 T010/T011 改动引入的 4 处类型缺口已修：FieldState 单一定义、invoke 窄化、glue binding 前置 const 窄化、registeredPending 值收窄——全部为类型面修复，行为零改动，93+120+27 复跑绿） |
| `npm run build` | ✅ **绿**：Built 18 enabled extensions into products/desktop/dist；product: Ordessa Desktop 0.1.0 (0.1.0-local) |
| Python 各包 | ✅ 绿：agent 域 15F；pacthold+environment-api+server-plugin-api 386F；E 系+权威守卫 177F；apps/server 1215P（66F+2E 登记红集恒定） |
| npm aggregate / Electron controlled / typecheck 全链 | ⚠️ **部分**：聚合/无头 smoke 未跑（时间预算）；Electron controlled 腿沿用007 期本地 staging 结果（4/6 腿，2 腿登记成因）。**逐 ID 与基线比对无新增未处置红**（apps/server stash 对照）。 |
| 不删 assert / 不 skip 假绿 | ✅ 全程零删断言、零 skip；红集稳定 66F+2E |

待续（登记）：`npm run --workspace apps/desktop test`（36F）、`tests/integration/acp-connector`（79F）
与 `npm run test:agent-shell && npm run test:electron` 无头 smoke——命令已修复可达（baseline.md），
下会话可直接执行补账。
