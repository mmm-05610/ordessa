# L4 线性任务清单

全项顺序按plan。复选框初始未完成；只有对应证据齐才能勾选。每项具体执行方法见所属工单和acceptance；同一单的任务默认串行。

R3强制追加：contracts/relationships.md（E3/F3）§8将受管理关联交付分配到既有工单/阶段，A66–A75纳入验收；R3时本清单96个任务，不表示追加交付可省略。对应工单的codeReady必须包括分配到该单的S/I证据，不能仅以旧任务复选框宣告完成。

## 001 固定可复现的产品迁移基线

- [x] T001-01 只读核对main/P HEAD、merge-base、commit范围、脏文件所有者、根/子目录AGENTS及服务注册；输出批准范围冲突，禁止照过时AGENTS排除现插件。
- [x] T001-02 逐文件分类源码/测试/装配/文档/运行数据/凭据/生成物；来源manifest仅源码路径和digest，秘密文件只记录排除规则，不读正文。
- [x] T001-03 列出main与P的功能差异及现有验收引用，特别history、同Profile重选、model切换与输入闪烁；非引用证据不得当现测试通过。
- [x] T001-04 提交明确源合成和实施树建议并等待授权；获批后在同一实施树固定来源，未获批保BLOCKED，不自行commit其他人脏改。
- [x] T001-05 运行npm test -- --list并保存可发现suite清单；经许可在隔离环境跑Python/JS基线，保存每个失败ID/原因/skip/error及命令版本。
- [x] T001-06 形成baseline-receipt（合成SHA、源digest、授权、继承红、未验证GUI和资产）和恢复点，保证未跟踪024/025/026设计在实施树可读。
- [x] T001-07 冻结允许导入的不可变源码manifest（type/mode/link/content digest），前后重算并拒并发编辑/越界symlink；输出Python collect、Go package、独立ACP rig/lock、安装子进程suite发现表，见C2与shipping。

## 002 冻结联合契约、保证等级与兼容清单

- [x] T002-01 读取024V3最终修订和025V4§14，并将M04–06对旧候选的覆盖条款映射到每个affected case，不覆盖历史。
- [x] T002-02 冻结environment-api DTO/Ports/error族及版本；TypeScript F1/C1数据类型、canonical codec与Python对应wire序列化正反例能编译互通。
- [x] T002-03 Q01–Q12逐项列实际Harness支持、required保证、raw差异、provider职责和消费者；未支持原生原子性标unsupported而非上层重试补齐。
- [x] T002-04 定义request key作用域/完整输入MAC编码（附件/配置/目标）、密钥port/轮换/未知保存，可靠与raw显式选择；key失效不自动降级。
- [x] T002-05 冻结public API/export/Token/carrier/extension ID发行身份清单，列old CoreStore构造与领域carrier兼容例外/消费者及退出单。
- [x] T002-06 新增契约测试覆盖PythonDTO/TS wire identity、编码版本不产生新writer、scheme/realm/owner校验、领域程序集零host import。
- [x] T002-07 输出批准合同版本与hash，新增设计语义差异提交用户；已批准内部实现选择可自行锁定，不要求用户逐个选方法名。
- [x] T002-08 联合冻结C2恢复协议、E2/F2生命周期证据及shipping合同：同根排他、跨模式request key、跨库marker/查原ID、附件不可变、三序号/RecoveryBinding、native alias、frontend fence；每项有编译类型和对应反例。

- [x] T002-09 联合冻结E4/F4数据空间/宿主交互/秘密诊断、E5持久关联、A1 Agent公开合同，类型/codec/错误/缺席保证与A76–A95逐项映射，不引入第二核心。

- [x] T002-10 按plugin-architecture冻结领域路径与逻辑manifest schema、公开exports、旧发行/入口/数据identity映射；检查元数据不二次调度，列每个移动消费者。

## 003 实现可独立运行的空环境与中性对象模型

- [x] T003-01 建立environment-api独立pyproject与stdlib契约；保pacthold发行/import名称，新public.Environment不导入业务或具体Store。
- [x] T003-02 把安装选择、activation、instance、capability、ObjectRef、Activity、Usage的唯一索引归Environment root；拒完整身份不匹配。
- [x] T003-03 复用现core registration/providers/Ref校验；execution与资源编排保为内部机制，纯query/static能力不强制ExecutionPlan。
- [x] T003-04 实现显式空启用集、read/query/lookup入口，installed不自动enabled；历史read与invoke权限分开。
- [x] T003-05 隔离wheel/venv只装API+核心，执行无产品/无Server起停；将核心反向import和第二root故意注入作为失败反例。
- [x] T003-06 记录公开入口与实例identity，证明两个环境/两个数据根不共享模块级registry；给004/005同root消费接口。

## 004 将插件激活与退出权威合入Environment

- [x] T004-01 提取ServerPluginHost拓扑、冲突、stage/commit、holds与loader校验到Environment；不并存两个registry或scheduler。
- [x] T004-02 实现贡献事务及发布revision，失败撤未公开贡献；失败激活产生的外部对象登记settlement，不宣称无副作用。
- [x] T004-03 实现drain cut原子关新准入：与并发invoke/late open的线性化点明确，旧generation回调不得改新activation。
- [x] T004-04 实现closure root/cut/original grant/role/dependency/budget规则，停止确认与晚对象清理可继续，伪新业务拒绝。
- [x] T004-05 实现owned/borrowed usage退役：owned要范围退出证据；borrowed仅release；static移关系保内容；unknown不删。
- [x] T004-06 实现预检、异步等待关系与跨参与者退出排序，检测真实等待环；不因用async就认为无死锁，不加Agent协作业务。
- [x] T004-07 受控双插件激活失败/退役、晚事件、权限撤销、未知职责测试，所有状态仍来自单root。

- [x] T004-08 在同Environment实现持久关系声明/反查完整性/变更reservation与引用准入的统一门，区分Usage/持久引用/历史关系，测试并发和停用不擦引用。

## 005 提取SQLite持久化并验证真实故障窗口

- [x] T005-01 从现CoreStore提取SQLite实现与工厂；Core仅StorePort，兼容旧构造消费者迁移，不核心反向export实现。
- [x] T005-02 定义fixture新增schema与只读旧schema映射，保持原库命名与migration编号；真实数据写需另许可。
- [x] T005-03 以事务保存request占位、Activity、creation→Object/Usage、原Receipt与currentFact、response slot；外部调用不持DB锁。
- [x] T005-04 实现ProtectedFingerprintPort依合同用系统secret port的opaque key；临时测试key仅fixture，真实托管缺席可靠受限而raw不被禁。
- [x] T005-05 子进程kill分别覆盖intent前、持久intent后投递前、外部接纳后回执前、结果commit前后，重启查询与未知不重发。
- [x] T005-06 并发同ID同输入仅一个准入/相同回执、不同输入拒；跨ID同response slot只消费一次，两个data root隔离。
- [x] T005-07 测试SQLite只读包含WAL、事务失败/锁冲突/缺密钥/轮换/损坏schema；保原Receipt不变，晚证据修CurrentFact且冲突不自动解锁。
- [x] T005-08 输出新schema和真实迁移风险/备份恢复提案；没有许可只fixture，不提前开用户DB。
- [x] T005-09 落实C2同根跨进程writer排他、key轮换墓碑/独立history-read；真实暂停旧writer/双进程/正文过期测试；同步CoreBinding与产品具体Store构造消费者，防005→006依赖死锁。

- [x] T005-10 实现可注入DataAreaPort与文件/SQLite公开适配、稳定namespace/句柄/兼容schema及获批迁移准入；隔离fixture验证卸载保数据、旧版本拒写和CAS声明。

- [x] T005-11 实现持久引用跨Store与领域提交intent/证据/恢复、coverage未知和reservation崩溃保护；同根fence下不自动解锁或重做外部效果。

- [x] T005-12 扩现SecretStore为受管理SecretPort，OS适配不入内核；验证purpose/代次/renderer仅引用、locked拒绝、轮换和删除引用/在途责任，MAC墓碑保留。

## 006 Server变薄并切换全部环境入口

- [x] T006-01 bootstrap由产品显式注入Environment/Store/Policy；应用只网络/认证/入口启动，移除global core_db配置与平行binding根。
- [x] T006-02 ServerPluginHost变有限投影/forwarder，methods/http/stream按同committed revision映射；保原签名/auth/origin与端口边界。
- [x] T006-03 server-plugin-api提纯transport契约并迁backend，应用不导入环境内部registry/privateStore；网络断线只释放transport。
- [x] T006-04 盘点所有入口与旧sidecar/work_core/NeutralRunTracker路径；旧执行新请求转Environment，旧记录只读，不能为绿复活退役worker。
- [x] T006-05 本地/CLI/HTTP/WS对同controlled provider检查dispatch次数/identity/receipt，错误族/发现与能力不可用行为保持明确。
- [x] T006-06 受控切换freeze准入、旧closure/unknown接管与route失败回退；新effects后只能兼容事实回退，不能热回旧writer。
- [x] T006-07 将pacthold/server-plugin-api物理归backend，同步pyproject、lock引用、安装脚本、CI、wheel隔离测试；保持发行/import/data标识。
- [x] T006-08 按C2效果fence受控切换，activation/instantiate/config apply/control reply均算外部效果；证据不足不能旧writer回退，旧实现仅既存closure继续者。

- [x] T006-09 接可选backend/platform-services到同Environment；SecretStore兼容入口转同实现；按compat-retirement逐项拆清server/runtime兼容业务、切换旧入口到同Environment，仅保有证据的薄发行壳及封存迁移，保持原发行与入口ID。

## 007 Harness与资源按开放参与者接入

- [x] T007-01 Harness现start/connect/close保实现，增加Participant/Surface/Scope证据适配；native session/channel/Activity/Turn身份分开。
- [x] T007-02 品牌目录内部组织Codex/Pi/Claude生命周期及配置/资源适配；provider/profile/skill/mcp业务保持中性，不复制品牌判断。
- [x] T007-03 原生模型/provider/配置查询与应用按C1能力声明适配，不承诺native不支持的CAS；安装资产不重建除非新增必要协议。
- [x] T007-04 迁native-history的稳定owner/instance/native ID与只读decoder，空draft选择不创建原生会话；点击历史才native load/resume。
- [x] T007-05 资源/服务参与者支持静态catalog不需Agent/Profile/Store；borrowed MCP/外部服务release本方usage，owned进程退出scope测试。
- [x] T007-06 controlled peer支持/workflow/未知event/原生控制确认：原样有界、可信control单消费，不新增核心命令API。
- [x] T007-07 所有resource/provider来源范围/退出范围声明；partial/opaque owned实例不足证据retire pending，shared关系不误杀。
- [x] T007-08 保三品牌现有controlled回归逐ID，记录真实资产和登录测试未跑不冒称Pi/Codex/Claude真聊天通过。
- [x] T007-09 按E2保未知delivery_role义务与三序号/RecoveryBinding；独立第四种controlled Agent和独立静态资源包构建/安装/退出，可靠可unsupported，不核心品牌特判。

- [x] T007-10 逐域将assets资源归顶层插件，业务/API留owner，品牌适配迁Harness内部品牌/资源模块；保全部现资产与支持矩阵，不按目录名整体搬错。

- [x] T007-11 资源消费者改用DataArea/公开绑定与E5关系声明；Provider归档不深扫Profile，关系coverage和变更竞态受控验证，资源无Profile仍可管理。

- [x] T007-12 独立外部资源包通过公共数据空间/关系/秘密可选能力安装运行，缺Agent/Chat/Profile及OS适配有明确降级，无私有宿主import。

## 008 迁前端包组与Workbench组织权威

- [x] T008-01 逐包移动API/ui/components/connections/bridges到frontend；loader+host合extension-runtime但保Lumino唯一依赖管理。
- [x] T008-02 Workbench明确迁frontend/workbench；内部navigation/views/layout/overlays/settings/focus按职责组织，不拆巨量空包。
- [x] T008-03 app host-services.settings/main overlay迁Workbench展示注册/容器；平台设置作为贡献，业务值留原owner。
- [ ] T008-04 foundation分通用carrier与Agent领域carrier；更新所有consumer specifier，不平台反向export业务；共享Token运行身份测试。
- [x] T008-05 同步npm workspace/exports/import-map/tsconfig/build顺序/extensions lock/package lock/packaging脚本/test discovery，保证旧extensions完整空覆盖。
- [x] T008-06 迁connector对app内部NativeTransport依赖到公共contract；api入口无Electron/React副作用，main入口不落renderer bundle。
- [x] T008-07 真实typecheck/build/Workbench host/ui-components/connection suite与空产品smoke；overlay定位/Esc/窗口按钮不被挡、settings关闭/输入焦点受控UI验证。
- [x] T008-08 前端preflight冻结dispatch/required借用/batch publish同门，拒/超时恢复原贡献；跨窗口晚dispatch/晚required依赖屏障竞态；U待验不阻S/I codeReady但全单不DONE。

- [x] T008-09 按逻辑manifest和发行映射迁frontend入口/connector职责，products与原运行manifest仍选择/调度权威；共享carrier一份，backend与frontend可按需启用。

- [x] T008-10 将通用commands registry/execute迁同runtime、键绑定与面板归Workbench、业务handler留插件；旧ID薄forward，原生slash不转平台命令。

- [x] T008-11 增量冻结F5中性API/错误/Token/保证缺席矩阵及合同摘要，登记002清单增量；固定复用候选版本/许可/锁，不重写已完成基线。
- [x] T008-12 实现owner私有写入口与消费者只读状态容器、稳定不可变快照、批量通知、selector/equality及scope自动退订；runtime不存全局业务值。
- [x] T008-13 提供独立React状态选择绑定，真实构建两个非Agent消费者验证共享同源、字段变化更新及组件卸载，不让无关通知重写输入。
- [x] T008-14 实现复用E3观察的授权只读投影与普通read查询缓存，连接/权限/目标代次隔离、合并/分页/invalidate/有界清理及显式刷新重试策略。
- [x] T008-15 实现scope关联的异步等待任务、捕获目标和晚到结果屏障，区分取消等待与原操作取消，unknown保原关联不自动重发。
- [x] T008-16 实现非Chat依赖的公共编辑会话和设置绑定：base/edit revision、字段mask、dirty冲突、校验接口、保存结果关联及秘密字段隔离。
- [x] T008-17 实现可注入UI持久化合同与宿主fixture适配、命名空间/版本/条件写和布局恢复；无适配明示session-only，不保存业务正文或凭据。
- [x] T008-18 在Workbench实现统一通知/进度/选择确认接口及作用域句柄，消息更新不闪烁，取消不伪报停止；普通对话框复用既有浮层。
- [x] T008-19 完善命令上下文单源投影、翻译/图标回退及公共组件键盘焦点规范，when只管可用性不代替执行授权。
- [x] T008-20 接入全部F5 suite发现、真实包出口和两个独立fixture插件，完成A96–A103/A109定向正反例及依赖/生命周期回归。

## 009 实现通用交互面与受控桥接

- [ ] T009-01 interaction-surfaces按通用target/schema/ref绑定，unknown kind/command原文降级；不要求Agent/Chat目标。A60必须穿实际connector/SDK，不能直feed新surface绕过旧过滤。
- [ ] T009-02 connections仅本地phase/句柄/settlement；late open后scope关闭释放，关闭连接不伪remote stopped。
- [ ] T009-03 native/server bridge分api/main/isolated executor入口，caller/activation/lease/target授权及await后重核；认证留main。
- [ ] T009-04 明确可信内建与不可信模块执行域；禁止第三方main顶层动态import。隔离嵌入面CSP/IPC只授所需能力，不全局放宽sandbox。
- [ ] T009-05 每跳raw byte/decoded/queued/history预算与credit/gap快照恢复；超限typed拒或明确incomplete，关键状态不吞。
- [ ] T009-06 编辑与surface input ticket绑定target/epoch/lease，输入法composition尾Enter不发送；global Esc只消费一层，触发器消失返回有效焦点。
- [ ] T009-07 独立构建非Chat terminal/document视图测试，无Profile/Agent也可附着；旧generation绑定/伪审批/伪窗口身份反例拒。

- [ ] T009-08 实现Workbench普通dialog与native-bridge文件/目录/clipboard公开能力，替换Chat全局picker/Profile window.confirm，验证取消/撤销/晚到不写及选择不授访问权。

- [ ] T009-09 复用013日志/诊断公开scope注入与跨前后端关联、sink脱敏和late片段预算；诊断仅观察不probe/apply，日志不成为Receipt主账。

## 010 收束配置、会话、草稿唯一领域所有者

- [ ] T010-01 Agent域提供ConfigOwner/SessionOwner/SubmissionOwner，DraftOwner与通用edit合同分离；runtime登记槽不吞domain state。
- [ ] T010-02 移除Profile selection/glue的selections/lastConfirmed/retained/bindings/clickQueues写权；Profile只目录解析/操作源和薄UI贡献。
- [ ] T010-03 移除model next-turn-client/chat-api-entry的pending/sequence/route/queued/current写权；codec仅关联请求，模型单项公开操作。
- [ ] T010-04 实现present/unset字段、provider/model原子组、点击seq、异步解析归序、目录版本不追改capture、同Profile重选新opId。
- [ ] T010-05 实现native ConfigEvidence known/unset/unknown及snapshot/patch链，乱序有界缓存，同revision冲突阻capture，重复原观察不解锁，完整新快照清旧缓存。
- [ ] T010-06 实现稳定target/binding/native generation适用性与跨窗口同owner，selected只投影，binding替换旧queued操作stale且不自动重base。
- [ ] T010-07 草稿stable draftId/revision/editorLease，view离开收尾仍能更新；成功只消费捕获revision，ABA同文本不清新稿。
- [ ] T010-08 禁用Profile产品矩阵实构建运行controlled两轮和model切换；Agent/Chat/model不需要Profile私有serializer或身份。
- [ ] T010-09 按E2逐字段迁ACP connector/session model的sessionList/runs/interactions/firstSends/pendingControlledSessions及alias写权；同native第二连接unverified只读，owner unknown不因重建client/晚success解锁。

- [ ] T010-10 落实A1 Session/Config/Submission/Run/Interaction owner公开只读/dispatch/Harness证据入口；同会话确认与操作单owner，前端代理无第二writer。

- [ ] T010-11 资源选择控件与Profile facet走公开贡献及Agent操作，无私有binding/serializer；Profile字段覆盖、同预设重选、无Profile模型切换和无Chat资源管理都有证据。

- [ ] T010-12 将Agent/Profile/model选择控件迁公共只读订阅及操作入口，移除控件镜像和重复缓存；字段覆盖语义及原配置owner保持不变。
- [ ] T010-13 将Chat草稿及至少一个资源设置编辑页迁公共编辑工具，保领域owner、字段校验、未知保存及IME缓冲，测试dirty冲突/ABA与迟到保存。
- [ ] T010-14 接入公共任务/通知/进度与查询机制，证明资源管理无Chat/Profile依赖；完成A104–A106并扫描第二写者和私有服务导入。

## 011 贯通发送、恢复与真实产品链

- [ ] T011-01 实现capture事务固定draft/附件/配置opIds/base/target/binding/schema/保证等级；UI选择/晚编辑不得改捕获快照。
- [ ] T011-02 可靠路径持久request+fingerprint/reservation后调用Harness所声明条件提交；raw入口显式，绝不从可靠失败降级。
- [ ] T011-03 首次create-with-config/creationAttempt关联与existing session分开；选择不create，unknown创建只核对，不new第二实例。
- [ ] T011-04 分记config partial/input known-rejected/accepted/unknown和native run结果；UI异常说明准确，不把一切写连接中断。
- [ ] T011-05 断线/应用崩溃重启持久关联只读reconcile，历史列表启动即读、点击才load/resume；旧owner/new generation不冒认。
- [ ] T011-06 输出时Profile/model改意图不stop；应用完成UI模型标签更新同owner，输入每键不触发send错误闪烁。
- [ ] T011-07 controlled三品牌provider/model切换与多会话隔离、同provider变化/cross-provider native restart/resume按原生支持；不修原生内部非阻塞问题。
- [ ] T011-08 获单独许可后真实Pi/Codex/Claude各两轮、profile→model→profile、重启历史、官方登录与API并存隔离；缺许可/资产保测试BLOCKED，不把controlled算真实。
- [ ] T011-09 按C2跨库mapping→possiblySubmitted→backend intent→native效果→领域result，真kill配置生效输入前等窗口；冻结附件内容避免MAC A/native B；同K可靠unknown换raw/key失效零重派。

## 012 退役旧权威并完成发行前整体验收

- [ ] T012-01 遍历old path/import/export/entrypoint/构造/registry/store/route生产引用，清zero-consumer兼容，保批准公开facade指向唯一实现。
- [ ] T012-02 确认packages仅frontend/backend底座包组，旧desktop-platform/workbench/pacthold/server-plugin-api无运行实现；移动后的测试数量/ID发现映射可审计。
- [ ] T012-03 npm ci从锁安装、typecheck、真实build/npm aggregate/Electron controlled、Python各包+全链；逐ID和cause比基线无新增未处置红，不删assert/skip假绿。
- [ ] T012-04 干净venv隔离wheel导入与bare host、独立extension build、deb生成/解包/无凭据clean smoke；运行打包检查不签名/publish。
- [ ] T012-05 所有acceptance必需场景正例反例证据，真实三品牌用户动作截图/日志关联脱敏；GUI/模型缺授权不算完成。
- [ ] T012-06 数据fixture旧库/WAL/未知schema/两根/rollback/crash+秘密扫描+无追踪binary/userdata，真实数据若不获批注明未迁不能许诺已升级。
- [ ] T012-07 更新architecture/baseline/naming/reference/migration/known-issues及云端draft（仅获对应token权限），目标与实现状态分开；不偷偷修改AGENTS。
- [ ] T012-08 固定实施SHA、完整完成/缺口/兼容余项/操作步骤/安全回退点和main集成请求，用户批准前不合main不push。
- [ ] T012-09 按shipping从解包产物验证required wheel/entrypoint/启用清单闭包，缺required不skip；默认和无Profilecontrolled两轮，禁止repo editable补依赖；发现清单逐suite重验。

- [ ] T012-10 从干净发行产物验证领域插件多入口/旧ID与namespace兼容、backend-only/frontend-only及三外部样例，默认闭包不能用仓库源码或旧兼容引擎补。

- [ ] T012-11 回归E3/E4/E5/A1和插件结构A66–A95全部必需场景，扫描第二关系/命令/配置权威及核心业务import；更新目录文档与剩余compat退出清单。
- [ ] T012-12 从干净发行产物运行F5 API/React出口、独立插件和存储fixture，覆盖A107/A110；不以仓库源码或模块单例补发行/跨窗口保证。
- [ ] T012-13 逐项回归A96–A111并执行A108/A111真实Electron输入/通知/焦点/UI恢复验收，记录资源缺席；更新公共接口、例子、依赖图及未验项。
