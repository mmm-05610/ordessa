# 016 · tasks（夜批六包）

勾选=已完成且证据在 report。不因完不成改判三态；卡点如实写。

## PE1 permissions-authority（plugins/permissions，支 codex/plugin-permissions）

- [ ] PE1-1 authority 记录模型：在 permissions 插件内定义授权事实记录（谁/批准了
      什么工具或操作/作用域 session|user|profile/时效/撤销态），复用其既有
      规则与审批存储，不新建平行存储。
- [ ] PE1-2 查询面：经 plugins/permissions/api 暴露 authority 查询（按操作/
      会话/用户取生效授权），DTO 字段冻结并写进 report（供 core 对齐）。
- [ ] PE1-3 接入贡献：authority 来源经现有插件贡献面注册（server_plugin_api
      Contribution 形态），不要求 core 改动即挂上（core 消费归 INT/AR）。
- [ ] PE1-4 受控测试：授权在场/缺席/过期/被撤销四态 → 查询返回正确 DTO；
      无授权时返回诚实空/None，**不得造默认放行**。
- [ ] PE1-5 边界测试：permissions 不 import server/harness 实现；两会话授权
      互不串扰。
- [ ] PE1-6 report.md + api-requests 回填（core 消费所需 DTO 全字段+失败反例）。

## PE2 harness-native-evidence（plugins/harness，支 codex/plugin-harness）

- [ ] PE2-1 native_evidence 模型：观测事实 = native owner receipt、原生会话身份、
      launch 溯源（access-entry/provenance 既有材料），定义类型并冻结 DTO。
- [ ] PE2-2 三品牌供给：pi/codex/claude 至少三家适配产出 evidence（受控替身
      驱动，零真实模型）；其余品牌登记 unsupported+原因。
- [ ] PE2-3 与 C4 native receipt 协议对齐（51c7905108 口径：operation 绑定
      receipt + 一致 readback），不另造平行协议。
- [ ] PE2-4 受控测试：evidence 在场/缺席/readback 不一致三态；缺席=诚实 None。
- [ ] PE2-5 边界测试：harness 内部改动不越出 plugins/harness；不 import
      permissions/实现。
- [ ] PE2-6 report.md + api-requests 回填（与 PE1-2 同表，core 一次对齐）。

## HK hooks（plugins/assets/hooks，新支 codex/plugin-hooks）

- [ ] HK-1 域骨架：包结构/pyproject/manifest；facet `assets.hooks` 注册进 C2。
- [ ] HK-2 hook 定义模型：事件名/匹配器/命令或 handler/超时/异步；可执行内容
      =强制批准+来源哈希+版本 pin（机制 D 红线）。
- [ ] HK-3 批准与安全：未批准定义=不装载；安全字段（shell 注入面）扫描清单；
      批准状态可诊断、可撤销。
- [ ] HK-4 逐品牌投影表：八家 × hook 支持面三态（有原生 slot=投影；无=unsupported）；
      依据 harnesses.md+harnesses.toml hooks slot，逐格带证据。
- [ ] HK-5 投影执行：经已有 slot/C2 通路投影（通路缺失则 AR 登记报回，不越界
      改 harness）。
- [ ] HK-6 阻断语义如实：观察性 hook 不得承诺强制（Codex MCP hook 失败不阻断
      的反例写进文档与测试断言）。
- [ ] HK-7 report.md：逐格表+批准流程+测试证据。

## LSP（plugins/assets/lsp，新支 codex/plugin-lsp）

- [ ] LSP-1 域骨架 + facet `assets.lsp` 注册进 C2（仿 model-provider adapter
      形制，只仿不 import）。
- [ ] LSP-2 定义模型：LSP server 定义（名称/命令/参数/语言映射）、formatter
      定义、启用与作用域；引用制（可执行文件本体不入仓）。
- [ ] LSP-3 五品牌 adapter：pi/hermes/opencode/qwen/kilo 逐家编译进原生配置面
      （pi LSP/formatter、qwen `.lsp.json`、opencode lsp-stdio 等，语义以官方
      文档为准）；codex/claude/dsh=unsupported+证据。
- [ ] LSP-4 可用性诚实检查：投影前探测可执行文件在场（which/路径解析），
      缺席=该格 unsupported 并带原因，不产假配置。
- [ ] LSP-5 受控测试：golden 转录（字节稳定）+ 两会话隔离 + 缺席可执行反例。
- [ ] LSP-6 report.md：五家逐格表+证据+探测结果。

## SR search（plugins/assets/search，新支 codex/plugin-search）

- [ ] SR-1 域骨架 + facet `assets.search` 注册进 C2。
- [ ] SR-2 原生投影表：八家 × 搜索面三态（claude web search=Desktop 专属
      **不得推定 CLI/ACP**；hermes 搜索后端；其余逐家核实；无=unsupported）。
- [ ] SR-3 投影 adapter：有原生面者编译进原生配置（开关/后端引用/预算参数）。
- [ ] SR-4 可选 SearXNG 绑定（默认关）：置备器骨架（检测 Docker、生成
      data-root 内部署件、探活 JSON API）；AGPL-3.0 进 THIRD-PARTY-NOTICES
      与设置页标注「第三方自托管·进程隔离」；默认不装、不触网。
- [ ] SR-5 受控测试：投影 golden + 缺席反例 + SearXNG 关闭态零副作用；
      **不实测外网搜索**（无授权）。
- [ ] SR-6 report.md：逐格表+SearXNG 选装说明（含 AGPL 边界声明）。

## PX prompts-EXT（plugins/assets/prompts，支 codex/plugin-prompts）

- [ ] PX-0 R0：树内实测四件套计数（pytest/vitest×2/tsc），与账本对齐。
- [ ] PX-1..PX-6：执行 main 上 addendum-eight-brands.md 的 EXT-00..05 逐项
      （八家 instruction 适配收口、harness-adapters 表回填、facet 合并规则
      ——015-B 的 AR-4 等这个结果）。
- [ ] PX-7 R0 补账：36 项未勾账本逐项补勾或注明卡点，报告落
      reports/PX-report.md。
