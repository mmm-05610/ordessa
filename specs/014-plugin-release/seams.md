# 接缝请求单（014 ⇄ core/013 线）

> 用法：plugin 线对 core 线的全部跨线请求与答复账。plugin 侧在接缝落地前以受控 fixture / 诚实缺席推进，不越界代写。状态：`open` / `relayed`（已转 core）/ `agreed`（归属/做法已定）/ `landed`（已落地，回填 SHA）。**本文件已提交进 main，core 线可直接在此表下方回填。**

## 2026-09-28 core 线答复摘要（013 现状：三包完工未提交，基底 7adf5aeaca，plugins/** 零改动；三条折扣：红账本复验不完整 / P-C 接占位桩 / wire 生产接线仍 fixture）

| id | 请求 | 归属与状态 | 说明 |
| --- | --- | --- | --- |
| S-00 | 发行门依据入库（`docs/release/` + `specs/013-desktop-product/`） | core **INT-05 入库** | specs/013 已在 `codex/013-desktop-product-plan @ 7adf5aeaca`，未进 main；docs/release 仍未跟踪 |
| S-01 | `products/desktop/extensions.json` 启停 | **装配动作归 core；启用清单归 plugin 线（已给，见下）** | 启用：`ordessa.chat-api`、`ordessa.chat`、`ordessa.profile-api`、`ordessa.profile-frontend`、`ordessa.profile-chat`；退役：`ordessa.agent-conversation`（**条件**：P-C 完成等价覆盖核对后确认，见 PC-6）。core 提醒：`default_plugins()` import 的 `ordessa_permissions_adapters`/`ordessa_sandbox_adapters`/`ordessa_sandbox_backend` 三个发行版装配前必须装齐。**P-A 增补（2026-09-28，PA-4 完成后）**：三包缺件已补齐（manifest+build.mjs+诚实 entry，构建演练三包均出 entry 产物，演练产物落临时目录未触 products/）；依赖闭包：`ordessa.profile-chat`→`ordessa.chat-api`（glue 消费 ChatContributionsToken）、`ordessa.profile-frontend`/`ordessa.profile-chat`→`ordessa.profile-api`（ProfileServiceToken/类型）；`ordessa.profile-api` 另出 `contract.js` 第二 entry（对接 S-04 CONTRACT_SOURCES）；启用后即可过 extensions 通道，真实视图接线（workbench 注册/Token 供给）随装配落，前端 entry 现为诚实无副作用桩。**P-C 回执（2026-09-28）**：条件已满足——等价覆盖逐条核对完成（P-C report §PC-6 表），`plugins/agent/conversation` 九文件已在 P-C 分支删净（旧 view id 引用同步清除）；摘除该 id 后 11 扩展变体构建通过（含 chat-api+chat，证据 P-C report）；真实产品构建在 id 摘除前会红（`build-all` 拒绝无包 id），属预期，随本条装配翻转消除。`apps/desktop/renderer/agent-conversation.test.tsx` 在 main 已不存在（T019 移包），core 侧无删除动作 |
| S-02 | `extensions.lock.json` 与根 lock | core **INT-02 定稿** | extensions.lock 是 `tooling/build-all.mjs` 的**产物**（每次构建重写），非源文件；`@assistant-ui/react` 摘除与 P-B 新增 `server-bridge` workspace 一并在 INT-02 干净构建重算。**P-A 增补（2026-09-28）**：根 lock 还缺 `@ordessa/plugin-profile-api/-frontend/-chat` 三个 workspace 条目（main 的 lock 同样缺），P-A 本地 `npm install` 重算保持未提交（011-z1 先例），INT-02 重算时须一并纳入。**P-B 增补（2026-09-28，R0 第一手实证）**：根 lock 还缺 `@ordessa/plugin-model-provider`（plugins/assets/model-provider/desktop）与 `@ordessa/plugin-model-provider-chat`（chat-contribution）两个 workspace 条目——`npm ci` 实测红（Missing: … from lock file），按同先例本地 `npm install --no-save` 安装（根 lock 零改动，git status 干净），desktop vitest 10 / chat vitest 21 全绿；INT-02 重算时与 profile 三条一并纳入 |
| S-03 | Server 默认插件集增 profile 入口 | **装配动作归 core**；model-provider 装配须在 S-08① 退役之后 | 同 S-01 清单；顺序约束已双方确认 |
| S-04 | `tooling/vitest-extensions.mjs` CONTRACT_SOURCES +2 行 | core 补；**路径已给** | `plugins/chat/api/src/contract.ts`、`plugins/profile/api/src/contract.ts`（均实测存在） |
| S-05 | 附件 prepare 生产 owner + `BackendAdmissionState` 供给 | **拆分裁定**：prepare/verify/release 语义、过期、跨连接规则=**插件业务**（plugin-layout §3）；core 只出「受信字节通道 + 摘要完整性校验」机制；Go 桥收非图片 resource link 归 harness 线。**DTO 已冻结（2026-09-28 核实修正）**：connectors 侧 `AcpPreparedAttachment` 本就含 `preparedId`（`plugins/connectors/acp/src/attachments.ts:10-12`，注释明言 Server ACP DTO 未携带）——对接基准即此形状；**缺的字段在 Server ACP DTO，归 core 补齐对齐**；`BackendAdmissionState` 生产供给归 plugin 线 harness 部分（P-E，第二批：Q5 authority + harness native_evidence）。**PC-9 核实回执（2026-09-28，P-C 分支）**：`attachments.ts:10-18` 复核无误——`preparedId` 在基准形状内（另有 `name/uri/mimeType/sha256/byteLength`，`validPreparedReference` 逐字段校验，`samePreparedReference` 全等比较），缺的字段确在 Server ACP DTO；**P-C 对 connectors 零改动**（git 可核），agent-contracts 0.2.0 已把该形状镜像为 `AgentPreparedAttachment`/`AgentAdmissionEvidence` 消费面；core 按 `attachments.ts:10-18` 对齐 Server DTO 即可 | 互等解除：形状基准已给（attachments.ts:10-18），core 按 Server DTO 对齐 |
| S-06 | admission `ready=False` 翻转链 | **机制归 core（在做）**：fail-closed 门 + 从产品组合取 authority + 注入观测事实；**不编码"什么算被许可"**（业务归 Q5）。依赖 plugin 侧两件：Q5 authority、harness `native_evidence` —— **均归 plugin 线，已排 P-D（014 第二批，A/B/C 收口后）**；core 机制侧可先行，互不阻塞 | 顺序答复已给 |
| S-07 | Claude Code 命令目录/附件承载 | **三次修正（2026-09-28，源码实证）**：Claude 有 ACP 桥——钉版官方 `@agentclientprotocol/claude-agent-acp@0.81.2`（`plugins/harness/packaging/claude/`），不走 Go 桥。**附件＝旧负证据已推翻，修复立项（用户裁定：必须解决）**：0.81.2 源码 initialize 明确声明 `promptCapabilities:{image:true, embeddedContext:true}`（`acp-agent.js:1108`），双向图片转换在案（:7364 用户图片→Claude base64；:7682 输出图片→ACP chunk），`resource_link` 转 URI 链接文本下发（:7341，非丢弃）；旧记录"真实握手 promptCapabilities 为空"系 0.77 时代遗留（随 974e643a10 拆库带入，升 0.81.2 后未重探），FAMILY_MATRIX 只对 toml 不对 adapter 故未抓到 → **立 P-D 包**：重探针→翻绿 attach→接通 claude 通路（语义如实：图片=真实附件块，非图片文件=URI 链接，audio 未声明）。**命令目录＝已探针（2026-09-28，PC-10 第一手负证据）**：P-C 在受控环境（loopback fake Anthropic API + 一次性 CLAUDE_CONFIG_DIR + fake token，零真实模型/凭据；架式沿用本目录 provider-routing-smoke.mjs）拉起钉版 0.81.2 adapter 完整会话（initialize → session/new → prompt end_turn → 3 秒观察窗），**全通道零 `available_commands_update` 帧** → claude 行命令目录=**诚实 absent（该品牌未播发）**，chat 斜杠面板按此呈现"无命令+原因"；转录存 `specs/014-plugin-release/reports/P-C-pc10-probe-transcript.json`（同轮 initialize 实证 `promptCapabilities:{image:true,embeddedContext:true}`，佐证 S-07 附件修正）。探针代码 `plugins/chat/probes/claude-native-commands.probe.mjs`；plugins/harness 零跟踪文件改动。**P-D 完成（2026-09-28，受控 L2 级）**：第一手探针推翻旧负证据（实测握手播发 `promptCapabilities {image:true, embeddedContext:true}`，image 往返 sha256 一致，resource_link=URI 链接文本，audio 适配器静默丢弃→通路类型化拒绝），`attach` 翻绿已观测，通路接通（`ordessa_harness/claude/attachments.py`）；报告 `reports/P-D-report.md`、转录 `reports/P-D-probe-transcript.json`（sha256 45101ea7…），交付 SHA=分支头。**命令项两证并存待对账**：P-D 同轮顺带观察到 0.81.2 会话内自发播发 `available_commands_update` ×2（只记不接线），与 PC-10 的 3 秒窗零帧负证据条件不同（观察窗/会话形态差异），定夺仍挂 PC-10 口径，对账归后续波次 | 附件=修复完成（P-D 已翻绿接线）；命令=PC-10 判 absent 在案，P-D 顺带正向观察待对账 |
| S-08 | compat/旧 writer 退役三件事 | **归 plugin 线（core 确认不碰插件文件，只配合 products 装配）**，**集成波次串行执行**（不在 A/B/C 并行段做，防 A/B 在 server-compat/core_wire.py 互撞与中途破坏 harness）：① server-compat `model_configs` writer（`core_wire.py:238-276`）退役→再装 model-provider；② harness 品牌渲染（`native_materialization.py:114-145`）退役（B 的 adapters 金样承接）；③ profile 旧 writer（harness `generic/profile_*.py`、`harness-profile-store` entrypoint、`{claude,hermes,opencode}/profile*.py`、server-compat `server_profiles`）退役 + `agent-box.profile@1` **双声明仲裁**。A 出 ③ 的裁定与清单（PA-7）**已交付（2026-09-28）：`specs/011-z1-profile/retirement-request.md`**——裁定 `agent-box.profile@1` 唯一声明者=profile-api（依据含加载顺序"先者赢后者 FAIL"实证），R1-R10 逐文件退役清单+消费者核查+执行顺序；其中 server-compat `server_profiles` writer（R10）退役执行归 B 侧波次；harness 侧 R5 entrypoint 摘除须同波改 `test_core_boundaries.py:15` 断言、R6 摘除须同波改 P-A 矩阵测试 face import（清单内已注记），B 出 ①② 的清单与装配顺序（PB-7）**已交付（2026-09-28）：`specs/011-z3-model-provider/retirement-request.md`**——W1-W15 逐行退役清单（行号以现行树实测，派单旧行号 238-276 已漂移并声明）、消费者核查（products 装配注入/边界测试断言 apps/server test_server_compat_boundary/兼容回归四件/execution 冻结面 W5 跨域引用）、「先退 compat writer（同批含边界断言更新）→再装配 model-provider（S-03）→两步之间不许双写窗口」顺序确认；S-08② 承接方证据=adapters conformance 金样一致性门（codex TOML 逐字节/pi 对象/claude env/DIALECTS≡harness 家族表/描述符 native target≡harness pins，含注册路径）；执行时机=新 owner 就位（已就位：六方法逐字+MP-12+192 测试）+ core 装配排期后 | 已认领（A 侧③与 B 侧①② 清单均已交，执行归集成波次） |
| S-09 | canonical SessionRef 服务端映射 | **core 整条撤回**：会话业务语义归 session 域（`plugins/agent/sessions`），core 只在传输带不透明稳定 id。**plugin 线认领**：排 014 后续波次，产出「方案 + 迁移记录」设计件后**请用户确认**（数据兼容敏感）方可实施。**P-A 状态注记（2026-09-28）**：设计件不在 P-A 包（PA-7 仅覆盖退役清单，不涉 SessionRef）；本包 140 口径中 legacy 映射（realm='local', uid='legacy:<id>'）保持"只保真迁移不冒充跨服务身份"的 v1 口径，后续波次接手 | 已认领（设计先行） |
| S-10 | `docs/baseline.md` 安装清单补录 | core 补；**清单已给** | pip 可编辑包新增：`plugins/profile`（ordessa-profile）、`plugins/assets/model-provider/server`（ordessa-model-provider）、`.../adapters`（ordessa-model-provider-adapters）、`.../profile-contribution`（ordessa-model-provider-profile）。**P-A 增补（2026-09-28，R0 第一手实证）**：安装**顺序**坑——`products/server` 把 `ordessa-sandbox-backend/-adapters/-api`、`ordessa-permissions-api/-backend/-adapters` 声明为依赖，但它们只在本地（`plugins/assets/sandbox/*`、`plugins/permissions/*`），不先 `-e` 装好则 pip 从 PyPI 找 0.1.0 必红（`Could not find a version... ordessa-sandbox-backend==0.1.0`）；baseline 安装命令须把这些包放 `products/server` 之前，`ordessa-server-plugin-api` 亦须先于 sandbox（其依赖）。P-A R0 实际可复制的命令序列见 reports/P-A-report.md §R0 |
| S-11 | desktop PluginContext wire invoke 生产绑定 | **半 landed**：`packages/desktop-platform/server-bridge/src/wire-port.ts`（`HttpWirePort`，含测试）已交付；宿主接线 `apps/desktop/electron/main.ts:109` 仍 `createFixtureWirePort()`，切换点归 core **INT-01**。P-B 升验收口径：「接口与实现已交付、生产绑定在 INT-01」，R0 直接消费 `HttpWirePort` 类型。**P-B R0 核实注记（2026-09-28，第一手）**：`wire-port.ts` 的交付位置是 core 分支 `codex/013-b-server-runtime` @ `742389c2e6`（`git log --all` 定位；源码直读证实三态 `WireResult`/`AbsentWirePort` 语义在案），**不在 main 491aa92392、不在本树**——P-B 树内无可导入/可引用的交付物，R0 仅完成存在性与形状核实，生产绑定仍归 INT-01 | agreed |

## core 侧三条红线（双方遵守，已写进各 dispatch 简报）

1. core 不定义业务语义（S-06 只做"有 authority 就过、没有就拒"）。
2. core 不实现插件 port 的业务部分（S-05 只出字节通道与摘要校验）。
3. core 不动业务标识（S-09 撤回；会话标识变更只能由会话域出方案+迁移记录+用户确认）。

## plugin 侧待办回执（对 core 三问的答复，2026-09-28）

1. **S-06 顺序**：Q5 authority 与 harness `native_evidence` 均在 plugin 线，已排 **P-E（014 第二批，A/B/C/D 收口后开）**，同包并行两件；core 机制侧先行不阻塞。
2. **S-05 DTO（答复修正）**：connectors 侧形状**已就绪**（`AcpPreparedAttachment` 已含 `preparedId`，attachments.ts:10-12），P-C 的 PC-9 改为核实+回写基准；**Server ACP DTO 补字段归 core**，按该基准对齐即可，无需等我们。
3. **S-01 清单**：见上表 S-01 行（`agent-conversation` 退役以 P-C 覆盖核对确认为条件，**P-C 已回执条件满足**）。

## 转交记录

- 2026-09-28：S-00…S-11 首次问询经用户转 core；同日 core 逐条答复（013 现状+归属裁定+三回执问题），本表已按答复回填。core 侧如需继续回填，按 `日期 / 条目 / 结论 / SHA` 追加在下方。
- 2026-09-28：P-C 分支回执——S-01（agent-conversation 退役条件满足，见行内回执）、S-05（PC-9 核实：基准形状在案、connectors 零改动）、S-07（PC-10 探针：不播发，absent+证据）三条已按行内追加回填。
- 2026-09-28：P-D 分支回执——S-07 附件翻绿并通路接线（受控 L2 探针，行内追加）；命令目录 P-D 顺带观察到自发播发 ×2，与 PC-10 负证据**条件不同、两证并存待对账**，行内已注记。
- 2026-09-28：014 收口并入（主会话集成动作）——四包报告/勾选/接缝回填联合入 main；seams.md 为 b∪c∪d 三路联合，S-07 命令项两证并存如实保留。

## plugin 侧对 core 四阻塞项的答复（2026-09-28 收口后）

**① 夹具路径（已修，待 core 合并复跑）**：新热修支
`codex/hotfix-server-compat-fixture-path` @ `0d1d9bd8b8`（基于 `codex/core`
`dbaa0fac4a`），修 server-compat 侧**两处**：`composition.py:452-453`（计算侧，
即 core 指认处）+ `test_controlled_peer_opt_in.py:14`（断言侧，core 未点名的
第二处——只修前者该测试会接着红）。至此 harness 白名单 / server-compat 计算 /
server-compat 断言三方同指 `tests/integration/acp_orchestration/…`；全仓代码
旧引用清零，py_compile 与夹具解析存在性已验，套件复跑归 core（预期回到
harness 2 红 / 编排 18 红继承态）。

**② 附件 DTO「编号」字段（冻结版已就绪）**：冻结形状 =
`plugins/connectors/acp/src/attachments.ts:10-18` 的 `AcpPreparedAttachment`
（`preparedId/name/uri/mimeType/sha256/byteLength`，校验
`validPreparedReference`/`samePreparedReference`）；消费面镜像 = **agent-contracts
@0.2.0**（`AgentPreparedAttachment`/`AgentAdmissionEvidence`）。core 拿这个版本号
对齐 Server ACP DTO（补 `preparedId` 等字段）。0.2.0 源码当前在
`codex/plugin-chat` @ `4d555a09b2`（`plugins/agent/contracts/src/agent.ts`），
落 main 随下次 consolidation；core 需要先行对齐可按该 SHA 读。

**③ 放行闸门两事实（已排 P-E，闸门先行不阻塞）**：authority（permissions）与
`native_evidence`（harness）即 014 第二批 **P-E** 包（S-06 行已注 A/B/C/D 收口后
开——现已收口，P-E 即将派单）。core 建闸门/接线照做；事实到位前 `ready=False`
诚实拒绝正是双方约定口径，不算卡 core。

**④ profile 装配（名字已给，落 main 归 consolidation）**：三个扩展准确 id 在
S-01 行（main 在案）：`ordessa.profile-api`、`ordessa.profile-frontend`、
`ordessa.profile-chat`（同批 `ordessa.chat-api`、`ordessa.chat`；退役
`ordessa.agent-conversation`，P-C 已回执条件满足）。profile 代码在
`codex/plugin-profile` @ `2c48889a25`——1+x 结构下插件代码先驻分支，落 main 的
consolidation 需用户授权定时；core 可按 SHA 预备装配。baseline 安装清单补录 =
S-10 行（6 子包 + 顺序坑，可复制命令在 reports/P-A-report.md §R0）。

**对 core 串行计划**：INT-01 / INT-04 不受插件侧阻塞，可先行；**INT-02 的根
lock 干净重算需要 profile 三包 + model-provider 两包 workspace 目录在场**
（均在分支上），完整重算同样等 consolidation，届时一并纳入（S-02 已记五条）。

（core 线回填区）

