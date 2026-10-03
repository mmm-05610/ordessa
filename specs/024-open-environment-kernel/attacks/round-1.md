# 第一轮：V1 并行攻击、处置与复查入口

攻击快照：`models/v1.md`；边界 B1。三个代理只读、不写模型、不派下级。主会话是唯一修订者。
用量：spawn 3；任务 `/root/attack_a`、`/root/attack_b`、`/root/attack_c`；token/费用不可取得。没有产品测试结论。
原始报告中 A/B/C 有「D2未决」措辞：派发后用户已确认 D2，消息已通知；属于报告上下文时差，不能据此重新向用户问同一问题。

## 原始攻击记录

以下按统一格式转录代理返回的全部 23 项攻击内容；合并排版，不合并编号、删除矛盾或更改严重度。处置另列，不将修复意见当用户裁决。

### A：语义与组合

**A1-1 / blocker / V1 / 对象、激活、活动**
前置：后台job J，create活动A已成功，Usage全部释放，订阅关闭，J仍活。
序列：A终态→最后Usage释放→drain只查活动/Usage/已请求销毁未确认/hold/dependents→全部空→卸载owner。
矛盾：未请求销毁的活owned对象漏出blockers；没人用不代表停止。
不变量：所有管理中未确认终结对象必须有退出归宿。
建议：明确owned/borrowed/delegated及退出要求；owned available/unreachable/unknown默认阻塞，移交/脱管需证据/授权。涉及D2。

**A1-2 / blocker / V1 / 对象、使用、并发、退役**
前置：O available，无Usage；C可use，owner可destroy。
序列：T1检查可use未提交→T2检查无人用并删除→T1提交active Usage→销毁证据released。
矛盾：成功签发了已开始销毁对象的Usage，反向也可能删除已借用对象。
不变量：use/destroy准入有共同原子排序点。
建议：destroying状态、原子关新use+写意图后发效果，destroy/retire共享门；释放仍可用。强制毁共享对象需另产品授权。

**A1-3 / high / V1 / 活动、观察**
前置：同原生token通过不同通道报告成功/取消，允许乱序。
序列：真实写文件成功S→cancel到原生→返回「取消已处理」C→C先到冻结cancelled→S晚到只记conflict。
矛盾：身份合法不能证明取消效果；不可改终态与核对当前事实未闭合。
不变量：取消接收、动作、真实停止结果分离；到达顺序不是原生真相。
建议：owner/source/token/revision及充分证据；不可变发布结论与可纠正当前核对状态分开，冲突进入disputed/unknown。

**A1-4 / high / V1 / 嵌套、并发**
前置：A/B各max_inflight=1，处理器可同步调用彼此。
序列：X持A→子Y持B→子Z等A→A等Y/B等Z。
矛盾：X→Y→Z是DAG，等待图A→B→A却死锁；安装图也无环。
不变量：父子图、依赖图、等待图分开定义。
建议：验证调用上下文/held-resource集；禁止无声明阻塞重入，资源全序或等待图拒绝。是否开放同步嵌套是可选政策，不能拿静态DAG证明无死锁。

**A1-5 / high / V1 / drain、活动**
前置：unknown A及活对象O，核对/销毁是新活动。
序列：drain关新准入→reconcile拒绝→destroy拒绝→blocker永久保留。
矛盾：关闭新调用封死了解除blocker所需路径。
不变量：禁新业务，允许针对既存义务的收尾。
建议：business与closure准入分离，固定旧target/generation，保留cleanup表面，不放行任意新任务。

**A1-6 / high / V1 / Usage权限**
前置：A仅use-only，可解析Ref；use允许选rights/grantee。
序列：A请求给B use+destroy→只校A可use→B获权→destroy。
矛盾：使用权变成发放高权限能力。
不变量：使用≠授予，rights受可转授权上限和owner策略约束。
建议：acquire本人Usage与grant/delegate分离，验证grantee/ceiling/期限/撤销；共享邀请产品政策需裁定，可默认不转授。

**A1-7 / high / V1 / Binding配置与原生变化**
前置：B固定r1/t1，共享原生对象可被其他入口修改。
序列：B建立→UI改r2或MCP tools_changed t2→旧B按r1 digest准入→原生按r2执行。
矛盾：本地快照不能证明原生执行配置被冻结。
不变量：仅承诺实际可固定的轴。
建议：desired/observed/enforced区分；支持compare-and-invoke才保证执行固定；否则observed-only，记录执行revision unknown；共享配置变化政策不能隐式扩大保证。

### B：故障与安全

**B1-1 / blocker / V1 / 去重、并发、保障**
前置：两个线程同(E,principal,surface,key)，Store存在，无外部去重。
序列：都查空→各建活动写intent→两者发出→事后冲突。
矛盾：intent先行仍双发，没有唯一占位/dispatch持有权。
不变量：同去重域最多一个被授权发出活动。
建议：唯一键+原子占位/摘要核对/创建、CAS dispatch claim、事务级锁；Store失败禁止发送。

**B1-2 / blocker / V1 / 原生投递、保障、D1**
前置：native_internal入口memory活动，消息会触发效果。
序列：创建内存A→发送原生接收→环境崩溃→同key新代际重试→重复发送。
矛盾：不接管推理不能免除已经承诺的入口投递事实。
不变量：可能已投递不能重启当未投递。
建议：发送有独立delivery guarantee；默认durable intent或原生可核对token；memory要绑定原代际且跨代际拒绝自动重试，不能由D1推导重复投递授权。

**B1-3 / high / V1 / 终态与移除**
前置：取消接受/调度停止被adapter封成cancelled。
序列：真实success缓冲→cancelled先到冻结→success晚到conflict→对象漏记→retire按已终态放行。
矛盾：冲突未强制进入未决账，错误终态放行卸载。
不变量：取消RPC成功不证明托管范围停止；残留冲突阻塞移除。
建议：充分finish evidence，token/序号/角色；原回执保留，当前conflicted/unresolved及管理义务持续。

**B1-4 / blocker / V1 / 权限发行**
前置：A有read/use Ref；use可指定destroy或其他grantee。
序列：申请高权Usage→登记→后续每次rights检查因自己发的Usage通过。
矛盾：校验代际不能防合法远端用户扩权。
不变量：引用/使用/授予/管理四权分离。
建议：owner policy/caller/ceiling/grantee共同校验；release也校主体；撤权与admission共享线性点。

**B1-5 / high / V1 / idle_dispose竞态**
前置：最后使用者释放触发闲置销毁。
序列：U1释放→owner看到0→U2取得Usage→owner依旧执行destroy。
矛盾：瞬时闲置确认不排除新使用。
不变量：进入销毁前原子关准入，unknown不回available。
建议：disposing栅栏，派生Binding/hold参与；强制撤销共享Usage需明确策略。

**B1-6 / high / V1 / drain核对自锁**
前置：活对象或unknown要通过原Surface stop/reconcile。
序列：drain关准入→所有新管理活动也拒绝→无法消blocker。
矛盾/不变量：同A1-5；不能为补洞放行所有旧Binding。
建议：有限closure操作、既存目标/固定代际/pin；native stop声明维护模式，不能核心特判字符串/stop。

**B1-7 / blocker / V1 / 未发布启动残留**
前置：stage/instantiate会启动托管进程。
序列：stage已启动P→locator/cleanup事实尚未写时崩溃→重启只见安装清单无实例→启动P2→卸载只查P2。
矛盾：原子发布不是副作用持久性，未发布孤儿漏账。
不变量：声明托管的外部启动发出前有意图/关联，未发布也承担义务。
建议：stage attempt/token/temp generation先持久，恢复stage unresolved阻塞；无法核对保留orphan-possible，不按裸PID杀、不自动重启。

**B1-8 / high / V1 / 跨代际核对**
前置：g1 unknown，重启只剩g2 adapter但可读旧token。
序列：g1发T→重启g2→严格g1源核对被拒永unknown；或接受g2冒认g1带来控制权。
矛盾：兼容声明不证明同一原生身份，query/control未分。
不变量：新observer不得冒充旧owner，只读不能顺带控制。
建议：限权recovery binding含旧activity/native identity/token、新observer、兼容摘要；adopt另授权，旧Ref仍不可执行。

### C：开放环境与可接入性

**C1-1 / high / V1 / 原生衍生对象完整性**
前置：已授权原生入口，会话S。
序列：未知/branch-session直达→原生建S2→环境只见send活动→S2在原生入口工作→移adapter。
矛盾：强制核心枚举对象工厂会网关化；不发现却报全停会虚假完成。
不变量：新命令无需核心识别；只声称管理明确报告范围。
建议：对象发现/托管完整性complete/partial/opaque及中性发现证据；无法枚举时移除报告含未接管范围，投递成功≠原生完成。D2不可被漏记绕过。

**C1-2 / high / V1 / 动态目录与绑定**
前置：MCP原生入口B，目录R1。
序列：R2新增T2/改T1→旧会话调用T2→同key重试→T1删除后调用T1。
矛盾：冻结目录阻开放，隐式变摘要破审计，每目录变化撤绑定打断会话。
不变量：运输合同/adapter/环境配置/原生目录四轴分开。
建议：freeze明确字段，原生目录仅证据；同key重放已接收结果，不能重新执行；新工具不新增Core Surface。

**C1-3 / high / V1 / 轻查询生命周期**
前置：无Store/Harness/Profile的catalog，read无需Lease。
序列：读取打开内容→drain→无Lease→正文编码前retire实现。
矛盾：无长期Lease误解成无执行期阻塞；反补永久Usage使查询过重。
不变量：查询执行/编码期间实现短pin，结束释放。
建议：admission自动invocation hold；懒正文返回必须新query或声明对象/stream生命周期；独立无Store验收。

**C1-4 / high / V1 / 秘密输入与durable intent**
前置：短命令合法秘密输入，外部副作用durable。
序列：admission→完整快照泄密/裁剪快照失真→发送→崩溃→同key查询→移adapter读历史。
矛盾：实际输入/安全意图/去重指纹未区分，可能泄密、裁剪原生输入或偷偷memory降级。
不变量：合法原生输入完整，持久事实不含秘密，不虚称恢复重发。
建议：内存payload、安全摘要、secret ref分离；秘密指纹比较范围明确；恢复缺凭证unknown/refused，不隐式取凭证/执行。

**C1-5 / high / V1 / 长期对象漏blocker**
前置：watch J start成功，不自动idle dispose。
序列：usage/subscription全退出→J继续→活动/hold/dependent空且未destroy→retire。
矛盾：同A1-1，反过来所有历史对象也不能永久pin。
不变量：活托管责任、已关闭历史、借用关系分开。
建议：对象管理责任与释放证据分账，逐对象归宿。

**C1-6 / high / V1 / 第六类原生画布双向请求**
前置：画布adapter有原生UI；可主动要用户选择/保存位置。
序列：打开画布→Q选择请求→前端回应→断连→Q2→移前端承载而后端仍在。
矛盾：API仅invoke/subscribe，缺反向目标、reply权/hold与UI依赖；raw展示不能代替用户操作，也不能adapter替用户答。
不变量：已授权交互端接反向请求，缺UI报gap，单播控制≠广播观察。
建议：中性interactor/reply correlation、单一应答者、过期/重复应答处理，实例声明必需交互依赖。无前端全功能不是默认承诺。

**C1-7 / high / V1 / 控制背压与观察gap**
前置：高频日志+需答控制；用户一应答、另一只观察。
序列：观察队列满→控制P→observer gap/detach→responder慢→原生不支持pause→control delivery失败但open已成功。
矛盾：哪个事实unknown未定义；不应倒改open或把观察断线当会话失败；核心认payload品牌会泄漏。
不变量：adapter中性交付角色、控制与观察分账、无法pause不授权kill。
建议：observation/reply_required/reply/evidence角色和target；control独立deadline/failure，保留有界控制容量，未知角色gap不同于未知业务类型。

**C1-8 / medium / V1 / 移除后历史解码**
前置：插件私有codec结果，环境仅envelope。
序列：结果→移plugin→读历史只有壳或永久pin私有decoder。
矛盾：中性schema不自动保证完整原生正文可读；永久pin又不可移除。
不变量：最低事实无实现仍可读，正文缺decoder明确，不恢复执行权。
建议：中性投影含身份/边界/结果/证据/失联/安全摘要，opaque附件受限；可选只读decoder与执行adapter分离。

## 主会话逐项处置（V2）

保留所有原严重度。相同问题统一修复，但每个攻击有独立追踪号；「已修订」不等于已实机验证。

| ID | 处置与理由 | V2规则 | 复查/场景 |
| --- | --- | --- | --- |
| A1-1 | 接受；活owned对象和未发布义务全入账 | §V2-1 义务/退役 | S03/S14/S17，第二轮C |
| A1-2 | 接受；use/destroy/retire共同门，closing先于外部调用 | §V2-2 生命周期准入 | S14/S15，第二轮C |
| A1-3 | 接受；删第一到达胜出，receipt与当前证据分轴 | §V2-3 证据核对 | S12，第二轮A |
| A1-4 | 接受；DAG不当死锁证明，区分wait图/重入合同 | §V2-4 嵌套 | S16，第二轮B |
| A1-5 | 接受；限定closure可准入，既存目标保pin | §V2-1/2 | S13/S17，第二轮C |
| A1-6 | 接受；默认不允许调用者转授，owner policy端口发本人权利 | §V2-5 授权 | S15，第二轮A |
| A1-7 | 接受；不承诺原生配置固定；required guarantee不满足则拒绝 | §V2-6 Binding轴 | S18，第二轮B |
| B1-1 | 接受；唯一占位+事务/CAS，commit失败零发送 | §V2-7 意图/去重 | S10/S11，第二轮A |
| B1-2 | 接受；native发送也先意图；无Store不接有副作用发送 | §V2-7 原生投递 | S05/S10/S11，第二轮B |
| B1-3 | 接受；conflicted管理义务不可由terminal receipt抹掉 | §V2-3/1 | S12/S17，第二轮A |
| B1-4 | 接受；本人使用许可、授权上限、release主体校验 | §V2-5 | S15，第二轮A |
| B1-5 | 接受；idle与destroy同栅栏，不默认自动idle destroy | §V2-2 | S14，第二轮C |
| B1-6 | 接受；closure非任意旧invoke，不核心解析/stop | §V2-1/2 | S13，第二轮C |
| B1-7 | 接受；stage纯准备，instantiate/start先记durable义务 | §V2-7/1 | S11/S17，第二轮A |
| B1-8 | 接受；read-only recovery attestation，adopt控制另授权 | §V2-8 恢复 | S13/S15，第二轮A |
| C1-1 | 接受；管理完备度声明，opaque不声称全停 | §V2-9 管理范围 | S05/S06，第二轮B |
| C1-2 | 接受；固定运输轴，native目录可变，重放不执行 | §V2-6 | S05/S18，第二轮B |
| C1-3 | 接受；轻查询短pin直到编码结束，无长期Lease | §V2-2 | S09/S17，第二轮C |
| C1-4 | 接受；三种输入分离，秘密摘要不可裸hash，凭证不恢复重取 | §V2-10 输入 | S10/S11，第二轮A |
| C1-5 | 接受；同A1-1，borrowed只撤本方关系，历史不pin | §V2-1 | S03/S19，第二轮C |
| C1-6 | 接受；中性Interactor/ReplyHold与UI依赖 | §V2-11 交互 | S07/S08，第六类样例，第二轮B |
| C1-7 | 接受；控制交付单独事实，有界控制保留容量 | §V2-11 | S08，第二轮B |
| C1-8 | 接受；最低中性历史≠全部正文，可选只读codec | §V2-12 历史 | S19，第二轮C |

## 处置中的用户/技术分界

D1、D2由用户明确选择。默认不允许用户自行转授控制权、不新增自动adopt、不做强制shared destroy、不声称可冻结原生配置，都按现有授权边界闭合；若产品今后需要这些能力，另出政策和授权，不在本轮默默加入。
统一入口的托管副作用/native投递默认需durable intent，普通只读查询仍memory；不是引入每条内部帧执行链。技术规则不是让用户选正确性。
第二轮将轮换视角：A看故障/权限，B看开放/组合，C看生命周期/轻量/迁移。至少一个仍未参与模型编写的攻击者独立复查最终版本。
