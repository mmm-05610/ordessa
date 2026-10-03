# 007 T007-10 资源域迁移施工图（repo-scout 交付，主代理存档验收）

来源：只读子代理 2026-10-03，全部带文件:行号与[事实]/[判断]/[UNKNOWN]分级。全文见子代理报告，
本档为执行摘要+主代理裁决。

## 机械风险集中点（全域共享）
1. 根 package.json:19 显式 `plugins/assets/model-provider/desktop`（`plugins/**` 通配其余自动覆盖）；
   package-lock 9 个 `plugins/assets/...` workspace 键需 npm install 重写。
2. packaging/build-deb.mjs:162-176（sandbox×3、model-provider×2、skills）+ ci.yml:36-45/:106-110。
3. `parents[N]` 深度敏感点：lsp points.py:78、memory provisioning.py:226、skills restore.py:118
   + 12 处测试 helper。
4. tsconfig 4 层上跳（5 个前端域）。
5. lsp README 的 PYTHONPATH 是迁移必改项。

## 语义事实（关键）
- compat → assets 域 import：**0 处**。唯一生产性域→compat 依赖：model-provider plugin.py:49
  wire_validators（退役随 wire_validators 拆分）。
- 真实装配只有 model-provider/sandbox/skills(native)；其余六域"包在、装配缺"（known-issues 已登记）。
- 域内品牌适配全部经 `harness.configuration-adapters` 公开点注册（注册机制已中性化）。

## 主代理裁决（007-10 执行口径）
1. **目录顶层化现在做**（保发行/import/extension id/数据 namespace 全不变：mcp 扁平 `backend`
   import 名冻结，M07）。
2. **域内品牌适配物理搬迁本轮不做**：归属语义（品牌应用归 Harness）由公开贡献点承载已满足
   C95 判据；物理归位随逐符号触碰（012 复核时清账）。依据 plugin-architecture §5"共享代码放
   Harness 内部，不强制笛卡尔积"。
3. runtime-preferences 整域归属模糊（纯品牌偏好编译）→ 维持资源域顶层位 + 登记待用户裁决项。
4. memory/posture 双半边陷阱按台账逐符号拆（"资源业务留域，原生路径解释归 Harness"），不整文件搬。

## UNKNOWN 移交（8 项）
command-templates plugin seam 缺失；mcp adapters 生产装配路径；六域动态装配方（catalog/entry-points
待查）；model-provider/adapters 空目录；subagents 前端扩展 id 启用方式；sandbox frontend 默认态；
docs 旧路径全集（012 清扫）；build/lib+egg-info 残留副本清理。
