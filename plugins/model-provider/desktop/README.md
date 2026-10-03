# desktop — 「模型与服务」设置分区（扩展 `ordessa.model-provider`）

迁移自 `plugins/model-provider/desktop` @ `9305563719d25e04076b9221a7284660bd8f8642`，
逐字保真；仅以下机械适配（见 MIGRATION 注记）：

1. `vitest.config.ts` 别名深度：`../../../packages/...` → `../../../../packages/...`（目录加深一级）。
2. `build.mjs` 同深度修正（`../../../../tooling/build-extension.mjs`）。
3. JSON 文件（package.json/manifest.json）逐字复制、不携带 `//` 注释头（JSON 规范），provenance 记录于本文件。

相对本树的真实改进：注册面经 alias 消费的正是本树当前 Workbench composition 契约
（`packages/desktop-platform/contracts/workbench/src/workbench.ts`，含 `addSettingsSection`），
composition 缺席→类型化拒绝的对照是对着真实契约跑的。

验证：`node_modules/.bin/vitest run --maxWorkers=1`（包目录内）→ 10 passed（G6 渲染零探测、
键盘、窄窗、缺席对照、凭据零泄漏等）。

待接线（不冒充完成）：桌面 PluginContext 的 Server wire 传输口（REQ-Z3-5，OPEN）——
production 组合层绑定 transport；未绑定时本扩展类型化拒绝激活（TRANSPORT_MISSING）。
