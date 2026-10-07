# 设计验收与修订记录

## 分工与证据
本轮用户明确要求拆分并派独立子代理。六个模块由六名独立子代理只读设计，
主会话保有跨模块合同、取舍、整合文件与验收。子代理没有源码/Git写权，不递归派工，
没有运行模型/安装或碰正在工作的实施树。
M01 /root/design_contracts；M02 /root/design_runtime；M03 /root/design_jev；
M04 /root/design_task_gate；M05 /root/design_planner；M06 /root/design_integration。
报告是设计/源码引用，不是受控或产品验证。正式权威为整合后的本包，原报告矛盾不能覆盖合同。

## 第一轮设计验收
- 接受一个发行包、六个内部职责；拒绝机械拆六发行包。
- 接受原版graph+薄包装；预算/证据属于边界规则，不另建scheduler。
- 采用官方SDK；Jev只选择/评分，候选组合交外部业务组件；拒绝自由生成Profile/解释。
- M04报告将provider/policy/预算错误映射blocked，主会话否决：改技术联合终态。
- M04局部ready改gate_pass，避免被当最终提案ready；跨run免费缓存/幂等假设删除。
- M05提出Noul等同无候选的表述被否决，改为问题明确的是/否概率；拒绝路径显式Choice选项。
- M05候选数量/重试次数与runtime统一为实际有效限制的较小值，不各自维护独立预算。
- M06发现前实例只读描述/评估缺口，补JD007原机制，不以preview/prepare/private调用填绿。
- 基线在研究中前进；来源SHA分别保留，核心事实按git show固定，不修改实施树。

## 第二轮交叉攻击及裁决
| ID | 审查者/反例 | 修订 | 验收 |
| --- | --- | --- | --- |
| A01 | runtime：completed/cancelled竞争写双终态 | 单终态原子幂等提交，ACK未知先query，已完成不覆盖 | T24/T25 |
| A02 | runtime：intent只写内存就发网 | durable ACK、flush/fsync与发前门，memory仅offline | T21/T22 |
| A03 | runtime：取消域内await清理立即再取消 | 有界shield、secondary error、原取消传播 | T11/T28 |
| A04 | runtime：预算票复用/cross-run/排队过期 | run+摘要绑定单次opaque permit，slot后核预算和deadline | T06/T23 |
| A05 | Jev：配置0.7被codec拒绝 | 有限JSON小数合法，结构identity/revision仍强类型 | T67 |
| A06 | Jev：64候选+拒绝槽超上限 | 64业务/66总选项，拒绝槽不可截断 | T68 |
| A07 | Jev：组合器未注入导致字段逻辑塞runtime | proposalSource显式注入，M05 composition.py | T53/T67 |
| A08 | contracts：仅结构valid被升级ready | requiredValidationObligations逐项覆盖，未知拒绝 | T65 |
| A09 | contracts：同flow不同policy无法区分 | RunManifest/effectivePolicyRefs/result摘要绑定 | T66 |
| A10 | contracts：聚合缺blocked分支 | 明确fatalBusinessBlock及技术/clarify/revise优先 | T45/T46 |
| A11 | contracts：摘要域/checker/原核心DTO不闭合 | 域分隔与覆盖向量，CheckBatch、inputDigest映射及旧providerunsupported | T02/T58/T65/T66 |

协议概率误差1e-6是初拟不是官方保证，JD001必须以官方fixture验证后冻结；不由执行者自动放宽。

## 最终定向复核
M01审查者复核A08–A11：原反例在设计层闭合，无剩余设计阻断。
M03审查者复核A05–A07：原反例闭合，数值容差前置保持。
runtime A01–A04由主会话按第二轮完整建议逐项整合，新增对应场景；
不声称审查者已实际运行这些竞态/崩溃测试。
JD002实际DTO/编码向量/端口兼容审阅仍为JD003/JD007前置，文档存在不替代实现门。

## 残余风险和实施前置
1. 真正发布包与研究SHA对应、AnyIO取消/SDK重试均待授权受控验证。
2. 原核心纯读评估逐家provider支持范围未知；不可转译为所有Harness支持。
3. Jev中文质量、选项顺序、注入影响、费用与延迟未真实测试。
4. 图是可信代码，不是沙箱；文件证据无敌手防篡改保证；取消非远端退款/回滚。
5. 当前实施树正在被别的会话推进；本包尚未投递、开新树或确定实施基线。
上述不靠补抽象解决，在JD001/JD007/JD009/JD010用实证分账。

