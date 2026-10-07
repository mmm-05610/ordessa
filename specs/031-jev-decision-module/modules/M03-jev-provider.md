# M03 · Jev 提供者

## 职责与复用
复用官方 typesafe-sdk 异步客户端；只将通用问题转换为 Choice/Score/Noul 并校验答案。
不依赖 Pydantic AI Agent，不 fork SDK，不读取 Ordessa，不定义判断顺序、阈值、配置字段或动作。
版本研究依据见 [research](../research.md)。固定研究提交不等于已验证安装包。

## 内部组成与接口
provider/settings/sdk_client/request_mapping/response_mapping/validation/failures。
公开 JevDecisionProvider 和 JevProviderSettings，端口统一为 DecisionProvider.decide，
不采用子方案中重复的 DecisionRequest/evaluate 类型名。
SDK client 由 provider 创建和拥有，组合根关闭；不借用其他组件的 client，因为 SDK 关闭行为会影响它。
业务节点只持有预算网关，拿不到 raw SDK 和 key。

## 输入与答案
- Choice：来自可信问题定义的optionId→描述封闭集合。maxBusinessCandidates=64，maxChoiceOptions=66，为策略预留none_suitable/insufficient_evidence槽，不能截断拒绝选项。官方最大255不是本版默认。M03不分页业务候选；无业务候选/单业务候选由流程判断是否需要模型。
- Score：明确2–10级有序 rubric；期望值可为小数。
- Noul：返回 yes 的概率，不伪造通用 confidence。
- Jev 不生成 Profile、任务拆分或自由文本解释。缺陷代码/证据 ID 被选中后，本地可信模板生成解释。

答案必须与本次 question 集合精确对应；类型、ID、选项集合、概率映射、有限值、
范围、总和、期望分数和模型版本都验证。SDK 丢弃未知答案后产生缺项仍判失败。
概率容差初拟绝对误差1e-6（不是官方保证），JD001用官方响应fixture核对数值舍入并冻结protocolValidationVersion；若不能满足，登记不兼容提交裁决，
不得实施者自动重归一或放宽。Choice并列最高值不是唯一胜者，策略定义明确并列分支。
usage 缺失记unknown，不填0；provider confidence不等于正确率或授权。

## 调用与预算
RetryPolicy(max_retries=0)；不在 provider 再包 Tenacity。
端点只来自管理员配置，默认官方端点；任务不可提供 base_url/extra_body/extra_headers。
模型ID固定在 settings，记录响应 resolvedModel；不默用latest。401/403直接技术失败。
超时/取消可能已经产生远端费用，attempt不返还，默认不自动重发。
发前无有效预算许可、过deadline、请求摘要不符时零HTTP。
绝对总时间由runtime限制，SDK timeout取剩余时间与管理员上限较小值。

## 安全
key通过secret resolver注入、不入DTO/state/log；禁用原始body调试日志与敏感自动采集。
可信规则与外部state分开；typed回答不证明免疫prompt injection，外部描述可影响模型判断，
硬权限/必需条件由普通代码和来源服务核查。
模块不承诺真实中文判断质量、成本、延迟或安全准确率，另设真实评测授权。

## 验收
T33–T42覆盖真实SDK+假transport请求映射、异常、隐藏重试、协议验证、客户端生命周期。
离线替身只能证明接入机制，真实Jev质量测试T60单独授权。
