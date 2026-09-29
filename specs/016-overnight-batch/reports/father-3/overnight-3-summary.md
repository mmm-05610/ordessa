# overnight-3 总汇报（father 会话）

日期：2026-09-29。执行体：father 会话（zcode 代打）。任务：father.md 四子包
串行完成 + 阶段二（四家设计 + zcode TUI 侦察 + 审阅）。纪律：封装调用、
失败代打留痕、子分支提交不并回、审阅非验收、无真实模型调用、本会话并行
智能体 ≤2（全程串行，无并行子代理）。

## 一、四包结果总表

| 包 | 分支 | 终提交 | 结果 | 测试 | 审阅 |
| --- | --- | --- | --- | --- | --- |
| son-lsp（新建 LSP 域包） | codex/plugin-lsp | 32be93d8a1 | LSP-1..5 落地（域骨架/facet `assets.lsp`/定义模型/探测/投影决策；pi/codex/claude-code 三格诚实 unsupported） | **42 passed**＋golden 字节钉 b8926851 | 5 轮，终轮**有保留如实登记**（C-LSP3 晨裁待裁、entries 占位注册定性接受） |
| son-cmp-mcp（甄别+补验） | codex/plugin-mcp | f4fab0488f | q4 全项 A/A'；前端 dto 重写为实测 shape；wire 契约调和＋C4 native-receipt 链修复 | 接手 4F+2E → **526 passed / 0 failed** | 3 轮后备，终轮**通过**（闭环） |
| son-cmp-profile（甄别） | codex/plugin-profile | c00b48a0f0 | 17 项全 A/A'；树内 venv 复验 | **152 passed**＋vitest 28＋反例 12/12；4/5 门（tsc ×3 未复现=根锁脱同步，z1 遗留归 C0，如实登记） | 2 轮后备，确认轮唯一保留已补账本条目（**闭环**） |
| son-cmp-chat（甄别） | codex/plugin-chat | fae10a8adc | z2 26 项：A×17／A'×6／未测×2（V09/I07）／归属×1（V08）；WS01-10 为他支线（codex/workbench-sidebar 未并）项，注记"线报告自验口径、本包未独立复验" | chat-api **23**＋frontend **50** vitest 全绿，tsc ×2 干净 | 1 轮后备有保留→两点落实（统计重计；他支认定降格）（**闭环**） |

四包详细证据格、逐项对照、遗留义务去向均在各自
`specs/016-overnight-batch/reports/{LSP,CMP-mcp,CMP-profile,CMP-chat}-report.md`
（已随各分支提交）。

## 二、qoder 调用记录（四包一致）

- 逐包经 `bin/run-qoder.sh` 调用，**全部失败**：`-p`＋`--permission-mode
  default` 权限墙确定性拒绝一切写盘/执行（非间歇性；三父会话同报，日志在
  `specs/016-overnight-batch/reports/logs/`）。按 spec.md 红线 5 无人值守附加
  条款改**父会话代打**，四包提交信息与报告均标注「qoder 失败、zcode 代打」。
- 审阅侧：`run-review.sh` 对 mcp 全分支 diff 触发 `timeout` 参数列表过长
  （exit 126）→ 按 father.md 后备口径以 `pi -p --no-session --no-tools
  --model mimo-v2.6-pro` 直喂批提交 diff（45KB）完成；其余包用封装或同型
  后备，轮次与结论见各报告。

## 三、复用 vs 自建

- **son-lsp 自建**：definitions/transcription（api）、evidence/points/probe/
  project/registry（adapters）与 42 测；**复用形制**（只仿不 import，依赖方向
  测试钉死）：sandbox/model-provider 的 adapter 注册形制、probe 注入式 PATH、
  canonical_json_bytes 字节稳定转录、golden 比较门。
- **son-cmp-mcp 补做**：wire 契约调和（SOURCE 解析账本＋账本/报告同动＋反义
  孪生防空洞）沿用 contract-guard 既有方法学；C4 receipt 绑定从声称变验证
  （新增异 receipt 回读反例，单变量隔离）；不重造 probe/权限双门/受管 client。
- **son-cmp-profile**：零生产代码改动（甄别包）；环境自建=树内 venv 有序
  editable 安装链（pacthold→…→products/server；packages/workspace 非 Python
  项目不装）。
- **son-cmp-chat**：零生产代码改动（甄别包）；复用主仓 node_modules 工具链经
  目录 walk-up 跑树内源。

## 四、卡点（非本线可解，均如实登记不私改）

1. **qoder 权限墙**（系统性）：封装可运行但被权限模式废功——封装脚本本身
   无损，未触发裸调降级条款；修复需 qoder 侧权限面裁决（晨裁输入）。
2. **C-mcp-fe**（son-cmp-mcp）：前端三项语义裁决（canonical 文档缺席于新
   mcp.get wire 面、状态三档证据源、entry 身份绑定）待裁；tsc 75 行存量
   清单在报告内。
3. **根锁脱同步**（z1 遗留，归 C0）：profile 三包 tsc 门不可复现、npm ci
   失败（package.json/lock 不同步）——只登记未私改主锁。
4. **C-LSP3 晨裁**（son-lsp）：任务前提与 L2 证据相悖（pi 无 LSP 面/dsh 有
   lsp-stdio），按"F6 修正入档、不改任务文本"处理，待晨裁。
5. **装配 owner 待裁**：lsp 域登记产品装配归 INT/AR、chat 域归 C0——两域
   登记不一致，阶段二设计已加显式注记（派单前不得互推）。

## 五、阶段二产物（./reports/，只文档）

| 文件 | 内容 |
| --- | --- |
| phase2-design-lsp.md | hermes 待核/opencode+dsh+kilo 实施形态（待授权派单）网格、adapter 形制、5 项测试门 |
| phase2-design-mcp.md | 四家 MCP 配置面证据格（hermes mcp_servers/opencode local+remote+OAuth/dsh Cordis 包级 patch/kilo schema 钉版）、复用 011-q4 件、测试门 |
| phase2-design-profile.md | facet 提供者+字段账（hermes SOUL 分层/opencode layered-merge/dsh generation 写入语义（applyMode 待核）/kilo restart） |
| phase2-design-chat.md | 每家会话接入 capability 声明面；opencode/kilo 未证前只读降级、dsh sessionRef 待实测 |
| recon-zcode-tui.md | ZCode TUI/CLI 配置面侦察：L1 本机钉定（安装树、CLI 0.16.9 help 原文、随装 zcode-guide@0.3.0 官方文档）+L2 官方仓库（zai-org/ZCode @release aeaed5dd，v3.14.3）；app-server "ZCode Protocol" stdio 通道待核；7 项缺口清单；安全面（MCP 全作用域自动连接、headless 默认 yolo） |
| phase2-review-record.md | 阶段二 pi 审阅轮记录：总评有保留，8 条问题 8/8 修订入档 |

**落盘纪律说明**：overnight-3 工作树检出于 `main` 分支，按"不在 main 提交"
纪律，阶段二产物**只写盘未提交**；如需入库由用户指定分支后转移。

## 六、偏差与诚实边界

- 无未授权真实模型调用；全部验证走受控 fixture/假端点/隔离 HOME 口径。
- lsp 审阅终轮"有保留"不再循环（两点diff 终局分歧如实记录在报告）——按
  "审阅非验收"口径留给晨裁，非默认通过。
- chat WS01-10 未独立复验（工作在他支线未并），报告中只声明"线报告自验
  口径"，不冒充本包复验。
- 版本映射（本机 CLI 0.16.9 ↔ 仓库 v3.14.x）与 ZCode license 原文为侦察
  文档内登记的待核项，未凑数。
