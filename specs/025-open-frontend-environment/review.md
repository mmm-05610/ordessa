# 最终独立复查与交付结论

2026-10-03（Asia/Shanghai）。最终候选：models/v4.md。结论：**可交设计审核；未授权、未实施生产重构**。未解决阻塞/高优先级设计矛盾：0；真实产品、UI和安全验证缺口仍在。

## 主验收补充：A-03/A-04

上述为原交付结论；后续独立主验收复现A-03/high（同revision冲突后重复原观察错误解锁）及A-04/medium（完整快照恢复后过期缓冲再造stale），证明原28项参考检查未覆盖这两条序列，不是已证明生产故障。

用户要求直接修后，主会话增加独立conflict标记、重复观察/patch解除限制及完整快照缓冲清理，V4§14.3明确合同。新增两项检查同时覆盖拒绝与恢复正例，修后30项通过/退出0；恢复各旧行为的内存变异均失败。新证据evidence/acceptance-repair-checks.json；原offline-results.json与delivery-check.json保留为修订前证据。

两项现为closed-in-document-and-finite-reference；并非生产符合性证明，不宣称修后又经独立审查。后端Q01–Q12仍需双方共同合同收口，当前不标实施ready。其余既有审查与限制保留。

## 审查独立性与时间线

主会话唯一模型、文档和账本作者。三个攻击代理只读，均无嵌套，不写生产/本目录文件。最终复查由attack_c完成，未参与模型编写；B另复核schema身份和文档一致性。均使用自包含文件快照任务，而非继承全段历史。

|版本/轮次|发现与修订|复查证据|
|---|---|---|
|V1→第一轮→V2|25项，3 blocker/16 high/6 medium；§11新增领取、证据、持久标记、preflight、settlement、公共API、native隔离/commit、编辑与预算|A/B/C第二轮逐项复查原反例均文义闭合；B1-03公共API范围继续以B2收束|
|V2→第二轮→V3|16项，13 high/3 medium；§12新增通用target、跨major权威、重连alias、patch链、binding适用性、编辑发布、读权限/document epoch/审批/资源、decoded预算|A2四项/B2五项/C2七项逐项复核文义闭合|
|V3→独立复查→V4|schema版本仍可分裂authority（B3-01=F-01）；参考脚本conflict未阻capture（F-02）；另同步两处身份/依赖措辞|B复核B3及文档项闭合；C独立复现F02和重跑28检查，最终结论可交设计审核|

两轮共41个攻击条目；最终复查两个实质新增问题（schema问题由B/C独立重复发现，算同一问题）均保留ID与处置。V1/V2/V3原文件不覆盖，V4§14明确最终修订。原始代理返回在本会话；round-1/2及本页提供可独立审计的反例和结果。没有用“已考虑”或好评替代规则/反例。

## 最终复查新增问题与复核

**F-01/B3-01 high，V3**：资源schema v1/v2分别编码同一实体→完整TargetRef不相等→两个authority注册成功→两个owner写同事实。破坏N1。期望版本只作编解码，统一事实身份；缺映射拒第二写者。V4§14.1改normalize→CanonicalFactTarget，权威槽不含schemaId/version/major；namespace/alias经可信registry，不能自报换名字绕过。离线正反例不同编码同identity，第二注册拒绝。B/C独立最终复核文义闭合；真实身份registry/数据迁移未验证。

**F-02 high，V3参考脚本**：同revision不同内容→observe返回conflict→capture仍possibly-submitted。独立复查实际复现，是离线材料与规范不一致，不是生产故障。修脚本保留原Confirmed、标stale阻capture，并检查合法更新恢复正例。C最终独立复现 `conflict→capture:stale`，28检查与保存JSON逐项一致。完整来源/绑定证据机制仍未实现，此检查只支持该序列。

两处一致性项：state-ownership恢复稳定draftId；refactor-plan表明Chat为接入迁移，非Chat edit ticket不依赖Chat。B/C均复核闭合。

## 验收对账

|025要求|交付与等级|结论|
|---|---|---|
|两树快照、现状完整链及边界|inventory、source-snapshot/source-excerpts（S）|覆盖M/P身份与脏内容；无产品运行证据|
|事实/操作/待应用/展示草稿单一权威|state-ownership Mermaid+权威表、V4（D）|源版本、消费者、更新、持久化及生命周期明确|
|每版定义/时序/正反例/三个接入|V1–V4及scenarios（D）|模型版本保留；最终规范优先§14>12>11>基础|
|Profile/model覆盖及完整轨迹|scenarios端到端12步、V4配置语义（D/L有限）|pending与confirmed分开；不是实际发送日志|
|开放公共API与三插件|V4§11.5/12.5、boundary（D）|Agent/资源/非Chat目标均可表达；伪SDK未编译|
|22组场景|scenarios（S/D/L；U/P缺席）|逐项正反例、缺能力及未来方法|
|包职责、源码迁移、兼容/回滚|refactor-plan P0–P7（D）|九子包+Workbench按语义划分，不机械对称后端|
|两轮攻击与独立复查|round-1/2、本页（D；F02有L）|所有blocking/high设计反例闭合|
|离线确定性证据|checks/model_checks.py、offline-results（L）|28通过/0失败，主会话执行退出0；C独立重跑一致|
|边界不扩大|工具执行范围及delivery-check|仅025写入，抽样冻结源码hash不变，两树HEAD不变；没有生产代码/服务/024写入|

## 证据不能外推的部分

28项只覆盖命名的抽象序列：字段mask/顺序、同值操作、冻结与晚操作、乱序回执、reservation、CAS模型、unknown/partial、ABA、版本拒绝、patch补链、binding简化证明、authority/alias、显式路由、preflight/commit、document投递、输入epoch/Esc、审批单次claim、抽象预算，以及最终冲突/schema/恢复标记分支。

其中terminal marker失败是直接构造unknown，不是真实持久化写失败；schema检查是样例归一函数，不是真实物理实体解析；creation proof是局部身份判断，不是创建协议；预算是整数会计，不是内存测量。没有执行resolver真实异步返回乱序、model/provider字段组schema、DOM selection/中文IME、跨窗口共享owner、Token实际打包、Electron IPC与第三方隔离、OS安全资源open、每跳内存或后端条件应用。检查不导入生产代码，不能证明其符合V4。全部保留为refactor-plan实施门。

backend-interface-questions Q01–Q12只是前端所需能力与缺席行为，不是024任务拆分/接口冻结。旧格式/用户数据/真实授权没有获准变更。候选一致配置发送要求条件版本/整体patch保证，缺能力的真实链必须明确受限，不因普通聊天能发送就冒称统一闭环。

## 交付边界

产出已完成到设计审核层。下一阶段编码必须用户审核模型和方案后才可启动；本轮无需用户协调代理、启服务或处理Git。文件完整性/场景编号/攻击条目数/28离线检查/源码抽样不漂移见evidence/delivery-check.json。
