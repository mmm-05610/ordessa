# 夜间验收合同：逐条 ID、反例与证据

状态：待执行。与 `overnight-handoff.md`/`overnight-tasks.md` 配套。
下列 `[ ]` 表示**当前交接候选尚未完成该条验收**，不意味着所有代码还没实现。
旧证据可引用以避免重做；最终修订影响到的门必须在最终候选重跑。

## 0. 证据口径与总完成门

每行先写受控正/反例，再写实际证据；测试名称可以按现有风格命名，行为不得变弱。
人为植入缺陷/旧实现跑红和新实现跑绿保留摘要；同批新增正向测试不能冒称先红后绿。
缺资源/字段/观察能力=BLOCKED或FAIL；不是PASS。命令要保留真实退出码，不能用后续 tail 覆盖失败码。

证据等级：L1受控单测、L2实际原生可执行文件/无模型、L3后端真实供应商、
L4实际Electron UI操作链、L5安装后的产品。低等级不替代高等级。

最终多Harness/Profile收口：A/B/C/D/P/F所有必需条目在当前候选通过，
S按原 `acceptance.md` 已有产品要求独立结算；旧18条缺一不得声明完整 MORNING_CANDIDATE。
不增加所有未来 facet 的应用要求，不降低已约定的安装/真实UI要求。

## A. Codex 原生进程、生命周期与历史所有权（T1，关键路径）

设计落点：`plugins/harness/packaging/native-profile/{codex-process,enhance,bridge,restoration}.mjs`。
采用锁定原生 app-server 的正常 initialize/thread/read/thread/resume 接口，不重造会话存储。

- [ ] **A01** 确认被管理 PID 的 executable/父子关系：证明是原生 Codex，而非仅 Node启动器。
  证据：自有进程树（路径脱敏）、native PID+启动时间、锁定版本。未辨明身份不得做替换。
- [ ] **A02** 正常关闭先关闭自有输入并等 OS退出事件；仅 `.killed=true`、unsubscribe ACK 都不算退出。
  反例：kill返回true但进程不退；必须禁止启动 replacement。
- [ ] **A03** grace→TERM→KILL 有界；强杀路径也证明原生后代已退出。
  反例：launcher退出但 native 仍活着；必须拒绝，不并排创建第二原生进程。
  推荐 Ubuntu锁定资产内直接启动已验证原生binary，解析/平台选择全在Harness；
  若保留launcher，须拥有并确认完整自有进程组，禁止只信launcher exit。
- [ ] **A04** 重启前/后始终只有一套本会话原生运行所有者；ACP父进程/transport不被重建成新会话。
  证据：原生PID变化、旧PID无存活（启动时间防PID复用）、ACP/通道ID不变。
- [ ] **A05** 输出中、configuration忙、lifecycle忙时零停止/零spawn/零resume；等待下一次合法发送。
  反例：卡住一次prompt并请求切换；输出不中断，下一发送才发生效果。
- [ ] **A06** 替换前读取本 owner 的 thread/read；thread.id必须精确匹配当前native session。
  反例：返回兄弟session.id；零close/stop/spawn。
- [ ] **A07** 历史路径必须是已持久化的本实例/已绑定历史；绝对规范路径、真实普通文件、所有权正确。
  反例：null、不存在、符号链接、父目录符号链接、目录、异主文件、越界路径均拒绝。
- [ ] **A08** 跨HOME恢复只允许上轮已绑定的同历史文件，不能接受任意客户端路径。
  正例：官方→API→官方同文件；反例：相邻另一个rollout或伪造此前绑定路径。
- [ ] **A09** 暂无持久历史时诚实拒绝恢复，不自动 session/new/复制空历史/创建新canonical。
  仅测试夹具可创建空native thread；产品不因打开草稿就创建空会话。
- [ ] **A10** 旧原生结束后 fresh native client正常初始化；新client/命令对象/事件handler指向新连接。
  反例：旧commands closure仍持旧client；读/命令/消息不能静默流向旧进程。
- [ ] **A11** fresh client初始化失败清理新进程，禁止自动retry；保留主异常及可见清理失败。
  反例：新进程已spawn但initialize抛错；最终无两套活进程、owner不恢复旧绑定。
- [ ] **A12** 显式原生resume同native session和持久rollout；不得把旧cached thread的ACK当恢复成功。
  证据：新PID+原生thread.id+真实恢复历史；只有替换对象不能通过。
- [ ] **A13** resume/模型应用/偏好读回失败保持Unknown/拒发，禁止备用newSession。
  反例：resume返回错误、返回兄弟thread、断开响应；效果一次、消息零次。
- [ ] **A14** runtime generation换代，canonical session/native session/逻辑owner连续；旧target失效。
  反例：凭旧generation提交配置/发送，效果前拒绝。
- [ ] **A15** 重放相同恢复operation返回记录，不再stop/spawn/resume；query绝不产生效果。
  反例：响应丢失但效果完成，连续query/replay；统计每个原生效果仍恰一次。
- [ ] **A16** 同operation不同input拒绝；输入/记录容量与字符串界限保留。
  反例：同ID换endpoint/model/凭据/target/account path、越界payload。
- [ ] **A17** 其他适配器实例/通道进程不受影响；只清理本次创建的PID/组。
  证据：B实例前后PID、generation、配置、可读状态不变。
- [ ] **A18** stdin close/ACP退出在切换前、中、后都清理当前拥有的native；无旧引用导致漏杀/误杀新实例。
  反例：初始化挂起时关闭ACP；新旧进程清理有界。
- [ ] **A19** 历史/参数路径只留在私有owner调用；公开回执/日志不输出本地历史正文/Key/账号身份。
  反例：上游异常包含合成secret；投影只保留关闭的原因码。
- [ ] **A20** 操作失败diagnostic同时区分restart/history/auth/model阶段，不吞错写observed。
  缺独立readback/route证据一律Unknown，不因model值相同误确认。
- [ ] **A21** 非目标平台/版本明确拒绝；不得落回未验证launcher或全局codex。
  反例：缺平台native包、二进制漂移、锁定源码anchor漂移。
- [ ] **A22** 原execution终态不复活；实际恢复的新运行依既有契约新建/绑定execution。
  若现有产品对此没有账本接缝，报告明确阻塞，不擅自设计pacthold模型。
- [ ] **A23** 真原生无模型恢复测试：利用受控端点/本次自有历史，证明PID与thread身份，不冒充L3。
  若必须先有真实首轮才能持久化，记录前置并由Lead在预算内建立，不能伪造rollout作真实证据。
- [ ] **A24** 独立复审A01–A23，特别是SIGKILL后代、旧closure、失败后owner三处；Lead亲跑受影响门。

## B. Harness 中双向供应商/账号恢复与 C4（T2、T7）

私有RPC可有品牌差异；Profile/model-provider仅提交中性意图。

- [ ] **B01** API目的地来自model-provider已解析中性配置/安全凭据注入；Codex差异仅Harness内部。
  反例：Profile直接选择native path/HTTP认证头；公有面拒绝。
- [ ] **B02** 官方目的地由Harness managed_account owner解析，Profile不存accountDirectory/token/keyring键。
  反例：API→官方但无factory、无认证、非Codex品牌；零原生恢复效果。
- [ ] **B03** 官方account目录专属、0700、正确UID、规范真实目录、与实例目录不交叉；用原生keyring。
  反例：world-readable/符号链接/同instance目录，停止前拒绝。
- [ ] **B04** 官方模式不调用gateway setter、不用API Key模拟订阅、不登录/登出/复制全局`.codex`。
  证据：原生account/read为chatgpt与thread.provider=openai；公开证据仅bool/安全路线。
- [ ] **B05** API模式CODEX_HOME为独立实例；parent env/route guards跟随新模式，不借共享官方home写API配置。
  反例：第二次切换仍使用旧accountenv、旧gatewayConfig/旧headers，必须被探针抓住。
- [ ] **B06** 凭据重新从拥有者取得，prepare/execute输入digest/fence复核；Secret不进plan/记录/磁盘配置。
  反例：prepare后Key/账号scope/desired/publication变化，效果前拒绝。
- [ ] **B07** 恢复独立确认当前session route/model/config及新generation，再生成恢复票据，不能只相信请求意图。
  反例：响应provider不符、route缺席、同generation、错model、旧owner，均不生成成功票据。
- [ ] **B08** 恢复票据不是Profile应用完成；在新target上重新compile/独立验证，得到本轮C4 receipt才发prompt。
  反例：只返回restoration ACK、无新C4；prompt计数0。
- [ ] **B09** 每轮模型以用户选择为准；保持其它受支持偏好，不把额外参数丢掉骗过model-only门。
  反例：reasoning参数不同/不支持；明确拒绝或支持的精确读回，不静默defaults。
- [ ] **B10** 实际L3官方→Go：首轮短随机标记，第二轮准确回忆；同canonical/native，PID/generation换代。
  两次C4、恢复恰一次、实际Go出站携带首轮上下文/原生正确历史展开。
  反例：可回复但不含标记、Go HTTP=0、只有previous_response_id且无可用跨端点上下文，均FAIL。
- [ ] **B11** 实际L3 Go→官方：同一场景第三轮准确回忆首轮标记；第二次换PID/generation，官方认证/route独立确认。
  不新建会话、不让旧API密钥污染官方请求；官方刷新机制不改。
- [ ] **B12** 同时运行官方B和API对照；A双向切换期间B配置/generation/native身份不变。
  不要求B重复推理；只读足够验证不串配置，若需验证事件路由先用受控对端。
- [ ] **B13** 与Pi live、Claude恢复的现有成功语义无退化；Node/Python策略选择回归、归属门均通过。
  不为Codex引入全品牌必须restart的通用假设。
- [ ] **B14** 将失败的两条旧Codex历史探针保留，新增成功证据绑定新资产/SHA；不覆盖旧失败日志。

## C. Profile 与 ModelProvider 的会话配置语义（T3）

本段基于既有接口完成，不重新设计schema。每条至少L1；C02/C03/C08/C10/C16还须在实际产品链L3或L4观察。

- [ ] **C01** 全局Profile仅存配置图纸，session持有选择+逐字段临时覆盖；无完整native HOME副本。
  反例：同Profile两session必须不同instance，Profile记录不含凭据正文/native目录。
- [ ] **C02** Session A临时切model，Profile全局配置逐值不变、Session B不跟随A变化。
  观察DB/公开读取+原生有效配置；仅UI标签变化不算。
- [ ] **C03** A覆盖model后全局同时改model与未覆盖的偏好：A下轮保留临时model，未覆盖偏好跟随全局。
  反例：全局覆盖A临时model或整个Profile被overlay冻结，均FAIL。
- [ ] **C04** 覆盖以字段而非整个facet标脏；provider/model相互约束由资源插件中性校验+Harness适配处理。
  反例：孤立model与provider不兼容，明确错误，不自动选另一个用户未选model。
- [ ] **C05** 显式切换同Harness Profile清空旧临时覆盖、无弹窗，次轮应用新Profile完整意图。
  反例：旧model/provider/偏好残留，或把清空动作回写全局。
- [ ] **C06** 输出中变更仅记录选择/override，零原生set/restore、零cancel；不立即发送。
  反例：server通知或frontendrerender触发配置效果。
- [ ] **C07** 连续选择P1→P2→P3，到下一发送只应用最终意图；被取消的选择不产生恢复副作用。
  记录revision/fence，不把“最新”实现为无校验盲覆盖。
- [ ] **C08** 全局revision在prepare/execute间变化：旧plan拒绝/重读；若效果已Unknown，仅query，禁止盲重做。
  反例：旧revision被confirm、重复应用旧凭据。
- [ ] **C09** resource贡献者卸载，设置项从编辑页消失但数据保留；重载后原值恢复。
  不能伪造配置可应用；发送时必需提供者缺失有明确拒绝。
- [ ] **C10** 首次Profile准备失败不创建假会话：草稿逐字保留，可修配置后显式再发，零重复session/new。
  首发只有接受后登记有效会话；已创建但结果Unknown则仍遵守查询语义。
- [ ] **C11** Unknown不清草稿、不标成功、不自动再prompt；通过相同operation查询收敛。
  注入transport在setter后断开；效果计数恰一次。
- [ ] **C12** failed/refused不产生可用C4 receipt；用户能纠正参数后执行明确新操作，操作ID不能复用不同输入。
- [ ] **C13** runtime换代后旧owner/target/context不可缓存复用；同canonical获得新有效绑定。
  反例：旧reference执行model action，效果前拒绝。
- [ ] **C14** Provider配置保存/编辑不依赖DNS；实际probe仍做SSRF/DNS边界。
  反例：Fake-IP保存应成功，probe走被拒地址仍不能假绿；不放宽全部内网网段。
- [ ] **C15** provider/model目录来自真实后端/资源插件，不前端硬编码品牌/可用性。
  反例：安装资产缺失、catalogue空/畸形、外部model不支持，诚实禁选/错误。
- [ ] **C16** API Key经系统密钥环持久化，重启可读取，锁定/缺席明确拒绝，不降级明文文件。
  测试自有locator保存→跨进程读取→删除；scan DB/log/export无合成secret。
- [ ] **C17** Key删除/替换影响未来准备；运行中的Agent不中断；不把旧缓存继续当有效授权事实。
- [ ] **C18** 单官方账号与API配置分离；切model不隐式选择官方认证或强制全局切provider。
- [ ] **C19** Profile基础CRUD/命名/Harness归属/配置持久化不退化；重启同图纸可读取。
  未增加会话跨Harness切换；草稿可选择Harness，但已绑定的会话不能静默变品牌。
- [ ] **C20** Profile编辑扩展面通过公有facet/contribution；不import资源插件私有实现、不处理Codex/Claude配置差异。
  以AST/边界反例证明，不是仅grep零命中。
- [ ] **C21** ModelProvider只拥有provider/model/credentialRef数据和UI业务；不成为process/session协调者。
  配置应用都经Harness公开能力；无第二份provider adapter逻辑。
- [ ] **C22** 独立复审覆盖全局更新/overlay竞态/Unknown/卸载恢复四组，Lead亲跑受影响门。

## D. Desktop UI → 生产发送路径（T4、T8）

不能用内存Server、UI-preview或“14插件挂载成功”代替实际生产发送。

- [ ] **D01** 默认启动真实Server与完整插件，UI能找到三品牌及Profile目录，无origin未设置/无限loading。
- [ ] **D02** 新建草稿只打开UI、零ACP open/new；选择项目/目录正确，第一句提交才创建会话。
  反例：切项目、打开profilepicker、取消弹窗不能留下空会话/原生进程。
- [ ] **D03** Profile picker二级Harness/Profile；已绑定会话仅同Harness切换可执行，不加跨Harness切换。
  无可用项/服务断连有可恢复错误，不假列表。
- [ ] **D04** model-provider picker提供provider/model选择，选项与后端能力一致；模型加载失败能显式重试。
- [ ] **D05** 选择Profile/model后不提示一堆内部换代状态；显示所选值，错误时明确指出未应用。
  不新增每次确认弹窗、额外“生效模式”操作步骤；内部证据仍完整。
- [ ] **D06** 输出中换Profile/model保持流式输出、不cancel、不自动发送；下一次显式send应用最新选择。
  受控流可钉时间窗口；实际UI至少一次此行为，后台配置方法计数在send前0。
- [ ] **D07** 首发 prepare→native session→canonical登记→C4→prompt次序可追踪，project验证先于开通道。
  反例：项目拒绝，openAcpChannel=0、native new=0、线上帧=0。
- [ ] **D08** 后续同provider model切换执行正确原生策略；跨provider用既有restore接口，不在React写native配置。
- [ ] **D09** accepted只在真实契约确认后更新UI；refused/Unknown不当消息发送成功；输入草稿保留。
- [ ] **D10** Unknown按钮/后台查询不触发第二prompt、新session或第二restore；断网重连不自动重放。
- [ ] **D11** 项目目录加载失败支持就地重试；断连/清目录后已知会话仍可见，不能从sidebar消失。
- [ ] **D12** Sidebar session切换正确；A流式事件/审批/工具不出现在B，双同名native IDs受控反例通过。
- [ ] **D13** 输入区域固定、消息区域独立滚动；文本/thinking/tool顺序稳定，完成后无残留loading。
- [ ] **D14** 工具真实由Harness执行；UI正确展示名称/输入/运行/结果/关联，至少一次受控项目只读工具。
  不把fixture卡片截图称真实执行；不新增Ordessa中间工具执行/权限拦截层。
- [ ] **D15** 原生approval若宣告支持：同UI实际allow/deny至少覆盖，决策回正确session；不宣告则不伪造模式。
  新外部sandbox/permission策略不在本轮设计；缺实际宣告/事件证据不能N/A糊过去。
- [ ] **D16** Pi UI两轮：选择Profile/供应商，消息实际发出，原生model/route与C4、回忆关联准确。
  后台旧成功可复用协议结论，但不能替代本条UI证据。
- [ ] **D17** Claude UI两轮：真实provider/model与Profile应用；至少真实首发+下轮应用，跨provider后台B类历史证据可关联。
- [ ] **D18** Codex UI首发+官方→API：当前新资产，保留会话历史/列表身份，实际出站/原生generation相关性正确。
  API→官方可用同backend三轮场景证明，UI需要至少选择与生效一次，不额外无限推理。
- [ ] **D19** 全局Profile改动+本会话临时覆盖，在实际UI/后端链完成C03场景；DB/route/界面三源至少两源对齐。
- [ ] **D20** 重启后Project/Profile/历史列表存在；旧runtime状态诚实为结束/失效，不伪造活连接。
  用户显式恢复按既有接口；不实现未设计的自动后台常驻/所有旧会话自动恢复。
- [ ] **D21** 未安装/未登录/供应商401或429/连接失败单会话诚实报错，另一会话和设置页仍可用。
  这些错误用受控对端，不能真实烧额度来制造429。
- [ ] **D22** 浏览器登录入口如现有产品应有则可用，Ordessa专用账号状态可见；过期/退出采用原生机制。
  不制造真实token过期；受控拒绝+当前真实登录readback即可，不创建多账号系统。
- [ ] **D23** renderer无Node/Key/认证headers，密钥输入提交后不在日志、组件公开props或导出中保留。
- [ ] **D24** UI证据绑定实际产品版本/asset/session，Lead独立执行，不沿用worker“截图看起来没问题”。

## P. 可信资产、产品装配与发行（T5、T6、T9）

- [ ] **P01** 新Codex资产从既有锁文件/固定源摘要构建；所有增强closure文件参与完整treeDigest。
  反例：漏helper、源码anchor漂移、lock漂移、篡改文件，构建/校验失败。
- [ ] **P02** 新候选做L2启动/首次准备/隔离验证；无模型门不能伪称恢复聊天通过。
- [ ] **P03** 只创建新asset目录；既有Pi/Claude/Codex资产与账号不覆盖。脚本拒绝已有destination/链接。
- [ ] **P04** 安装脚本pin verifier、treeDigest、版本、entry/counts/bytes；stage→verify→publish→verify原子化。
  错摘要、可写资产、UID/父目录不可信失败；不能只校验entry文件。
- [ ] **P05** root管理且普通用户不可修改，完整策略校验通过；用户执行sudo前此条BLOCKED_USER。
- [ ] **P06** default产品资产指向已验证新来源，无静默全局CLI fallback；三品牌来源与能力可诊断。
  asset目录只是安装候选阶段条件，不能当开箱产品的用户必须手工长期步骤。
- [ ] **P07** Python/npm插件按发行装配加入，manifest/lock由build生成，frontend/backend端口实际都存在。
  反例：代码包存在但默认装配漏配；启动门必须失败或明确功能缺席，不成功空壳。
- [ ] **P08** deb从最终候选构建，包含必需server/plugin/runtime或明确产品内bootstrap路径，
  **不能要求新用户另跑本次`.cleanup-evidence` sudo脚本才能具备基础功能**。
- [ ] **P09** deb无worktree绝对路径、不依赖本地editable/sourcecache/Key文件；native路径只在Harness内部解析。
- [ ] **P10** 普通安装后默认`~/.ordessa`按产品既定布局安全建立/复用，私有权限；不默认tmp或旧agent-box目录。
- [ ] **P11** Desktop实际监管自有Server：传origin/token、生命周期/端口/锁正常；不要求用户手动另起backend。
- [ ] **P12** 缺依赖/资产/产品组合fail-closed并给具体修复入口，不降级为fixture/空host。
- [ ] **P13** 安装包真实正常启动→项目→profile→一真实Harness任务通过；其他两品牌用同候选L4验证关联。
  不能只解包或dev Electron当“安装验收”；未sudo安装则本条保持BLOCKED。
- [ ] **P14** 关闭/restart后只清自身进程，native/Server无异常孤儿、锁可释放、配置与历史持久化。
- [ ] **P15** Ubuntukeyring与官方登录说明准确：正常系统自动发现，锁定提示；不默认明文兼容fallback。
- [ ] **P16** 最终deb文件名/SHA256、源码SHA、bundle/asset摘要齐全；完整用户启动/试用步骤可直接执行。

## S. 旧验收合同既有资源项，不悄悄抹掉（可并行审计，不做新平台）

- [ ] **S01** 列出现有Skill/MCP与其默认装配/facet/runtimeprojection支持状态，不以“代码存在”替代可用。
- [ ] **S02** 原合同Skill最小smoke：一份自有最小Skill正确进入支持Harness输入/projection，两session隔离。
- [ ] **S03** 原合同MCP最小smoke：自有本地stdio MCP能发现，至少一次工具结果到现有Chat UI；无外部付费API。
- [ ] **S04** 支持的既有prompts/instructions/runtime-preferences等跑compile/projection门，
  不为不支持的facet返回fake-success。全面逐资源L3不是本轮新增要求。
- [ ] **S05** 若现有实现缺真正合同/适配，列阻塞与既有产品目标影响；不临时把大型新资源方案塞进夜间任务。
  S02/S03未过，则原18条产品floor未过，报告不能省掉这两个格子。

## F. 最终验证、证据与交回（T9）

- [ ] **F01** root npm test当前聚合清单已核对，不能沿用旧“146测试”记忆；每个sub-suite计数/退出码可追溯。
- [ ] **F02** typecheck/build/相关workspace/ACP rig/packaging/Electron门以最终候选运行，记录环境及退出码。
- [ ] **F03** Profile/model-provider/Harness/products/server/Server/Pacthold Python受影响回归及最终全量门实际运行。
- [ ] **F04** inherited red按ID+原因和开工基线比较：零新增未解释红；原红不删除、不xfail掩盖。
  粗计数一致不是证明；若基线环境不同，先对齐锁定安装再比，不抄旧数字。
- [ ] **F05** 新生命周期/Unknown/归属守卫有缺席反例和注入命中证明；只grep零命中不能过。
- [ ] **F06** 冻结candidate后不再动源码/资产；若修一个文件重跑受影响门并更新全部候选指针。
- [ ] **F07** Key/refresh token、登录identity、真实消息正文不入git/log/screenshots/DB导出；扫描由脚本只报bool。
- [ ] **F08** 自有临时通道、进程、MCP、relay、keyring测试locator全部列清并清理；未删除用户账户/历史。
- [ ] **F09** 他属截图、root main、相邻worktree、旧installed assets未动，显式pathspec提交，本树已验证产物可追踪。
- [ ] **F10** 进度固定TODO每项链接到本合同ID/当前证据，部分实现不勾整项，旧失败未覆盖。
- [ ] **F11** 最终独立审阅把所有发现一次性整理：严重度、复现、原因、修法、验证；重要缺口修完同候选再审。
- [ ] **F12** 交回不是“最后还有一点”：列确切PASS/FAIL/BLOCKED/NOT_RUN及用户动作，
  完成只能COMPLETE_VERIFIED；缺安装/登录/网络/用户操作明确PARTIAL，不再加隐形验收阶段。
