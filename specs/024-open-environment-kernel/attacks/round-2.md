# 第二轮：V2 轮换攻击与修订

快照：`models/v2.md`。A改故障/权限，B改开放/组合，C改生命周期/迁移；仍为三个只读代理、不参与模型编写。
请求累计6（第一轮spawn3＋本轮followup3）；本轮17条新增攻击：1 blocker / 13 high / 3 medium；token/费用不可取得。
所有结果为模型推演，不是生产复现或形式证明。原始返回有些问题延续第一轮；不通过改编号/降优先级掩盖未关闭。

## 原始攻击内容（统一格式转录）

**A2-1 / blocker / V2 / 活动、对象、退役 / V2-1,2,7**
前置：创建有intent、临时代际，原生P启动并返回owned O。
序列：提交ack/success→启动义务resolved→对象/owner/活义务未提交就崩溃→重启仅见成功无O→退役放行。
危险：唯一账不能防半结果，内存pin不能跨崩溃保责任。
不变量：启动义务连续存在，只能原子转交完整对象义务或足证无残留。
建议：创建完成事务原子提交结果+全部ObjectFact+owner/generation+义务转交；不完整保starting/orphan_possible；partial输出保scope义务。

**A2-2 / high / V2 / opaque输入、安全去重 / V2-7,10**
前置：未知命令可能含secret，无fingerprint port。
序列：K输入credential=a/action=deploy→仅元数据持久→K改b/delete→元数据相同→误当同输入；裸hash又泄低熵secret。
危险：已识别secret路径修好，无法分类opaque路径未选准入结果。
不变量：完整合法输入必须安全比较，不能元数据冒充。
建议：未知一律敏感保守，完整内存payload+受保护port/immutable secret refs；缺能力发前refuse。C1-4同重大矛盾仍在。

**A2-3 / high / V2 / durable Binding恢复 / V2-6,7**
前置：B1内存，K成功持久，响应前崩溃。
序列：重启B1不可解析→客户端selector建B2→同K因Binding变更摘要冲突→读原回执无入口；忽略Binding则误认新实例。
危险：防再发不等于可脱离活实现读取结果。
不变量：durable请求的历史绑定/回执可解析，新Binding不能替旧操作执行。
建议：持久BindingSnapshot；按verified principal/logical surface/key只读lookup，返回旧receipt/current；revoked同键只读，不能dispatch。

**A2-4 / medium / V2 / 证据序号 / V2-3,8**
前置：native N/T无持久原生序号；g1本地rev40，g2恢复query本地rev1。
序列：g1 success40→g2权威核对发现证据不足1→按同native源判旧/按不同observer源无合并规则。
危险：合法核对不能修正，或本地数字冒原生因果。
不变量：native revision、observer epoch/sequence、CurrentFact revision分开。
建议：source identity/epoch、核对专属规则/覆盖证据；不同observer本地序号不横比，缺原生总序保持disputed。

**A2-5 / medium / V2 / reply重放 / V2-7,11**
前置：Q/H，durable key K，答复成功而回执丢。
序列：consume H→重试同K→先查H无效拒绝；保持H有效又可换key二答。
危险：第二应答拒绝与同键重放顺序不明确。
不变量：spent H不能新发，但旧key可只读receipt。
建议：先verified principal历史lookup/完整fingerprint比较，已存在返回原与current；新请求才检查/消费H，读取仍校当前read权限。

**B2-1 / high / V2 / 单次应答占位 / V2-7,11**
前置：同responder两个客户端同Q/H，不同K1/K2。
序列：A允许K1，B拒绝K2→两次查H有效→各有intent/claim→两答发出。
危险：key去重不能保证Q唯一答案。
不变量：同Q最多授权一个效果性发出，跨key也有效。
建议：Q+generation+delivery revision的unique response slot/H消费与admission同事务；issue_possible后不因崩溃/过期重发或换人，新key拒绝，原key重放。

**B2-2 / high / V2 / drain后新控制请求 / V2-2,11**
前置：drain前画布C，正在保存。
序列：drain→原生新Q要选路径→new ReplyHold→reply因Q晚于drain拒绝。
危险：现有工作不能结束；按旧C全部放行又可新业务。
不变量：必要收尾交互可继续，旧会话不是无限工作通行证。
建议：Q关联既存work/closure obligation与范围，允许必要新Q，不明关联用户处理；不按Q创建时间一律拒/允。

**B2-3 / high / V2 / unknown delivery role / V2-9,11**
前置：新帧需回应，旧adapter不能分类，但知native incarnation/session。
序列：frame→adapter_gap，无Q/义务→原生等待→drain用旧协议空闲证据放行。
危险：gap不自动成责任，未分类交付破坏完整性；全未知日志都阻塞也错。
不变量：unknown业务type可透传，unknown role不能证明只观察/无工作。
建议：有界unclassified-delivery关联对象/native revision、交互完整性unknown及核对义务；充分scope证据解，不自行构造审批/回答。

**B2-4 / high / V2 / partial scope正常移除 / V2-1,9 / 延续C1-1**
前置：环境owned I，partial，新命令开未发现J。
序列：已声明对象全结束→managed_scope查询空→义务索引空→删除实现，只说未证明全停。
危险：改措辞未保证D2，partial能缩小范围绕退出等待，或另一读者认为永久不能移除。
不变量：发现不完整不能自动缩小正常移除安全范围。
建议：功能事实范围与移除安全范围两层；owned要求实例级充分停止证据/ScopeObligation，borrowed只解除本方。两轮重大仍在，应立即用户讨论。

**B2-5 / high / V2 / opaque安全指纹与开放性 / V2-7,10 / 延续C1-4**
前置：未知合法命令可透传，无法判秘密，无稳定keyed port。
序列：durable要求完整digest但只存元数据→同key正文变而元数据不变；裸hash不安全；全部拒则开放性承诺受限。
危险：实际准入缺确定规则，安全摘要≠完整指纹。
不变量：输入不裁剪、不假相等、不无条件宣称入口完全可达。
建议：与命令无关的protected port对完整输入指纹；缺则明确保障组合拒绝，列为runtime前提，不搞命令白名单。两轮重大仍在。

**B2-6 / high / V2 / 异步等待图 / V2-4 / 延续A1-4**
前置：A/B各inflight1，async receipt，后续等待子结果。
序列：X持A→Y持B→X等Y→Y异步请求A上的Z→Z等A→Y等Z，callback都及时返回。
危险：async没消除等待；全序只覆盖同步声明，缺等待边登记。
不变量：实际wait而非函数形式决定死锁。
建议：定义await/capacity wait注册，保留slot时仍检查held→requested；或明确只能防框架死锁，不承诺插件内部wait。不能以async结案一般图保证。

**C2-1 / high / V2 / 晚到对象收尾 / V2-1,2,7**
前置：create A接受/已发，输出identity未知。
序列：accepted A→drain→原生返回O→活义务登记→destroy O因drain前不存在被拒。
危险：合法结果不能收尾，提前枚举透明命令结果又网关化。
不变量：按新业务意图截断，已接受意图结果可收尾。
建议：drain admission cut与既存活动集合；可验证属于这些活动的晚对象继承closure，不继承新业务授权；关联不足unknown。

**C2-2 / high / V2 / 原生停止交互链 / V2-2,11 / 延续A1-5,B1-6**
前置：旧O stop需要保存/放弃，responder断线。
序列：drain→stop closure→new Q→new Hold→同一用户重新attach不在允许表→不能reply→stop永久待。
危险：不能核心认“保存”；全部reply开放又能新任务。
不变量：授权收尾链持续，显式恢复角色不等自动迁移权。
建议：closure责任链而非旧Ref清单，新Q/H与同target/角色显式attach需adapter证据；未知关联拒绝。重大同类矛盾两轮未闭合。

**C2-3 / high / V2 / 跨插件closure依赖 / V2-1,2,4**
前置：A job J借B资源R，stop需要B只读参数，依赖pin已登记。
序列：A/B drain→B保pin→A stop→B/R新query既不是closure列表又非A owner→拒绝→A无法停，B无法释放。
危险：保代码不等必要调用可达，全部read放开又能继续新任务。
不变量：既存授权依赖可收尾，但不新增资源/业务/权利。
建议：不可伪造ClosureContext含根义务/cut/允许依赖/缩限grant/预算；必要query短pin，只限旧target；borrowed detach等收尾依赖完。

**C2-4 / high / V2 / 无Store静态资源移除 / V2-1,2,7**
前置：无Store catalog，不可变owned版本对象O，正文既有文件，无usage/pin/任务。
序列：read结束→drain活O阻塞→无本方projection-retire入口→destroy要Store/可能删正文→拒绝，普通catalog无法移除。
危险：静态内容与运行责任一刀切；被迫上Store/删资产/脱管。
不变量：保留静态内容不等活执行义务；本地关系退役与外部删除分离。
建议：退出契约stop执行/解除代理/保留资产并终结projection/显式销毁资产；memory本方关系退役不算external destroy，external delete仍durable。

**C2-5 / high / V2 / opaque退役门 / V2-1,9 / 延续C1-1**
前置：owned实例opaque，managed_scope内有未枚举work。
序列：新命令→已知S停→已知账resolved→retire成功但只不声称all-stopped。
危险：不报全停仍能绕D2；全部opaque永久pin又把scope外borrowed工作吞入核心。
不变量：托管范围内证明缺口阻正常移除，范围外只披露。
建议：显式ScopeObligation；coverage不足unresolved，原生全scope证据可解无需逐对象枚举，脱管另授权。

**C2-6 / medium / V2 / decoder生命周期 / V2-12,2,6**
前置：执行adapter已卸，decoder v2读v1附件。
序列：选decoder→未解码完drain/卸或升v3→旧读取继续/静默换实现。
危险：私有reader平行加载/不兼容解码，不是只读就安全。
不变量：固定compatible codec/digest、短pin；无decoder不影响最低事实，不给控制权。
建议：decoder普通只读Surface/contribution复用同环境，声明codec/version；缺兼容返回unavailable。

## 第一轮逐项复查（代理结论，不是主会话替改）

| 复查者 | closed-in-design（原反例已被V2规则禁止） | still-open / 本轮延续 |
| --- | --- | --- |
| A | A1-3、A1-6、B1-1、B1-3、B1-4、B1-7、B1-8 | C1-4→A2-2/B2-5 |
| B | A1-7、B1-2、C1-2、C1-6、C1-7 | A1-4→B2-6；C1-1→B2-4 |
| C | A1-1、A1-2、B1-5、C1-3、C1-5、C1-8 | A1-5/B1-6→C2-1/2/3；scope→C2-5 |

## 立即升级讨论的三项

主会话在收到第二轮结果后立即问用户：允许已有工作的必要收尾链；owned原生工作未枚举时需充分范围停止证明否则正常移除待完成；通用protected fingerprint作为未知输入效果性发送的安全前提。不是反复询问已选D1/D2，也没有无限代理循环。
此外等待图登记、创建结果原子交接、回执查询、证据epoch、一次Q应答消费、静态资源退役和decoder生命周期属于技术修复，由主会话推进。

## V3逐项处置

以下为修订目标，用户相关分支等答复后纳入V3，不将提案当批准。

| ID | 处置 | V3定位 / 场景 |
| --- | --- | --- |
| A2-1 | 接受，结果/对象/义务原子交接，ScopeObligation连续 | V3-1；S11/S17/X02 |
| A2-2 | 接受，未知输入完整protected fingerprint；缺席准入规则待D6 | V3-2；S05/S10/X03 |
| A2-3 | 接受，持久BindingSnapshot和principal/key只读lookup | V3-3；S10/S19/X04 |
| A2-4 | 接受，native/source/current三个revision轴，核对不跨observer比较本地seq | V3-4；S12/S13/X05 |
| A2-5 | 接受，replay先查历史read权，new admission才消费Hold | V3-5；S10/X06 |
| B2-1 | 接受，Q response slot跨key唯一，占位与intent同事务 | V3-5；S08/X06 |
| B2-2 | 接受，按既存责任因果链判closure；等待D4 | V3-6；S08/S17/X07 |
| B2-3 | 接受，unknown role产生交互完整性义务，不自行解释审批 | V3-7；S07/S08/X08 |
| B2-4 | 接受，功能托管scope与移除安全scope分轴；等待D5 | V3-8；S05/S17/X09 |
| B2-5 | 接受，同A2-2，明确可达性保障前提；等待D6 | V3-2；S05/X03 |
| B2-6 | 接受，环境await/capacity显式登记，任何持slot等待查图；原生/偷偷等待不假保 | V3-9；S16/X10 |
| C2-1 | 接受，admission cut接受因果后继，不继承新业务权 | V3-6；S17/X07 |
| C2-2 | 接受，限定根义务/角色的显式responder重新attach；等待D4 | V3-6；S08/X07 |
| C2-3 | 接受，既存依赖收尾Context+缩限grant/预算；等待D4 | V3-6；S16/X07 |
| C2-4 | 接受，静态保留资产关系退役≠外部destroy，退出契约预声明 | V3-10；S01/S09/X11 |
| C2-5 | 接受，scope未知直接阻正常退役不是改报告措辞；等待D5 | V3-8；S17/X09 |
| C2-6 | 接受，历史decoder同环境只读贡献/版本/短pin | V3-11；S19/X12 |

最终独立复查必须针对完整V3与实施计划，对这17项及5个延续第一轮问题分别给判定；未复查前不报已关闭。

## 编号勘误（最终独立复查）

最初复查派发消息使用D3/D4/D5指三项本轮政策，与B1原D3数据迁移冲突。当前所有正式合同统一：D3仍为实施前数据迁移；D4收尾链、D5范围停止证据、D6受保护指纹。保留此勘误，不重新解释历史批准。

独立复核回执：C重新读取修正段，确认F1 closed-in-document；第二轮9 closed-in-design/8 conditional-on-ruling不变。条件映射A2-2/B2-5→D6，B2-2/C2-1/2/3→D4，B2-4/C2-5→D5；第一轮延续同映射。该回执只验证文档修正，不是实现测试。
