# 场景、反例与验证层次

版本：需求场景集 S1，模型修订时补映射。覆盖 README 的 20 组；每项都必须验证缺席/反例。
验证标签：P=纸面事件推演；O=本目录规范参考检查；I=未来真实实现的受控集成测试；R=真实资产/模型/产品体验，需另授权。本轮最多做 P/O，不将其报告为 I/R。

## 必须覆盖的 20 组

| ID / README组 | 前置与事件序列 | 期望结果与反例拒绝 | 可执行离线/未来验收条件 |
| --- | --- | --- | --- |
| S01 / 1 | 显式空 product；无 Harness/Profile/store；加载依赖缺失插件 | 本地内存环境可建；该插件拒绝整组发布；空环境没有凭空品牌/业务表 | O dependency graph；I 空安装核心 wheel、本地 invoke 受控 query，确认无业务 import/DB，必需依赖缺失零发布 |
| S02 / 2 | 同插件 I1/I2，I1异常退出，I2仍有活动 | I1 unreachable；I2仍可工作；不能按 plugin_id 将两者一并 cancel | O generation/local state；I 两个 controlled instance，退出I1后调用I2一次且有效 |
| S03 / 3 | create(S)活动成功；订阅C断开 | create成功，S继续；detach只改subscription | O object/usage sequence；I 断HTTP/CLI客户端后从第二入口读S，owner未获stop调用 |
| S04 / 4 | 原生会话S，send1/send2，内部工具/压缩/workflow事件 | 同S关联多个入口活动；内核不建立内部Agent轮次状态机 | P 五类接入表；I fake native protocol 多轮，统计Core仅有入口活动，没有工具调度/原生审批规则 |
| S05 / 5 | 同adapter版本；上游在已承载命令入口新增 /workflow | 核心不变、请求完整到原生，native审批不丢；接口只承诺可达，不能承诺功能成功 | O opaque trace；I fake peer增加命令，固定核心/adapter摘要，收帧等值并拒绝未授权入口 |
| S06 / 6 | 新功能只有未承载native UI | adapter_gap明确；支持清单不得available；保留其他原生入口 | O reachability declaration；I 同样peer/UI-only feature，API返回明确gap，禁止假绿色 |
| S07 / 7 | unknown output、unknown需要应答事件、伪terminal payload | 保留有权限可显示内容/安全元数据，opaque业务不升级终态或批准；不能自动同意 | O unknown event handling；I renderer安全、未知callback可递交owner适配处理/明确未支持，HTML不会执行 |
| S08 / 8 | 慢订阅/断连、seq晚到/重复、无限流、控制帧夹在大量日志 | 有界队列/字节/订阅/inflight；显式gap；控制语义不能被静默丢掉；脱订阅不kill producer | O bounded stream trace；I real async fake peer saturate quotas，验证RAM上限、control错序/丢失拒绝及cursor恢复/无resume降级 |
| S09 / 9 | memory只读query；用户query活动；内部账本read；无Store/Lease | query统一admission和短活动，零DB/lease；内部记账不是无限子活动；请求durable却无Store拒绝 | O query cost counters；I 孤立环境真实spy store/acquire均0，metadata缺失不得默认副作用query |
| S10 / 10 | 并发重复 key/input；相同key换输入或绑定；超TTL | 同digest单次dispatch并重回执，异digest拒绝；过期不能静默当新effect重发 | O dedupe trace；I 双线程真实Store，重启重放；同key变principal/scope的规则显式 |
| S11 / 11 | 分别 crash@intent_before/after、send_before/after、receipt_before/result_after | intent前不得调用；发出结果丢失unknown；有durable结果重放；不凭planned猜未发 | O crash matrix；I 子进程+临时SQLite+独立受控effect计数，每窗口kill、重启，证明调用计数和记录一致 |
| S12 / 12 | cancel_requested；完成与cancel确认乱序/并发；deadline到 | 请求/效果/超时三事实分离；终态按owner证据顺序，冲突可见；不能先到弱cancel覆盖真实success | O terminal evidence trace；I fake provider序号与并发 callback，恶意/晚到控制不改已有可信终态 |
| S13 / 13 | 重启，实例代际变更，query unsupported；旧operation存在 | 只证据核对；无支持保持unknown并pin；不spawn/login/reissue；新实例不冒认 | O restart trace；I provider副作用计数0，旧句柄拒绝当前控制，受控恢复证明正反例 |
| S14 / 14 | shared object、U1/U2 Lease；release U1 | U2权利保留，对象不destroy；destroy须独立权利与无阻塞/明确许可 | O share sequence；I release/destroy/use并发，用户1不能中止用户2；借用对象销毁拒绝 |
| S15 / 15 | owner离线、使用者消失、usage过期、旧Ref与跨E/instance | usage到期不证明对象结束；stale/foreign拒绝；丢owner保留unknown；不能错控新的同名实例 | O scope/generation/ref checks；I 请求前后ownership变动（含refused callback分支），结果不得升级当前归属 |
| S16 / 16 | parent→childA成功/childB失败；cleanup也失败；递归/循环 | parent部分效果如实、主因+cleanup单列；不承诺外部事务；循环/重入死锁拒绝 | O DAG and compound result；I 死锁反例与解除锁后回调；返回A事实未被B失败抹掉 |
| S17 / 17 | contribution冲突、实例启动后commit失败；invoke与drain/retire竞态；升级 | 发布前冲突零可见；外部残留单列；drain禁止新工作，已接受工作保有实现；old不可控new | O atomic gate trace；I 多extension跨扩展点publish barrier +真实调用锁pin，commit后观察不到半状态 |
| S18 / 18 | binding rev1；update配置rev2；运行中活动和原生自主变更 | 旧活动固定声明内的rev1；新调用rev2；可live apply须插件明确作用域及证据；不假报原生内配置受控 | O binding snapshots；I controlled config revision apply拒绝/丢回执未知，不重发，跨generation拒绝 |
| S19 / 19 | plugin正常移除；读取历史；重新装同id/version；旧event回来 | history可读中性元数据，缺parser明示；新generation≠旧，旧activity不复活；敏感正文不泄露 | O tombstone and epoch；I uninstall真实包后读取已记录typed事实，保留关联不可执行 |
| S20 / 20 | HTTP、CLI、本地同key调用同Surface | 相同环境、principal映射、binding/digest语义；只有一次状态主写；network认证独立但权限一致 | O ingress equality；I 三入口对同临时Store/Environment的跨入口重放与认证负例；任一自建ledger失败 |

## 扩展攻击场景

追加攻击时保留 ID/轮次，不把原20场景改名隐藏遗漏。每个攻击记录须链接具体规则和 future I 测试；离线检查仅针对其中有限抽象。

| ID | 攻击来源 / 事件序列 | 期望 / 未来I验收条件 |
| --- | --- | --- |
| X01 | A1-2/B1-5；use/destroy两个合法排序 | O枚举两序列，不能同时active Usage+closing；I真实线程在查/提交窗口交错，门/事务锁验证 |
| X02 | A2-1；create完成提交对象前崩溃 | O原启动义务或新对象义务至少一项存在；I真实SQLite逐写点kill，success不能独立放行 |
| X03 | A2-2/B2-5；未知输入含secret，缺port；同key全文变化 | O完整受保护fixture指纹不同/无port拒绝；I真实受保护port的稳定域/key轮换、零payload/普通hash进日志，不读取真实凭证 |
| X04 | A2-3；B1消失，K结果持久，B2重试 | O只读lookup脱活Binding，B2异digest不发；I卸adapter后当前principal read授权+中性BindingSnapshot |
| X05 | A2-4；g1本地seq40/g2本地seq1，native无序 | O不跨observer比本地seq；I跨epoch attestation仅按声明核对，证据不足disputed |
| X06 | A2-5/B2-1；同Q不同K两个reply，原K响应丢 | Oslot跨key一次占位/同K重放零发送；I事务唯一约束＋真实并发、重启、过期Hold，不冒领新应答权 |
| X07 | B2-2/C2-1/2/3；accepted→drain→晚对象/新Q/重attach/跨插件read | O按cut前根责任证明允许后继，任意新根拒绝；I两插件共同drain、迟到ObjectFact、保存Q、grant撤销/关联伪造负例 |
| X08 | B2-3；未知role→仅gap→旧idle证据 | Ounknown role保scope义务而unknown业务observation不pin；I限额后摘要义务不丢，旧idle不够，原生充分停止可解 |
| X09 | B2-4/C2-5；owned partial scope已知对象全关 | Oscope不充分阻normal retire；borrowed只本方关系；I全scope证据包含分离进程/远端衍生边界，不裸PID判断 |
| X10 | B2-6；X持A等Y/B，Y持B等Z/A，异步callback已返 | O等待图环拒绝，不以async豁免；I协作wait/capacity gate并发，非协作内部等待只stall/unknown不假保 |
| X11 | C2-4；无Store catalog读后正常移除 | O退本方静态关系、body保留，watcher不能伪静态；I真实临时目录字节不变/无Store写、移decoder正文gap可见 |
| X12 | C2-6；decoder解码中卸/升不兼容版本 | O执行期短pin、缺兼容拒绝；I真实插件包装读活动，结束后才退，旧binding不换新实现 |

## 离线脚本能与不能证明什么

`checks/contract_checks.py` 是纯stdlib有限参考状态关系：20项最小例子及新增攻击的正反例、少量事件排列。它不导入产品代码，不开进程/网络/SQLite，不验证密码储存，不测实际锁或native协议。S04/S05/S20仅说明关系/同一参考表/bytes保留，不能证明真实多轮、原生路由或三入口已经接线。S11是五个抽象崩溃切点，不是杀真实进程。
文档覆盖由脚本检查ID存在，不是内容正确性证明；设计闭合仍由完整攻击/主会话处置/独立复查承担。I列全部保留未运行，不能因O通过勾选I。

运行：`python3 specs/024-open-environment-kernel/checks/contract_checks.py`。缺场景文档、ID缺失、任何规范正例失败或负例未拒绝均退出非零；结果另保存在evidence/offline-checks.json。脚本只stdout输出，主会话将输出写入本任务evidence。

## 主验收新增有限反例（2026-10-03）

| 编号 | 正例 | 反例 / 缺席行为 | 实施验证仍未运行 |
| --- | --- | --- | --- |
| X13 | I1/g1/S与I2/g1/S分别可用，Ref不相等 | 跨实例、错kind、缺instance_id均拒绝，不猜owner | 真实resolver/权限路由、旧Ref迁移来源不升级控制权 |
| X14 | 新key有invoke可发；旧key有history-read可零发送重放 | 仅invoke重试旧key、无read的存在/不存在lookup统一拒绝；仅read不能新发；异payload冲突 | 真实权限撤销、错误响应无存在性泄漏、持久spent key不重发 |

当前脚本34项；原evidence/offline-checks.json的32项为修订前证据。新证据见evidence/acceptance-repair-checks.json。

## 五类参与者的完整生命周期验收

共同：无依赖时独立可用；安装→校兼容→activate→instantiate→至少两次交互→revision更新→drain→证明结束/停止→retire→history read→reinstall stale拒绝。

| 样例 | 核心验证 | owner适配验证（未来） | 缺席反例 |
| --- | --- | --- | --- |
| 原生 Agent/Codex | object lifetime/入口grant/多轮/代际/pin | 假原生peer通道、approval correlation、未知新命令原样往返、会话恢复证据 | 无Profile仍有bare native入口；UI-only功能gap；移除Harness不拖垮Skills |
| MCP服务 | borrowed/owned区别、动态interaction、control routing | 协议握手/tools_changed/request/notifications由adapter负责，不核心枚举工具 | 远端borrowed不触发kill；动态工具移除在本次请求报告拒绝；无协议插件明确缺席 |
| Skills资源 | 轻查询/不可变版本引用/共享内容/lifecycle | 真实临时目录路径校验、内容digest与投影加载由插件保证 | asset store存在不等于原生加载；无Harness仍read/list；无body parser只读元数据 |
| 短命令 | durable intent/output流/exit证据/取消未知 | 隔离controlled process退出计数、引用规格与cwd/grant | stdout ended不等exit；任意payload不能隐式shell；真effect未receipt保持unknown |
| 长期工具 | start已结束而job活、subscribe脱离、独立status/stop | fake watcher protocol、暂停/限流声明、明确owner停止证据 | 客户端断线不结束；deadline不自动kill；shared usage减少不destroy |

R 验收不属于本轮：真实品牌工具完整接入、真实模型/服务/GUI可用性。后续必须按真实安装版本与用户授权范围补，不沿用 P/O 作为产品闭环证据。
