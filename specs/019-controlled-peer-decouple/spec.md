# 019 · 受控对端"路径=安全边界"解耦 实施规格

状态：设计稿（2026-09-29，源自 core 的根治建议 A+B）。目标：生产代码不再以
tests/ 物理路径作安全判定——**锁内容不锁位置**，此后测试目录怎么搬零影响。

## 现状耦合（三重）

1. `plugins/harness/runtime/access-entry.mjs:269-271` 白名单 = `path.resolve(...)`
   写死 `tests/access/controlled_harness.mjs` 与
   `tests/integration/acp_orchestration/fixtures/bidirectional_acp_peer.mjs`；
2. 物理深度写死（`parents[4]`/".."×N 同族问题在 server-compat composition——那件
   随 017 死亡，不归本包）；
3. 依赖方向反了（生产码认 tests/）。connectors/acp 的 src 仅注释提及，无代码耦合
   （注释已随 `5abd6e684d` 更新）。

## 方案（core 建议 A+B 组合，本包采纳）

- **A 内容摘要锁定**：白名单条目从「路径」改为「sha256(文件内容)」；受控对端
  文件无论搬到哪，内容一变即拒（比路径更强）。
- **B 装配注入端口**：harness 开放「允许的受控对端」声明面（端口/配置项），
  名单由装配侧（products/server，core）注入；生产代码不再内置任何 tests/ 路径
  常量。本包先落 A + 端口面；core 侧装配注入为 AR（对齐后启用）。

## 红线

仅写 `plugins/harness/**`；A/B 并存期行为不弱于现状（路径缺席+摘要不符=拒）；
改造不引入任意命令执行面（名单条目仍是"受控对端文件"，不是命令）。
