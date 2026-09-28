# P-C 报告 — chat 真实接缝(命令目录 / 附件 / 三态提交)

日期:2026-09-28。分支 `codex/014-c-chat`(基线 main 491aa92392 + 本包提交,见文末)。派单:[dispatch/P-C-chat.md](../dispatch/P-C-chat.md)。
状态:**完成(受控证据级)**;生产级验收项按派单口径如实登记(见 §缺口)。

## 1. 提交账

| 提交 | 内容 |
| --- | --- |
| `e9fcb8ae41` | contracts 0.2.0 三态 send + 目录/附件/admission 成员;sessions 门面接线;chat-api r4;chat 前端四态/附件/三态接通;PC-6 旧链退役;PC-10 探针;测试 +17→+29;报告与接缝回写 |
| (本报告提交) | 终 SHA 回填(交付提交,SHA 见 git log 次条) |

终交付以分支 `codex/014-c-chat` 最新提交为准(以提交 SHA 交付,012 口径)。

未 push、未并主干、未动 products/tooling/apps/packages、`plugins/connectors/**` 与 `plugins/harness/**` 全程零跟踪文件改动(git status 实证,见 §5)。

## 2. 链路图(文字版)

**命令目录(R-Z2-3 / PC-2)**

```
品牌 adapter ──available_commands_update──▶ connectors/acp AcpClient.observeCommandFrame(只读,main 既有)
  ──▶ AcpClient.getNativeCommands(sessionKey)(client.ts:183,只读,main 既有)
  ──[新]▶ AgentClient.getNativeCommands?()(contracts 0.2.0 可选成员;AcpClient 方法签名天然满足)
  ──[新]▶ sessions 门面 commandCatalog(sessionKey)(model.ts;unknown 判决→error(原因),无成员/无键→absent)
  ──[新]▶ chat adapters facadeCommandCatalog(service)(四态 1:1:available→ready/loading→loading/error→error(文案)/absent→absent)
  ──[新]▶ createNativeCommandSource → slash 面板真实条目;缺席=一条带原因的禁用行;错误=来源级 error 可重试
```

**附件(R-Z2-2 / PC-3,plugin 半边)**

```
chat 附件条目(plus 面板)──由 facade attach capability 驱动(S-05 缺席/无 picker=禁用+原因,US5)
  ──prepare(idempotencyKey=item id)──▶ sessions 门面 attachments.prepare
  ──▶ AgentClient.prepareAttachment?(=connectors AcpClient.prepareAttachment,只读消费;port owner 生产缺席→诚实 refused)
  ──▶ 不透明 ref(preparedId+sha256)存入门面注册表;ChatInputItem phase=ready(reference)
  ──submit携 attachmentRefs──▶ sessions 门面 send(text,refs) 解析 token→完整引用(未知 ref=typed refused,不丢弃)
  ──▶ AgentClient.submitWithAttachments?(=connectors AcpClient.sendControlled:verify(sha256 全等)→authorize→prompt blocks)
  refused/unknown:条目保留(failed 带原因 / unknown 可重试同幂等键);release 摘注册表+port.release
```

**三态提交(R-Z2-1 / PC-4)**

```
AgentClient.send: Promise<void>  ──contracts 0.2.0──▶  Promise<AgentSubmissionOutcome | void>(冻结客户端零破坏,实测 tsc)
sessions 门面 send = 映射 owner:
  admission 证据可观测且未就绪 → refused(CAPABILITY_UNSUPPORTED/BUSY)【HTTP 前诚实拒绝,S-05/S-06】
  链路断(down)证据 → unknown(operationId=held requestId;草稿不降级)
  typed 拒绝 → refused(code+reason)
  旧 connector resolve(void) → accepted(=旧"进入发送路径"语义,兼容规则写进契约)
chat gateway:门面结果 1:1(chat-api ChatSubmissionResult);UI:accepted 才清草稿;refused 保留+原因;unknown 保留+禁自动重发
```

**PC-5 generation**:`admissionEvidence.runtimeGeneration`(AcpClient 只读消费链已有)→ sessions 快照 `runtimeGeneration` → chat-api r4 `ChatLocation.runtimeGeneration`(可选);`contextRevision` 保留 UI 内部语义;无证据=缺席,不造数。

**PC-7 reasoning**:`AgentMessage.reasoningState?`(streaming/complete/interrupted/unknown+durationMs)入契约;connectors 半边不动(登记 S-05 同族);chat 展示层:有证据用证据,无证据沿用 run 状态、不造耗时。

## 3. F3 对照(逐条:真实接缝已生效 / 诚实缺席)

| F3 断点(派单原文) | 现状 | 判定 |
| --- | --- | --- |
| connectors 三态 submission.ts:13-26、client.ts:657(只读消费) | 零改动,经 `submitWithAttachments` 真实消费 | 真实接缝已生效(受控级;生产 authorize 见 S-05/S-06 缺席行) |
| 附件 attachments.ts:35-41、client.ts:608-645(只读消费) | 零改动,prepare/verify/release/carry 全链消费;A06 往返 sha256 一致(门表) | 真实接缝已生效(受控级) |
| 命令 commands.ts:8-25、client.ts:183-195 全仓零消费 | **消费已接通**:contracts→sessions→chat 全链四态;getNativeCommands 不再零消费 | 真实接缝已生效(pi/codex 行按品牌播发;claude 行=PC-10 实测不播发→absent,S-07) |
| acp-next-submit.ts:92-141 wire authorize(头注自述缺 backend owner) | 协调器零改动(护栏);门面按同纪律做 HTTP 前诚实拒绝(admission 证据缺席=不伪造) | 诚实缺席(S-05/S-06:生产 `BackendAdmissionState`/authority 归 P-E+core) |
| server 端 plugin.py:201-227、acp_admission.py(只读) | 零改动;生产 `ready=False` → authorize 诚实 refused(CAPABILITY_UNSUPPORTED),与门面 fail-closed 一致 | 诚实缺席(S-06 机制归 core 在做) |
| agent.ts:118 send():Promise<void> 需升三态 | `Promise<AgentSubmissionOutcome \| void>`,兼容规则+三个消费者迁移记录在契约头(0.2.0 账) | 真实接缝已生效 |
| sessions model.ts:115-146 facade 供给 | send 三态映射+commandCatalog+attachments+runtimeGeneration 快照 | 真实接缝已生效 |
| chat adapters agent.ts:126-141/150-155(恒 absent) | gateway 1:1 三态;facadeCommandCatalog 四态;附件源真实驱动 | 真实接缝已生效(absent 处均带原因) |
| chat-page.tsx:202-220 附件入口 supported=false 禁用 | capability 驱动激活;禁用态仍带 S-05/R-Z2-6 原因(生产 prepare owner+picker 缺席) | 诚实缺席(S-05/R-Z2-6) |
| PC-6 旧链 | `plugins/agent/conversation` 九文件删净;引用零残留;变体构建 11 扩展通过 | 真实退役(S-01 回执已给) |
| PC-10 claude 命令 | 受控探针:全通道零 `available_commands_update` | 诚实 absent(第一手转录,P-C-pc10-probe-transcript.json) |

## 4. 门与反例(终态全过)

| 门 | 断言 | 证据 |
| --- | --- | --- |
| 命令四态 | ready/loading/error/absent 全部注入实测;恒 absent/伪命令=红 | sessions seams(PC-2 三例:available/无成员+未知键/四种 unknown 判决)、chat seams(投影 1:1、slash 源、页面级 ready 行+absent 原因行);loading 仅受控注入,现无连接器产出(§缺口) |
| 附件往返 | 受控链 sha256 一致;refused 保留;仅 UI 可点=红 | A06:sessions seams「prepare 注册→carry 收到同一 sha256」+ chat seams 页面级「prepare→ready→send→transport 收到同 sha256」;refused=条目带原因保留且发送被阻;unknown=独立 phase 可重试同幂等键 |
| 三态保真 | refused/unknown 逐级到达 UI;unknown 不重发 | sessions drafts(unknown=值,operationId=held requestId)+seams(fail-closed 三例);chat composer-flow(unknown 保留草稿、sends 计数=1)+新 unknown 值驱动用例 |
| 退役 | 文件删净、引用零残留、覆盖核对留档 | 九文件 D;grep 残留仅注释性提及;§PC-6 对照表;变体构建 11 扩展 exit 0 |
| 诚实 | claude absent、S-05/S-06/R-Z2-6 缺席处禁用+原因 | 探针转录;capability note/面板行文案测试;admission fail-closed 测试 |
| 回归 | chat-api 23=23、frontend 50≥35(+15)、sessions 40≥26(+14)、connectors acp 36=36、ordessa 48=48;tsc 0 | §5 计数账;无下降 |

## 5. 计数账(R0 → 终态)

| 套件 | R0(2026-09-28 基线实测) | 终态 | 说明 |
| --- | --- | --- | --- |
| plugins/chat/api | 23 | 23 | r4 全增量、零破坏 |
| plugins/chat/frontend | 35 | 50 | +15:seams.test.tsx(四态/A06/页面流/generation/reasoning) |
| plugins/agent/sessions | 26 | 40 | +14:seams.test.ts(PC-2/3/4/5 门面级);2 例按三态值语义更新 |
| plugins/agent/conversation | 18 | (套件随包退役) | 等价覆盖逐条核对见 §PC-6 |
| plugins/connectors/acp(只读) | 36 | 36 | 零改动零回退 |
| plugins/connectors/ordessa(只读) | 48 | 48 | 零改动零回退 |
| `tsc --noEmit`(apps/desktop 全仓) | 0 | 0 | 含冻结客户端(OrdessaClient/测试 fixtures)对 0.2.0 契约零破坏 |

环境:Node 22.22.1 / npm 9.2.0(`npm ci` 自锁);vitest 各包 `npx vitest run`。F8 复核:extension-protocol.ts:11、build-extension.mjs:23、contract.ts:22-24 三处 C7 切换均在 main,未重做。

**根聚合说明(预期红,非本包门矩阵)**:`npm run build` / 产品守卫在 `ordessa.agent-conversation` 仍列于 products 启用清单期间必红(build-all 拒绝无包 id)——这正是 S-01 装配翻转要消除的状态;摘除该 id 的 11 扩展变体构建已实测通过(ORDESSA_PRODUCT_MANIFEST 受控变体,真实产物与锁未动)。

## 6. PC-6 退役留档与等价覆盖核对(S-01 条件确认)

删除:`plugins/agent/conversation` 全包(build/manifest/package/src×4/tests/vitest.config,git D 九文件);`@assistant-ui/react` 声明随包消失(根锁摘除归 S-02);sessions 入口 `agent.open` 不再打开旧 view id。

等价覆盖逐条核对(旧 18 gates → 新面;integration-request §4 预声明的 FC-0052/IME/拒绝保草稿三行已在 composer-flow):

| 旧 gate | 新覆盖 |
| --- | --- |
| 1 unknown≠failure | chat display 'failed and unknown never merge' + composer-flow unknown 用例 |
| 2/3 options 面不渲染 model/thinking | 设计性不移植(chat upstream-manifest D04 dropped);能力保持 unsupported 不假绿 |
| 4 工具状态标签 | display 'failed and unknown never merge'/'generic bash'/structured-command 用例 |
| 5 草稿打开零后端+门禁 | composer-flow draft gate 2 例 + sessions FC-0021 零调用例 |
| 6 createAndSend 一次+确认才清 | composer-flow typing-while-pending + sessions C-0030 拦截反例 |
| 7 拒绝保文逐字 | composer-flow 'refused send keeps the draft' |
| 8 续聊沿原项目 | sessions 'continuing an existing session…' |
| 9 Enter/Shift+Enter/IME | composer-flow 输入用例(三段) |
| 10 断连保文+断连发送 | composer-flow unknown 用例(现以门面 unknown 值驱动) |
| 11 每会话独立缓冲 | DraftStore pane 隔离例 + X05 换页不串 |
| 12 同 id 双连接不串 | connectors 频道键控测试(只读,main 既有)+ sessions 每连接 draft 例 |
| 13 草稿跨连接往返/discard 清空 | sessions 切换零发送/endedBy=discarded 例 |
| 14 陈旧选择失效不丢文 | sessions 'invalid restored project…' |
| 15 未上报失效的镜像拒绝保文 | sessions refused/unknown 值例 + composer-flow refused |
| 16 pane/key/session 同一谓词 | chat-page 移植保留 + X05 |
| 17 步离草稿走 createAndSend | sessions 'draft first send reaches createAndSend exactly once' |
| 18 开同一会话双方存缓冲 | sessions openSession endedBy='opened' 语义 + DraftStore |

**确认:S-01 的 `ordessa.agent-conversation` 退役条件满足**,回执已写入 seams 行内。`apps/desktop/renderer/agent-conversation.test.tsx` 在 main 已不存在(T019 移包),core 侧无删除动作。

## 7. PC-9 / PC-10 结论

**PC-9(S-05 核实,零代码改动预期兑现)**:`plugins/connectors/acp/src/attachments.ts:10-18` 复核——`AcpPreparedAttachment` 含 `preparedId`(注释明言 Server ACP DTO 未携带),`validPreparedReference` 逐字段校验、`samePreparedReference` 全等比较;对接基准即此形状,缺的字段在 Server ACP DTO(归 core)。P-C 对 connectors 零改动(git 实证)。回执已写 S-05。

**PC-10(claude 命令探针,S-07 命令项)**:受控拉起钉版 `@agentclientprotocol/claude-agent-acp@0.81.2`(闭包 `npm ci` 产物;loopback fake Anthropic API+一次性 config+fake token;零真实模型/凭据;plugins/harness 零跟踪文件改动),完成 initialize→session/new→prompt(end_turn)→3 秒观察窗,**全通道零 `available_commands_update` 帧** → claude 行命令目录=诚实 absent(该品牌未播发),chat 已按此呈现。第一手转录:`P-C-pc10-probe-transcript.json`(同轮 initialize 回执实证 `promptCapabilities:{image:true,embeddedContext:true}`,佐证 S-07 附件修正与 P-D)。探针:`plugins/chat/probes/claude-native-commands.probe.mjs`(node 直跑,不入 vitest 聚合,避免套件依赖闭包存在性)。

## 8. 缺口与 PARTIAL(逐条带归属)

| 项 | 状态 | 归属/条件 |
| --- | --- | --- |
| 生产附件 prepare owner(picker/字节通道) | 诚实禁用+原因 | S-05(core 通道)+ P-E(owner);落地后 UI 即亮(PC-3 全链已受控验证) |
| 生产 admission authority/`BackendAdmissionState` 供给 | fail-closed 拒绝(CAPABILITY_UNSUPPORTED/BUSY,HTTP 前) | S-06(core 机制)+ P-E(authority);门面 fail-closed 纪律已就位 |
| 文件 picker 通道(R-Z2-6) | 附件条目带原因禁用 | S-05 同族接缝(派单明示不扩本包) |
| reasoning connectors 半边(reasoningState 产出) | 契约+展示层就绪;现无连接器产出 | S-05 同族(PC-7 时间盒,登记);无证据时沿用 run 状态、不造耗时 |
| 命令目录 loading 态 | 契约可表达;现无连接器产出 | 登记即可(四态门以受控注入实测) |
| `SkillsChatSnapshotPort`(Q1 消费面) | 不在 main,只登记形状(PC-5) | Q1 线合并后消费 |
| 根产品构建红(见 §5) | 预期,随 S-01 装配翻转消除 | core S-01 |
| 根锁 `@assistant-ui/react` 摘除 | 随 S-02 INT-02 干净构建重算 | core S-02 |
| 真实浏览器矩阵/Electron 门 | 本期以受控与 jsdom 证据为界(spec 范围裁定) | 装配后集成轮 |

## 9. 兼容与契约修订账

- agent-contracts 0.1.0 → **0.2.0**(manifest+package 同步):三态 send(`Outcome|void` 冻结兼容)、五个可选成员、`reasoningState`、`runtimeGeneration`;修订账在 `agent.ts` 头部。消费者迁移: sessions 门面(映射 owner)、 chat gateway(1:1)、 旧 conversation 视图(随 PC-6 退役)。
- chat-api r3 → **r4**(全增量):`ChatLocation.runtimeGeneration`、`ChatSubmissionSnapshot.attachmentRefs`、`ChatAttachmentPhase.unknown`、`ChatPrepareResult.unknown`、add-content 幂等键入参、ready 命令 `description`;修订账在 `contract.ts` 尾部。r3 消费者语义不变(测试零删改通过为证)。
- 子代理:未使用(0 次),全程本会话实现+自审。
