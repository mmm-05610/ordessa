# 待决决策 — T008-04 HarnessAvailability 域载体身份（2026-10-04，硬性决策记录）

## 问题
migration-map 要求 foundation 内 HarnessAvailability 类型迁 `plugins/harness/contracts`
公开域载体，且"平台不反向 export 业务"。但实施撞身份死结：platform 纯度守卫（contract-ownership
test2）禁止平台源引用 `plugins/**` 相对路径；而 plugins/harness 非 npm workspace
（根 workspaces 显式排除），也没有 TS 共享载体（`@extensions/...` 形式需扩展身份）。
直接相对 shim 即刻红 23 处 typecheck + 守卫违规。

## 选项
A. 新建 `@extensions/ordessa.harness-contracts/contract.js` 载体（类比 agent-contracts）：
   需新增扩展身份/manifest/lock（新 ID 允许新增，但属发行面变化）。
B. plugins/harness 增加 npm 公开包（如 `@ordessa/harness-contracts`，contracts/typescript
   面）：守卫的 bare-specifier 白名单可加；属包面新增。
C. 类型留在 foundation 但标注所有权归 Harness 域（物理不动、语义标注）：最小改动，
   不满足 migration-map 的物理归属字面。

## 建议
选 A（与 agent-contracts 同构、守卫模式现成、身份显式）；实现成本约一个切片（载体包+
manifest+lock+guard 白名单+消费者 specifier 迁移）。026 已冻结的 Token（HarnessAvailabilityToken）
构造点不动。

## 现状处置
本切片回滚至绿态（typecheck 0 错）；T008-04 的另一半（foundation 与 Agent 域载体分离、
共享 Token 运行身份测试）已由既有 contract-ownership/layering/token-identity 门覆盖。
待用户批复选项后补完物理拆分。
