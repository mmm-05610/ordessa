# 016 · tasks（夜批十一包；SR 裁撤、MPX/EXT 补入、CMP 存量甄别补完）

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
- [ ] PE2-8 qwen 摘除：harnesses.toml qwen 段、品牌家族表/测试中的 qwen 断言
      同步摘除；report 注明"用户裁定除名，数据兼容无存量用户则零迁移"——若有
      qwen 运行数据目录兼容疑点，登记 known-issues 不擅自删数据。

## EXT extensions（plugins/assets/extensions，新支 codex/plugin-extensions；原 HK 扩容为可执行扩展全域）

- [ ] EXT-1 域骨架：包结构/pyproject/manifest；facet `assets.hooks` 注册进 C2。
- [ ] EXT-2 hook 定义模型：事件名/匹配器/命令或 handler/超时/异步；可执行内容
      =强制批准+来源哈希+版本 pin（机制 D 红线）。
- [ ] EXT-3 批准与安全：未批准定义=不装载；安全字段（shell 注入面）扫描清单；
      批准状态可诊断、可撤销。
- [ ] EXT-4 逐品牌投影表：八家 × hook 支持面三态（有原生 slot=投影；无=unsupported）；
      依据 harnesses.md+harnesses.toml hooks slot，逐格带证据。
- [ ] EXT-5 投影执行：经已有 slot/C2 通路投影（通路缺失则 AR 登记报回，不越界
      改 harness）。
- [ ] EXT-6 阻断语义如实：观察性 hook 不得承诺强制（Codex MCP hook 失败不阻断
      的反例写进文档与测试断言）。
- [ ] EXT-7 report.md：逐格表+批准流程+测试证据。

## LSP（plugins/assets/lsp，新支 codex/plugin-lsp）

- [ ] LSP-1 域骨架 + facet `assets.lsp` 注册进 C2（仿 model-provider adapter
      形制，只仿不 import）。
- [ ] LSP-2 定义模型：LSP server 定义（名称/命令/参数/语言映射）、formatter
      定义、启用与作用域；引用制（可执行文件本体不入仓）。
- [ ] LSP-3 品牌收窄（按品牌优先级裁定）：**只实施 pi**（LSP/formatter 原生面）；
      hermes/opencode/kilo 转阶段二设计；**qwen 除名**（`.lsp.json` 行跳过并登记）；
      codex/claude/dsh=unsupported+证据。
- [ ] LSP-4 可用性诚实检查：投影前探测可执行文件在场（which/路径解析），
      缺席=该格 unsupported 并带原因，不产假配置。
- [ ] LSP-5 受控测试：golden 转录（字节稳定）+ 两会话隔离 + 缺席可执行反例。
- [ ] LSP-6 report.md：五家逐格表+证据+探测结果。


## PX prompts-EXT（plugins/assets/prompts，支 codex/plugin-prompts）

- [ ] PX-0 R0：树内实测四件套计数（pytest/vitest×2/tsc），与账本对齐。
- [ ] PX-1..PX-6：执行 addendum EXT-00..05，**品牌面只做 pi/codex/claude**；
      hermes/opencode/dsh/kilo 行转阶段二设计；**qwen 行全部跳过**（含
      QWEN.md/context.fileName 等，report 逐行登记除名）。
- [ ] PX-7 R0 补账：36 项未勾账本逐项补勾或注明卡点，报告落
      reports/PX-report.md。
（PX-8 已撤：skills/subagents 覆盖盘点升级为 CMP-skills/CMP-subagents 全量甄别包。）

## CMP 存量甄别补完（五包，模式统一）

每包首步 = R0 甄别表：账本逐项三档（已实现已验[附证据指针]/已实现未验/未做），
再对第二档受控补验、第三档今晚补做或注明卡点（E3、core 依赖、被 012-016 架构
取代）。甄别表先落 report，再动代码；被取代项勾选时必须写"取代于何处"。

- [ ] CMP-SK-0..n（skills）：q1 23 项甄别补完；八家覆盖缺口在甄别表内列出，
      实施仅限 E2 可控范围；写入面仅 plugins/assets/skills。
- [ ] CMP-SA-0..n（subagents）：q3 21 项同模式；写入面仅 plugins/assets/subagents。
- [ ] CMP-MC-0..n（mcp）：q4 5 项甄别补完；写入面仅 plugins/assets/mcp。
- [ ] CMP-PF-0..n（profile）：z1 17 项；014-A r2/PA-7 已验项直接归档；写入面仅
      plugins/profile。
- [ ] CMP-CH-0..n（chat）：z2 26 项 + workbench-sidebar 设计账 10 项；写入面仅
      plugins/chat/** 与 plugins/agent/**（不含 conversation 摘除——那归 consolidation）。

## 并入现有包的甄别任务

- [ ] MPX-5：z3 model-provider 账本 5 项甄别补完（与 MPX 同支同树）。
- [ ] PE1-7：q5 safety 账本 5 项甄别（permissions 侧补做；sandbox 侧若需改
      plugins/assets/sandbox 登记报回，不越目录写）。
- [ ] PE2-7：c0 foundation 账本 24 项甄别（harness 侧补做；core 归属项注明转 core）。
