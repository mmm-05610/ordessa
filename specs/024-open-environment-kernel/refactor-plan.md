# 重构实施方案（设计交付，未授权执行）

基于技术候选 `models/v3.md`；三项政策未确认时相应阶段保持条件/阻塞，不能照提案自动实施。最终审核状态见review.md与status.md。
先迁移权威和行为，再考虑源码归组；不是按“后端4包”重写。不得据本文件启动服务、迁移真实数据、调用模型、安装资产或发布。

## 结果行为与不可丢失的原生入口

一个Environment拥有安装选择、激活/实例代际、贡献发布、统一入口活动、对象/使用关系、管理义务与退出门。HTTP/CLI/本地只是入口；Server不再是平行插件中心。Harness保持启动/连接/原生协议/审批/内部推理与工具工作，不逐命令变成Core API。
创建活动、channel对象、原生session与业务Turn分离。已装实现可正常移除，但必须按用户D2交代已有责任；历史中性事实无需执行代码。静态资源移除本方关系而保内容，无需杀服务或删资产。

## 目标包组与公共接口

以下路径是实施建议，不代表已经搬迁；发行名/持久标识尽量保持。前端包组只列受影响合同，不强迫实体对称。首次行为迁移可保现路径，最后再归组。

```text
apps/server                         # 网络/CLI引导：构造唯一环境，鉴权、transport
packages/backend/
  environment-api                   # 新中性合同包，零运行实现
  pacthold                          # 现pacthold发行保留，唯一环境机制
  persistence-sqlite                # 可选持久事实/墓碑/受保护指纹实现端口
  server-plugin-api                 # 现server_plugin_api，transport扩展合同
plugins/harness                     # 原生agent协议/启动/会话，品牌知识在此
plugins/workspace, profile, ...      # 独立领域状态及资源/能力贡献
plugins/server-compat, runtime-compat# 有限forwarder + legacy readers/迁移来源
products/server                     # 选择/版本/依赖/端口装配，非运行权威
```

| 包/组件 | 公共接口（候选名） | 所有状态 | 允许依赖 / 禁止依赖 | 独立验证 |
| --- | --- | --- | --- | --- |
| environment-api（新dist `ordessa-environment-api`） | Manifest/Scope/SurfaceSpec/BindingSnapshot/Ref/ActivityReceipt/FactView、EnvironmentPort/ParticipantAdapter、Store/Policy/Fingerprint ports、ClosureContext只读载体 | 仅不可变DTO/协议/验证，不持注册表/实例/Store | stdlib；禁pacthold runtime、Server、plugins、品牌协议、业务合同 | 隔离wheel import、DTO作用域/compat/缺字段负例、无状态实例检查 |
| pacthold（dist保持） | `pacthold.public.Environment`及旧Core facade适配，activate/instantiate/bind/invoke/use/query/lookup/drain/retire/wait/subscribe/reply | 一个root：启用清单/activation/instance generations、committed contribution revision、Bindings、短pin/Usage、协作wait图/预算、Observation/Control交付投影；事实按StorePort，内存与durable区分；derived Obligation索引不第二主写 | environment-api；禁Server/Harness/业务插件/具体数据库driver/品牌判定；不依赖persistence实现而是注入端口 | 无Server/Harness/Profile/Store启动；controlled adapters；生命周期排列、纯内存query、scope拒绝和越权反例 |
| persistence-sqlite（新） | StorePort.transaction/read_facts/reserve_request/commit_result/lookup_request、ProtectedFingerprintPort（能力须D6及实施安全审核） | 持久BindingSnapshot、意图/claim/spent key、Object/Usage/Scope责任、证据/CurrentFact revisions、response slot、版本/来源；受保护key_id生命周期属指纹端口，非登录凭证库 | environment-api与stdlib sqlite/既有protected key port；禁pacthold runtime内部/Server/原生协议/业务DB | 临时真实SQLite事务/kill窗口、单writer ownership、并发占位、不可读fail closed、key轮换缺席不再发；不是用memory假测SQLite |
| server-plugin-api（dist保持） | HTTP/stream/wire transport descriptors、错误族/发现facet合同，映射Environment contribution DTO | 无执行/插件活跃注册权威；只合同 | environment-api；禁pacthold内部、宿主、插件、协议品牌 | wheel零宿主import、auth/签名不可放宽、版本负例 |
| apps/server | build_runtime注入Environment、入口principal/authorization mapping、transport mount/projection、网络stop只处理transport | bearer/origin/连接/路由mount shape/网络订阅；环境committed revision的派生索引，不能独立决定activation/retirement/result | pacthold.public、transport API、Store/Policy ports（产品注入）；禁Harness品牌/bridge路径/旧global core_db/业务record写 | 空清单host/local/CLI与controlled network；三入口同一次dispatch；双数据根隔离，历史root拒绝 |
| Harness（现dist） | ParticipantAdapter/SurfaceSpec/ScopeEvidence/NativeCorrelation、既有start/connect/close API | 原生协议、native session/配置、adapter进程证据、协议请求相关性、动态目录、内部审批、原生history locator；环境活动仅通过port报告 | environment-api/pacthold public与自身Harness API；禁Server内部/另Runtime/自造环境ledger | fake native peer多轮/未知新命令/反向审批/范围证据；controlled native-only UI gap；不真实推理 |
| 资源/领域插件 | Surface/资源projection与owner合同；Profile/facet/source-ref；历史只读decoder | 私有资源内容、业务revision/配置journal/外部事实；不独立判环境dispatch终态 | environment-api/其领域公共合同；禁host内部、平行执行主状态、必需Harness/Profile注入普通资源 | 独立read/list/更新/保内容移除；缺依赖/decoder降级；真实临时目录byte相等 |
| compat/legacy readers | 旧API forwarder，旧ID→中性历史索引；sealed migration source；只读旧codec | 只旧数据/业务事实，不能接收新执行写、无新Runtime/并行registry | 新public及原领域合同；禁核心反向import compat | 原协议/错误码fixture、legacy不当空库、无新旧双写；历史读取与缺实现明确 |
| product | explicit selected installations/versions、依赖/兼容/Policy/Store/Fingerprint装配 | 部署选择配置，不运行state机；无默认授权推导 | 公共组件接口；禁bridge内部位置、运行事实镜像 | 空/资源-only/默认组合、缺Policy/Store拒绝有保障effects，安装不自动启用 |

有些包当前发行边界不同，先共用合同与单权威，不为目标树拆无状态转发小包。API contracts禁止逆向import实现；包组不是发行包，Python各自pyproject/editable，JS仍root npm workspaces。

公共面兼容须具体版本化：当前`pacthold.public.CoreStore(path)`是具体SQLite构造（inventory），目标Core不反向import可选persistence包。旧构造调用者迁移到产品选择的StorePort/provider；旧submit/query facade只转同一Environment，不私造Runtime。若需要保持旧path构造，在**兼容包**提供显式桥并迁移导入，不把新具体实现反向re-export到核心。其API变化要在R0合同审查、R2/R5受控消费者回归中声明；不能笼统说所有旧API签名原样保留。旧测试有明确迁移去向和同一断言，不删测试追绿。

## 逐项复用/合并/适配/退役映射

| 当前机制 / 证据在inventory | 决定 | 去向与理由 | 必须更改语义/风险 |
| --- | --- | --- | --- |
| core/runtime / registration | **保留机制、合并权威** | 租约/unknown/注册批次的检验逻辑与public facade复用，扩为Environment | owner busy需覆盖活动/对象/scope/pin而不是只lease；Store读失败不能内存兜底空义务 |
| core/dispatch | **适配并拆保障** | admission/intent/dedupe/cleanup原则保留，StorePort及CurrentFact统一 | 不给所有query强制ExecutionPlan/Work/DB；创建交接、response slot/native投递、scope未知补全；原terminal Receipt不可改 |
| core/store | **提取复用** | SQLite实现移可选persistence包，生命周期注入、原文件名保持 | 一个Writer/完整事务锁域；dispatcher局部锁不能替未来多模块Store门；不一边调用一边持DB锁 |
| work_core Work/Ref/events/projection | **保留领域语义，适配读** | Work责任/业务关联归业务owner，安全Ref转换/历史projection可复用 | 旧Ref不能成为当前控制权；native identity/代际不猜；不用反向re-export将业务重新拉Core |
| work_core ExecutionService/Repository | **迁移新执行主写、保留历史读** | Repository已有注入连接接口可复用legacy reader；新dispatch全部Environment | 无参global db路径从生产执行退役；Work表可保但不再独立dispatch；不可“同一个key写两本账” |
| execution NeutralRunTracker/contracts | **保留证据分轴，退役独立管理** | delivery/cancel/evidence DTO原则移neutral API，tracker为adapter缓存/环境投影 | 缓存不能判重启无副作用/自动重发，cancel receipt不等stop |
| extensions loader/catalog/bootstrap | **复用发现/校验，合并生命周期** | entrypoint provenance/版本校验、纯stage移Environment loader | 不再all installed自动enable/建私registry；selector/finalization/host-control业务槽归领域owner |
| ServerPluginHost贡献事务/holds | **提取通用逻辑并合并** | 依赖拓扑、冲突校验、stage/commit/rollback、hold/retirement gate移Environment | methods/stream/http仍transport索引，仅一个committed revision；异常rollback保存外部义务，不能宣称全无副作用 |
| CoreBinding | **暂留薄适配后退役重复root** | 旧Server调用直接注入EnvironmentPort；旧API转发不创建第二Runtime | 原construct/open/close需要一root所有权；避免两轮stage分别commit造成半可见 |
| bootstrap LegacyCoreBinding/global db | **退役写桥** | product注入legacy reader/迁移port，移除core_db.configure_database单例开关 | 历史路径迁移需批准；不把legacy/product DB与core.sqlite强合库 |
| Harness旧providers/resource selectors | **适配** | 旧start/observe/finish原生实现继续；契约转Surface/Participant/Object/ref | 不重写推理/tool/compaction/审批；固定环境轴与native observed-only明确；各Profile来源不用同名覆盖 |
| Harness server_acp registry/runs | **拆关联、保留原生机制** | native transport/identity、release证据复用，统一对象与scope账 | 旧channel≡Turn执行不再直接用；launch-before-record改意图先行，回执/输出/义务同事务；single pair共享按Usage非client ownership |
| acp_admission | **领域识别下移、policy端口保留** | ACP methods/permission payload解释归Harness，环境校grant/ResponseSlot | 不建立Core审批业务；成功/拒绝/超时后owner复核都覆盖，保持已有native保护 |
| runtime-compat sealed SQL/resource contracts | **保留读与迁移来源、逐域外移** | SQL字节/编号保全，workspace/skill/credential/profile合同归owner | 不复活已裁定legacy worker链以追绿；无实现明确unavailable |
| server-compat领域Services/asset records | **拆装配适配，不整包重写** | 资源/会话/配置原领域DB、函数及tests复用；从融合plugin拆可独立启用 | 部分本地Profile已在monorepo与文档不同，R0重核owner；asset catalog不证明native加载 |
| P native-session history +配置journal | **保留事实来源、限权适配** | 原生继续信息是history/correlation owner；只读decoder与控制分开 | P脏内容先固定，不由basename/path/version继承旧控制权；额外native apply证据不当Core执行主状态 |
| wire/discovery/error-family/HTTP auth | **保留transport投影** | generic facet合同与错误族继续，插件贡献从Environment读取 | 动态可见性与HTTP预mount constraints不混淆；无Harness空结果不当Core brand知识 |

不能只在Pacthold内部完成：至少bootstrap、plugin_host、CoreBinding、产品清单/端口、Harness providers/ACP registry/runs、acp_admission、server-compat执行链、资源SDK和前端connector合同需改。完整接缝见evidence/migration-seams.md。

## 数据与身份兼容：无双写的切换

1. 保留发行名pacthold/server-plugin-api、既有extension id/entrypoint兼容标识、data-root/DB路径/schema_versions/SQL编号，源码路径移动不等于持久标识重命名。所有命名变更实施前补migration note并用户确认涉及数据项。
2. 新模型需要添加install摘要/activation generation、BindingSnapshot、intent/claim/ResponseSlot/Object/Scope、CurrentFact补充历史等事实。先临时fixture测试新增独立命名空间/读取旧库，再提出具体schema和成本，用户批准后方写真实数据。
3. 旧core_execution/core_operation/work_core/server_turns记录保持可读，Receipt terminal枚举原样；新的当前核对结论通过带revision的附加事实关联，不伪改旧结果。移除原执行实现也至少可读中性事实，正文缺decoder明示。
4. 任一时刻对一条请求只能一个writer：迁移先停该部署新业务准入、保既有运行/收尾，旧writer的活动完成或unknown固定归属；切换后新请求仅Environment写。旧入口只forward/投影，投影不能另判终态或作为恢复依据。不通过双写“比较稳定了再切”。
5. 一致性关系跨业务私有DB不声称原子外部事务：环境请求账是投递主写，插件配置journal仍是应用配置事实；用correlation和证据桥核对，投递成功不伪报配置效果成功。创建环境结果/输出对象/义务必须在同一环境Store事务。
6. 历史导入只做read索引时必须证明所有ID/事件数/digest/unknown/status保持；来源字段、native continuation私有定位符不能被新ref恢复执行权。无法解码/碰撞/缺迁移源拒绝，不把旧库初始化成新空库。
7. rollback在切换前可撤新实现保旧源文件/库；切换后已有新effects，**不能回到旧writer重放未知请求**。回滚先close新准入，保new事实/spent keys/原生范围义务，使用兼容新事实的只读模式/已验证fallback，待核对后再决定下一writer。未满足兼容不能热切旧版本。
8. key rotation/缺指纹port保spent key，禁止新派发；真实secret store路径/权限/密钥保护与稳定性需实施前安全方案确认，本任务没创建/读取key。

## 分阶段实施与验收/回滚点

每阶段都需明确下一轮实施授权、固定baseline及独立评审；当前main与P不是自动允许操作的选择。原测试迁移保ID/断言，继承红逐ID+原因对比，缺测试资产不当绿色。

| 阶段 | 行为不变量 / 工作 | 正例和反例门 | 缺席/未知行为 | 回滚点 |
| --- | --- | --- | --- | --- |
| R0 基线/政策/合同 | 钉M/P集成SHA与未提交文件，确认D1–D6、迁移安全、trusted code边界；列真实所有调用者/继承红 | 两树hash可复现；隔离import边界守卫要有反向import变异；未运行模型标未授权 | 基线/政策/原始ID账缺失禁止开始效果性实现 | 纯设计/合同，可撤提案，无数据变更 |
| R1 空环境与只读安装 | environment-api+内存Environment；选择启用与安装分离，单发布revision；静态资源/read/decoder短pin | S01/S02/S09/X11/X12真实受控，缺依赖零半发布、decoder兼容负例 | 无Store可读但effects拒；无policy无隐式权限 | 新包未切产品，可移除候选代码；旧生产链无变化 |
| R2 durable活动/义务 | 复用Core意图/幂等，唯一writer事务、BindingSnapshot/claim、创建原子交接、scope、CurrentFact、Q slot | S10–S15/X02–X06真实临时SQLite、多线程、逐窗口子进程kill；key/domain/秘密log负例 | Store不可读/commit失败零发送，指纹缺失按D6，unknown不再发 | 仅controlled fixtures；没有产品新writer，撤候选；不能删失败ledger |
| R3 合并插件权威 | Server generic激活提取到Environment；transport贡献一revision投影；旧loader/Binding只forward；闭合cut/closure/wait | S16/S17/X01/X07–X10；双插件共同drain、晚对象/新Q/撤权、atomic visibility、异步wait环 | closure关联/依赖授权未知拒绝/待人工；Scope证据不足retire pending | 切换前旧writer仍唯一；撤新forwarder恢复旧构造，不动数据 |
| R4 五类+画布受控adapter | 现Harness native入口适配，MCP动态/资源/短命令/watch/画布；完整安装→实例→交互→更新→移除 | S03–S08/S18/S19、六类全流程fake peer/controlled process；新增未知命令零Core修改、UI-only gap、borrowed不kill | 原生证据无支持unknown/observed-only；不凭mock说品牌已验证 | 假资产临时根，只受控停止；旧产品未切，原native实现保留 |
| R5 产品入口/数据切换准备 | bootstrap/product policy/Store端口；旧Session/Turn映射；明确前端合同；只读旧fixture兼容后提出真实迁移请求 | S20三入口single dispatch；两数据根隔离、历史无decoder、原protocol/result回归、byte/ID账 | migration provider/批准/兼容不足拒绝，不初始化旧根，不热替活native | 切换前评审快照/备份/读回滚路径；未授权不操作用户服务/数据 |
| R6 经另授权切换与实测 | 按部署关闭新准入、责任核对后选唯一writer；真实资产/成本模型/GUI验收范围由用户定 | 原生新增能力/正常移除两核心场景、真实角色审批/背压/持久重启；baseline suites逐ID；真实模型需另成本授权 | 未授权/资产缺席标未验；scope未知不报移除成功；未解继承问题逐项登记 | 新effects后不能旧writer重放；保新事实/unknown，按兼容只读恢复方案回滚 |
| R7 退役兼容写路径与源码归组 | 全生产入口证明single authority后撤compat执行/旧global；最后移动包组 | 静态依赖守卫+实际trace无旧writer、旧历史reader仍可读、独立wheel+根回归 | 任何未迁真实consumer保相应forwarder/明确阻塞，不能删断言制造绿 | 纯路径移动可还原；语义/data切换不能靠git revert撤effects |

R1→R2不是每query强加Store；R3前不重复创environment/Server双宿主；R4保留原生增强自由但不过度承诺托管完备；R5/R6是用户审核窗口，不在本轮执行。

## 基线回归与真实验证范围

- 后续使用docs/baseline.md的Python/Go/Node版本与分包安装方式；本轮没有安装依赖。先冻结实际测试ID/原因，再跑pacthold、server-plugin-api、apps/server、Harness、products/server、runtime/server compat、实际Profile/resources相关suite，不能用历史总数说新绿。
- 独立公共轮子要在没有Server/Harness/Profile的隔离环境检查；fake module不能代替缺依赖；缺资产/真实模型分列未验，不添加skip隐藏。
- 前端未来受影响contracts（typecheck+connector/unit/受控native rig）：Receipt/CurrentFact revision、ObjectRef/Usage/generation、response role/slot、Gap/ControlDelivery、pending removal/blockers、Binding desired/observed/enforced、history decoder缺席。此次不改UI。
- 强制negative guards：missing Store/policy/fingerprint，反向import，same-key异payload，旧epoch/ref，所有callback包括refused错误后owner丢失，半发布/半创建交接，unknown不重发，borrowed不kill，partial scope不给normal retire成功。

## 实施前必须交给用户的具体选择

当前D4/D5/D6答复需纳入最终review；不反复问D1/D2。下一轮另需：实施起点是审过的M/P合成SHA、具体持久schema/旧ID映射是否允许、fingerprint key保护/保留机制、切换/回滚窗口、真实资产/模型预算与发布权限。这些是实施前条件，不意味着本轮不能完成设计交付。
