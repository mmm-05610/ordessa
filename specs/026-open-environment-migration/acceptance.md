# L5 验收矩阵

S=源码/结构；I=真实受控实现（包含SQLite/IPC/native fixture，不是真实模型）；U=实际Electron UI；P=获授权真实原生/模型。有限参考模型只辅助，不满足I/U/P。每项必需正例及反例；无资源不跳成绿。

| ID | 工单 | 范围 | 成功条件 | 必须抓住的反例 | 层次 | 缺席处理 |
| --- | --- | --- | --- | --- | --- | --- |
| A01 | 001 | 源码快照完整 | P未提交history/picker修复在批准快照；digest可重算 | 只用HEAD漏一文件→拒ready | S | 来源/授权缺席BLOCKED |
| A02 | 001 | 凭据隔离 | manifest无密钥正文/用户数据库/node_modules | 源码清单混key.txt→检查失败 | S | 扫描规则未跑FAIL |
| A03 | 002 | DTO和wire | Python/TS同contract版本编码互通 | 缺owner实例/不合法mask/版本不兼容→typed拒 | I | 构建产物缺席FAIL |
| A04 | 002 | Token唯一 | 真实分包build/import-map中同Token identity | 故意bundle第二Token→运行identity门失败 | I | 只typecheck不通过 |
| A05 | 003 | 空环境 | 不装Server/Harness/Profile/SQLite仍query起停 | 核心反向import/无Store可靠invoke→拒 | I | wheel隔离证据缺席FAIL |
| A06 | 003 | 对象引用 | 完整owner实例/代次/type匹配可读 | 两个owner同nativeId/g1不能跨invoke | I | 历史只有locator不可控 |
| A07 | 003 | 安装启用分离 | 空override激活0；installed不默认enable | 发现所有installed就activate→失败 | I | 显式清单缺席拒默认推导 |
| A08 | 004 | 原子激活 | A+B依赖发布同revision，正常consumer可见 | B失败后A半服务不可调用 | I | transaction证据缺席FAIL |
| A09 | 004 | 停用准入竞态 | cut前accepted责任可收尾，cut后新请求拒 | 新request冒closure/late open漏义务→拒 | I | scope未知retire pending |
| A10 | 004 | 代次与退出 | 旧dispose不撤新贡献，existing reply限原授权 | 旧slot回答/新任务冒停止确认→拒 | I | 原授权证据缺席拒effects |
| A11 | 004 | 自有与共享 | owned整个声明范围退出；borrowed仅release | 会话空但子进程活/borrowed被kill→失败 | I | 充分证据缺席pending |
| A12 | 004 | 资源与等待 | static移关系内容byte相等；双插件可收尾 | async wait实际成环/删除用户asset→拒 | I | 资源访问未知FAIL |
| A13 | 005 | 持久意图 | Store成功后才native send | commit失败仍外调/读坏库memoryfallback→拒 | I | 可靠Store缺席发前拒 |
| A14 | 005 | 五崩溃窗口 | 真子进程kill后query固定原ID，unknown不重发 | accept后crash重新send/new attempt→失败 | I | 没杀进程仅模型不通过 |
| A15 | 005 | 并发占位 | 同ID同payload一占位，同slot一次回答 | 同ID不同payload/跨key抢slot→拒 | I | 并发/事务证据缺席FAIL |
| A16 | 005 | WAL与两根 | 未checkpoint数据可见，两个Environment根隔离 | copy.db忽略WAL/跨根globaldb→失败 | I | backup未知不写真实根 |
| A17 | 005 | MAC与轮换 | 完整输入字段/附件/配置/目标指纹，key_ref无明文 | 裸低熵hash/裁剪未知命令/缺旧key自动重发→拒 | I | 可靠缺key拒；raw不受该项禁用 |
| A18 | 006 | 单根多入口 | local/CLI/HTTP/WS/compat同identity和结果 | CoreBinding创建第二Runtime/旧sidecar主写→失败 | I | 入口未实现typed unavailable |
| A19 | 006 | 网络身份 | 原auth/origin签名与错误族保持 | 坏token/origin/method动态签名扩大→拒 | I | auth证据缺席FAIL |
| A20 | 006 | 切换与回退 | 新请求单writer；已unknown有继续者 | 新effects后旧版本重放/双写比较→失败 | I | 兼容回退未证只读模式 |
| A21 | 007 | 原生新能力 | controlled/workflow和未知event原样有界到达 | Core品牌白名单/unknown当审批→失败 | I | 原生通道缺席unsupported |
| A22 | 007 | 会话身份 | 多Activity同native session，choose不session/new | channelID冒session、unknown创建再new→拒 | I | 关联缺席不可claim |
| A23 | 007 | 历史decoder | 卸载执行插件中性历史/unknown仍可读 | 旧Ref因路径同自动恢复控制权→拒 | I | 正文缺decoder明示部分可读 |
| A24 | 007 | 资源独立 | resource-only product不启用Profile/Harness可list/use | 静态list必须ExecutionPlan/Agent注入→失败 | I | cap缺席明确 |
| A25 | 008 | 路径与打包 | frontend/workbench/backend包在真实产物被消费 | 旧路径test消失或deb仍旧引用→失败 | I | 发现表缺席FAIL |
| A26 | 008 | 设置与浮层 | 单Workbench导航/overlay，关闭/Esc/焦点正确 | 宿主第二settings数组/菜单被overflow裁→失败 | U | 无GUI资源BLOCKED |
| A27 | 009 | 原生句柄 | 有效caller/lease在执行commit时可用 | 跨await撤销/伪lease/过期gen→拒 | I | 无broker校验不得宣安全 |
| A28 | 009 | 隔离信任 | trusted内建正常；第三方不进入main直接import | 恶意third-party顶层module/CSP全放开→拒 | I | 无隔离拒第三方，不吞可信内建 |
| A29 | 009 | 流与预算 | raw/decoded/queued每跳有界；gap有快照恢复 | 高频输出只留尾部假完整/关键事实默丢→失败 | I | native不支持恢复标incomplete |
| A30 | 009 | 输入操作 | 中文IME和英文正常，尾Enter不send；Esc一层 | composition尾事件发送/旧inputticket新target→拒 | U | DOM模拟不等真实IME |
| A31 | 009 | 外部非Chat插件 | 独立terminal/document扩展不依赖Agent/Chat/Profile | 绑定强制AgentKey/引用app内部→失败 | I | 独立build产物缺席FAIL |
| A32 | 010 | 字段覆盖 | Profile→model与model→Profile；无model保留；unset显式 | Profile全部覆盖空字段/同值no-op→失败 | I | schema解析缺席unsupported |
| A33 | 010 | 唯一状态 | 多控件/窗口同owner，旧glue/client仅codec | schema/major/窗口另开writer→拒 | I | 唯一性未证FAIL |
| A34 | 010 | 异步顺序 | 点击seq先定，迟resolver不覆盖后操作 | 按resolve时间排序/目录变化修改捕获→失败 | I | resolver错误操作拒 |
| A35 | 010 | 证据冲突 | r12/r11补链；新全快照清旧buffer | 同revision冲突重复旧观察解锁/缓冲再stale→拒 | I | base不完整阻可靠capture |
| A36 | 010 | 草稿与目标 | view close保稿，晚回执按revision消费 | 同文本ABA清新稿/selected把旧提交重路由→失败 | I | draft恢复能力缺席不承诺 |
| A37 | 010 | 无Profile | 不启Profile两轮聊天/model选，source稳定 | Profile identity/serializer硬依赖→失败 | I | 缺模型provider单独不可用 |
| A38 | 011 | 可靠与raw | 显式模式各自能力；可靠失败不raw降级 | 缺MAC禁所有raw/可靠失败偷发→失败 | I | 可靠缺保证unsupported；raw不冒可靠 |
| A39 | 011 | 配置与输入结果 | model applied+prompt rejected逐项显示保稿 | 整体假回滚/accepted显示运行成功→失败 | I | 结果未知保关联 |
| A40 | 011 | 首次发送 | 可靠create-config-input身份关联；选项不建session | unknown创建二次new/伪空revision CAS→失败 | I | 原生无原子能力unsupported |
| A41 | 011 | 输出不打断 | 输出间改配置，下次输入用捕获意图 | 选择触发stop/native内部工作流重实现→失败 | I | 不能测不称已保持 |
| A42 | 011 | 重启与闪烁 | 列表读历史、click resume；每键不闪send error | 重启清unknown/输入派发apply/send→失败 | U | 未操作桌面BLOCKED |
| A43 | 011 | 三品牌真实链 | Pi/Codex/Claude各首轮/第二轮/切换/历史续聊 | controlled结果冒真实、native内部问题上层吞掉→失败 | P | 无资产/凭据/授权BLOCKED |
| A44 | 011 | 认证与会话隔离 | Codex官方单账号与另一API实例并存，配置独立；Pi/Claude各provider原生支持 | 全局home覆写/密钥进renderer日志→失败 | P | 不支持模型/provider组合typed拒 |
| A45 | 012 | 干净发布构建 | fresh npm ci/wheels/deb解包在隔离环境起停 | editable隐藏漏依赖/装配锁错误/无测试发现→失败 | I | 工具缺席BLOCKED |
| A46 | 012 | 数据升级演练 | 旧/空/损坏/WAL/symlink fixture，保旧ID与原Receipt | 初始化旧库为空/复活legacy dispatch→失败 | I | 真实写无授权BLOCKED不执行 |
| A47 | 012 | 退役守卫 | 旧运行实现0，允许facade唯一新实现，文档对应实际 | 仅名字改但原registry还可调用→失败 | S/I | 静态扫描不足需运行反例 |
| A48 | 012 | 范围与交付 | 无秘密/binary/用户data入git，完整证据与未验清单 | 凭据ZIP误stage、未跑标DONE→失败 | S | 证据缺席FAIL |

| A49 | 011 | 跨库恢复握手 | 领域mapping/marker/backend intent/config apply/native accept/result各窗真kill可查原ID | 零派发marker写失败仍unknown；部分apply不能退ready重复apply | I | 缺映射拒补新请求 |
| A50 | 005 | 同根writer排他 | 两真实进程同根只一writer，暂停旧writer再恢复不增加send | 靠lease超时抢旧claim/旧进程复活重派→拒 | I | 无法证明旧writer失效拒effects |
| A51 | 011 | 跨模式请求一致性 | 可靠unknown+旧key缺失→raw同K只查/拒，新K显式raw可用 | guarantee/generation/transport变成新namespace→失败 | I | comparison缺席拒同K，不禁新raw |
| A52 | 011 | 附件内容冻结 | 指纹后替换文件/symlink/对象、同inode改写/截断只发原字节或发前拒 | MAC A/native B；仅保句柄冒不可变→失败 | I | 不能冻结内容拒可靠保证 |
| A53 | 001 | 快照并发与链接 | 清点前后/导入前后摘要及type/mode/link匹配批准manifest | 源码编辑/新增删除/untracked/regular变越界symlink→拒 | S/I | 源漂移重提差异不偷偷导入 |
| A54 | 005 | 密钥墓碑与历史 | 轮换/旧key撤销/正文过期/decoder卸载仍保spent；有history-read权中性事实可读，无权拒泄露 | 删墓碑重派/旧key缺席把known退unknown/拒读当不存在→失败 | I | payload/比较不可用不等原请求不存在 |
| A55 | 010 | native别名唯一 | 同owner/nativeId/gen的两连接附同可写authority，未知映射只读 | socket换名logicalKey绕unknown→拒 | I | native身份不足unverified |
| A56 | 007 | 未知role责任 | 未知delivery_role有scope义务，旧idle不能解除 | raw显示后丢scope/溢出丢义务→失败 | I | 分类不足retire pending |
| A57 | 008 | 前端原子preflight | preflight同门冻结dispatch/required borrow/batch publish，拒超时恢复 | 跨await晚dispatch/晚依赖publish撤必需owner→拒 | I | 无fence不能停必需owner |
| A58 | 007 | 三序号恢复 | native/source revision独立ingest/knowledge，RecoveryBinding可信 | 新observer低seq/not found、PID复用解除unknown→拒 | I | 证据不可比disputed/unknown |
| A59 | 010 | connector状态退役 | Session/Run/Interaction/Submission都owner决定资格 | client重建清pending/晚success解锁owner unknown→拒 | I | 未迁剩余字段不算唯一状态 |
| A60 | 009 | SDK端到端未知事件 | 同payload摘要native→Harness→Server→真实connector/SDK→surface显示 | 后端保raw但SDKKNOWN_SESSION_UPDATES过滤丢→失败 | I | 出口缺席不宣能力完整可达 |
| A61 | 009 | 三个外部包 | 第四种Agent、static独立wheel、nonChat扩展各公共合同构建/安装/退出 | 只内部fixture/三品牌resolver限制/资源需Server私有→失败 | I | 外部产物缺席FAIL |
| A62 | 005 | Store提取检查点 | 旧CoreStore消费者在005同步移公开工厂，Server受控回归绿 | 删public构造但006前旧Server import红→失败 | I | 不能宣005 ready等006救 |
| A63 | 012 | 分级依赖 | 仅S/I codeReady支持后续代码，U/P待验保持BLOCKED且finalDone false | U/P待验冒DONE或阻所有独立打包→失败 | S | 缺required codeReceipt不可推进 |
| A64 | 012 | 发行默认闭包 | 解包产物所有required wheel/entrypoint/依赖+默认/无Profile两轮controlled | missing目录skip但计划installed全；repo editable补漏→失败 | I | 任一required缺席FAIL |
| A65 | 012 | 独立suite发现 | Python collect/Go/ACP独立lock/external install全部对账与真跑 | 迁后空collect或漏Go/干净安装仍绿→失败 | I | 未知发现FAIL；继承红逐ID保留 |
| A66 | 003 | 单核心与语义中立 | 异协议插件经同Environment公共路径发现/绑定/调用/退出，核心无业务依赖 | 另建关系账/Server复制目录/新增品牌需改核心→失败 | I | 公共路径或提供者缺席FAIL |
| A67 | 002 | 绑定与能力缺席合同 | 候选显式选，required缺席拒相关入口，optional缺席其他可用；DTO/codec可编译 | discover后换provider/裸对象通道/旧写权继承新代次→拒 | I | 身份/access未知拒绑定，不冒可用 |
| A68 | 004 | 独占领域owner | 同canonical目标仅一writer，快照不可变 | 新schema/major/alias开第二writer或返回可变内部对象→失败 | I | 实体区分证据不足拒竞争写入 |
| A69 | 004 | 作用域与在途责任 | 关闭UI释放观察，已接纳Activity保必要Usage；消费者卸载不取消工作 | 菜单关闭删在途工作/provider无证据退出→失败 | I | scope未知拒新操作，旧责任保留 |
| A70 | 004 | 准入竞态与依赖环 | bind/invoke/subscribe与drain同门，required环拒，运行等待有预算 | preflight后插新绑定/持锁等provider/递归死锁→失败 | I | 门或环检查缺席FAIL |
| A71 | 009 | 无缝订阅及晚到句柄 | 快照与后继事件连续，建立中撤销晚句柄可释放/登记责任 | read后subscribe漏更新/late attach泄漏→失败 | I | 无连续性证明拒同步保证 |
| A72 | 008 | 背压与重新同步 | gap显式，重取owner快照清旧patch，旧回调不改新scope | 静默丢事件仍同步/旧buffer覆盖新快照→失败 | I | 回放缺席标resync-required，不假同步 |
| A73 | 004 | 释放与提供者代次 | release幂等，旧绑定不可写新provider，未明释放保责任 | 同ID暗中换实例/本地删map当退出→失败 | I | 释放证据未知保持pending |
| A74 | 010 | 多配置入口单owner | Profile/model订阅同状态，字段覆盖正确，资源业务独立 | 双currentConfig/核心解释model patch/Profile变必需→失败 | I | 原生未确认不伪成功 |
| A75 | 012 | 前后端不双权威 | 后端owner前端仅代理，纯前端owner独立；断线detach查原request | 镜像可独立写/重连清unknown或自动重发→失败 | I | 无绑定/恢复证据拒写，读取另核权限 |
| A76 | 005 | 数据空间隔离 | 稳定namespace仅本owner访问，插件卸载数据保留 | A选择B空间/源码移动换数据根/卸载purge→拒 | I | 无持久实现拒所需保证 |
| A77 | 005 | 数据迁移边界 | 授权排他/备份与版本声明，旧二进制拒写新schema | 构造时静默迁移/失败自动覆盖/旧writer仍写→失败 | I | 无许可/证据BLOCKED写 |
| A78 | 005 | 存储可选与CAS | 文件/SQLite声明保证，纯内存资源无SQLite可运行 | read+rename伪跨进程CAS/所有资源强依赖SQLite→失败 | I | CAS机制缺席拒强保证 |
| A79 | 004 | 持久关联存续 | 资源停用后引用仍可读，新引用域不改核心 | 停Profile擦引用/核心扫描providerId→失败 | I | 覆盖未知不报无引用 |
| A80 | 004 | 引用变更竞态 | reference publish与change reservation同门兼容核验 | query无引用后并发archive和引用都成功→失败 | I | 无强保证边界拒破坏性保证 |
| A81 | 005 | 跨库引用恢复 | 源写成功确认丢失/崩溃保持潜在关联，只查原ID | unknown撤reservation/TTL自动解锁/重做删除→失败 | I | 原提交证据未知保持相关gate |
| A82 | 007 | 引用覆盖与业务策略 | 导出源版本证明coverage，归档语义目标owner给出 | 缺扫描者当空/核心统一archive=destroy→失败 | I | coverage/contract未知拒对应变更 |
| A83 | 009 | 宿主交互生命周期 | 取消零写，late结果失效可清理，来源可见 | 卸载后选择返回仍注册项目/遮窗口控制→失败 | I | picker缺席unavailable不造结果 |
| A84 | 009 | 选择不等授权 | 选择路径后领域另核访问，普通确认不等native审批 | confirm提升权限/选择路径授所有Agent→拒 | I | 缺访问能力拒后续effects |
| A85 | 005 | 秘密访问范围 | 可信侧purpose/代次借用，renderer只opaque ref | 裸locator即权/前端取明文/旧绑定写新实例→拒 | I | access未知拒取秘密 |
| A86 | 005 | 秘密缺席与锁定 | locked拒秘密路径，无秘密功能继续 | 锁定回退明文文件/全局env/fixture默认→失败 | I | unknown保持不可用不重导入 |
| A87 | 005 | 秘密轮换删除责任 | 版本/持久引用/在途borrow检查，spent墓碑不丢 | 删key让旧请求变新/撤访问声称撤原生已交付秘密→失败 | I | 删除结果未知只核对原ID |
| A88 | 009 | 诊断无副作用 | scope注入有界脱敏只读，结果权威不变 | collect发probe/login/apply/日志替执行账→失败 | I | 片段unknown不伪healthy |
| A89 | 008 | 逻辑元数据不调度 | logical目录与旧入口/锁一致，runtime各仅一次激活 | parent manifest二次resolve/另设enable权威→失败 | I | 元数据/入口不一致FAIL |
| A90 | 012 | 按需入口 | backend-only资源、frontend-only可用部分，无Profile/Chat组合安装运行 | 逻辑插件强制全入口/资源管理硬依赖Chat→失败 | I | optional缺席撤附加能力，required闭包缺失FAIL |
| A91 | 007 | 品牌适配所有者 | 资源合同中性，所有现品牌适配保在Harness | resource插件新增品牌条件/丢非三品牌资产→失败 | I | 未实现支持明确unsupported |
| A92 | 002 | 公开契约身份 | 纯公开contract编译互通，旧发行与ID映射明确 | 导入其他插件私有store/新Token副本/重命名持久ID→失败 | I | 身份/兼容映射缺席FAIL |
| A93 | 010 | Agent能力读写分离 | 多控件同owner，只有绑定Harness来源能报确认 | 普通插件setConfirmed/前后端双pending主写→拒 | I | 来源未知不更新确认 |
| A94 | 008 | 命令权威与原生输入 | 平台注册执行一个服务，handler属业务，native slash原样到native | 旧commands另建服务/平台截workflow→失败 | I | 缺native通道明确不可用不转平台 |
| A95 | 012 | compat与实际产物 | 旧ID薄forward同实现，领域移动后独立产物完整；compat-retirement中C95-1–7全部成立 | 仅换legacy目录保双核心/repo editable补漏、残留业务owner、删测试求绿→失败 | I | required实现或退役台账/子断言证据缺席FAIL |

## 实测命令与发现

实施前001核实源；以下是现仓已声明入口，不能沿用文档旧计数：

```sh
npm test -- --list
npm run typecheck
npm run build
npm test
npm run test:agent-shell
npm run test:electron
npm run build:deb
```

Python使用获批源锁与隔离venv，每个迁后pyproject editable安装，再分别运行迁后pacthold/server/harness及所有改变的plugin套件。suite由测试发现清单记录，不凭本文虚构新的script名字。新contracts/surface/API packages必须接入root runner与独立测试，不只跑开发者目录。

Deb构建允许在实施授权内生成本地未签名产物，不安装/publish；clean-machine acceptance是否执行由系统操作范围另确认。GUI使用隔离temporary userData、fixture端口；不切用户运行窗口。真实P操作必须用户批准scope/cost，秘密不进日志和参数。

## 测试迁移对账

测试搬路径会改变pytest/vitest ID，应建立old→new case identity映射与断言来源。失败按逻辑case+cause比较，不能简单允许旧失败数量不变。移除真正已退役目标的测试需逐条记录原因、替代覆盖和批准，不删assert/skip求绿。新增失败不得归入旧红。

## 证据格式

每个Axx的文件至少含：sourceCompositeSHA、contractVersion、caseId、mode、command/cwd/toolchain、exit、assertions、counterexample结果、fixture/capture标识、cleanup结果与缺口。GUI附当前产物SHA和操作截图；P附脱敏native回执/消息相关性、明确测试成本及授权范围。证据不可携token/输入秘密/MAC key。

目录evidence/先只放设计校验和审查；实施日志后续新增。没有真实用户数据升级许可时交付“代码和fixture迁移完成，用户数据未迁移”；不能宣称安装升级已通过。完整DONE须A01–A95必需层次证据齐，真实目标不支持保证可明确拒绝并满足A38/A40，不假作已有保证。E3/F3分配到各工单的验收纳入该单codeReady所需S/I证据，不延至012才首次实现。

## R7 / M14 前端基础设施（全部必需）

| ID | 工单 | 范围 | 成功条件 | 必须抓住的反例 | 层次 | 缺席处理 |
| --- | --- | --- | --- | --- | --- | --- |
| A96 | 008 | 状态写权与快照 | owner更新后两个消费者读同快照，未变化引用稳定 | 消费者改嵌套值或用setState写领域事实被拒 | I | 无真实状态容器FAIL |
| A97 | 008 | 字段选择与批量通知 | 无关字段零通知，批量只见完整快照，重入有界 | 全局revision使输入每键重置或中间半状态泄露 | I | 无真实消费者/通知证据FAIL |
| A98 | 008 | 订阅和React生命周期 | 组件卸载释放订阅，旧dispose不撤新owner | 旧scope回调修改新目标或每次render重复订阅 | I | 无React构建/挂载证据FAIL |
| A99 | 008 | 授权投影连续性 | 同E3观察，gap重同步，撤权后停止访问投递 | 缺事件仍标同步或缓存跨授权/连接共享 | I | 无连续性能力标resync-required；保证验收不通过 |
| A100 | 008 | 普通查询缓存 | 同key共享read、分页失效有界，代次隔离 | 非幂等效果冒query自动重试或撤权仍读缓存 | I | 查询adapter缺席明确unavailable并FAIL |
| A101 | 008 | 异步等待与晚到结果 | A晚到不覆盖B，关页只释放等待不销毁已接纳工作 | cancel直接当后端已停止或unknown自动重发 | I | 取消能力缺席仅cancel-wait；不能宣称停止 |
| A102 | 008 | 通用编辑及设置 | 独立非Chat编辑消费mask/CAS，dirty更新保本地 | 迟到保存清新编辑、业务校验移核心或秘密入通用store | I | 编辑owner/条件写缺席拒save，保草稿 |
| A103 | 008 | UI存储与恢复 | fixture跨重启恢复安全UI项，namespace/版本隔离 | 未知schema覆盖、关闭scope删偏好或存API Key | I | 无适配session-only；持久验收不通过 |
| A104 | 010 | 配置控件公共消费 | 多个控件显示同owner，Profile/model覆盖按原语义 | 控件独立current/pending写权或Profile隐式必需 | I | 域owner缺席明确不可用，不走私有旧链 |
| A105 | 010 | 草稿和设置编辑接线 | 真实消费者dirty冲突/ABA/迟到结果保新稿 | 两份DraftOwner或保存成功无条件清表单 | I | 消费者缺席FAIL，不用工具单测替代 |
| A106 | 010 | 公共任务交互接线 | 资源页无Chat/Profile依赖，任务错误更新同通知 | 每次输入新红提示、取消伪报停止、资源页导私有serializer | I | 接口/独立构建缺席FAIL |
| A107 | 012 | 发行闭包 | 解包产物独立插件读取F5及React入口，fixture恢复安全UI项 | editable源码补包、React污染中性入口或旧双store兜底 | I | 缺required依赖FAIL，不skip |
| A108 | 012 | 输入和公共交互 | 实际窗口中文/英文输入无无关重写，菜单Esc和进度焦点正确 | 模型切换后输入闪烁、尾Enter误发或重复通知 | U | 无GUI/实际IME证据待验，不报fullDone |
| A109 | 008 | 上下文及显示机制 | 按钮/菜单/快捷键同源，翻译/图标缺失明确回退 | when授予权限或持另一份业务状态，缺label键盘不可达 | I | 上下文/回退/组件证据缺席FAIL |
| A110 | 012 | 多窗口存储隔离 | 受控双窗口共享项条件写或唯一owner，本地项独立 | 模块单例冒跨进程共享或旧窗口结果覆盖新目标 | I | 无协调拒共享写保证；必需验收未完成 |
| A111 | 012 | 重启后的界面恢复 | 实际Electron重启恢复布局/展开与安全偏好，插件缺席可降级 | 恢复自动启停业务、触发模型或失效引用致空白崩溃 | U | 无GUI/存储适配待验，不报fullDone |
