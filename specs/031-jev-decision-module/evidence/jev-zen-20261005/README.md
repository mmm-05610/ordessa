# Jev / OpenCode Zen 真实评测

用户指定 opencode_zen 凭据、https://opencode.ai/zen/v1/systemone 与 jev-1.13-free，另授权将凭据移至私有目录。官方路由说明见 https://opencode.ai/docs/zen/#jev；无付费 fallback、重试或 Harness 调用。

**T60 / JD010 PARTIAL，不宣布质量门通过。** 官方 typesafe-sdk 0.7.2 + 原 pydantic-graph 2.54.0 + 模块 gateway + 本地持久证据实际运行。实际请求 50 次（上限 64）：鉴权冒烟 1、首场景 3、其余场景 45、规定兜底 ID 的大候选补充 1。有时长回执的恢复评测 42.23 秒、容量补充 10.05 秒、鉴权 1.28 秒；首次三次请求未留存时长；每请求 10 秒上限、重试 0。账单费用 UNKNOWN，不能将官方标称免费写成已核算零费用。

有完整答案的 23 个模型场景中 22 个符合推理前固定标签；另一个零模型硬拒绝不能算模型成绩。明确任务六维单独对照均 pass；中文布尔正反例及英文正例、候选顺序、未知配置与注入小样本的答案见回执。单交付任务 gate-single-result 仍 clarify，问题为 acceptance_expression/delegation_unknown；未改标签或降低阈值。这不是总体质量百分比，也不能仅据这些样本判定生产成熟。

首场景 primitive-zh 已完成三次请求并持久化响应摘要；评测收集器用了 result_digest 而本模块写入 terminal_digest，导致 KeyError。修正后仅推进剩余场景，未重发。其答案内容未留存，质量 NOT_VERIFIED；初次失败日志与原 run 的事件/terminal 保留。恢复回执将此行 http_requests=3 用于累计，不能解读为本恢复进程又发三次。

原 capacity-66 使用 refuse/need_info，违反 provider 规定的两种兜底 ID；本地 policy_invalid、HTTP 0，是评测输入限制而非模型误判。补充保持原候选成本和预定 candidate_00 标签，只将兜底 ID 换为 none_suitable/insufficient_evidence。该次在 10 秒内未返回，provider_timeout，HTTP 1，服务端完成及 usage UNKNOWN，未重试。补充脚本回执的 total_http_requests_including_prior_probe 是该程序的局部计数；跨进程总数以 summary.json 的明确四项账本为准。

原准备的九样本/54 rubric 问题未全量运行；此处复用推理前已冻结的本地 Laya 合成样本与正确单维对照。Laya 9/25 标签匹配的独立记录不充当 Jev 证据；相同主体样本尚有绑定状态/截断限制，不作总体优劣结论。

[汇总与 usage](summary.json) · [逐场景答案](evaluation/receipt.json) · [最小鉴权](minimal-probe.json) · [补充容量回执](capacity/run/receipt.json) · [原固定输入](smoke-inputs.json) · [单维/布尔对照](control-inputs.json)。durable 目录保留真实 graph run 的哈希链与提交回执，技术 completed 仅表示评测流程结束；clarify/evaluation_only_no_proposal 不生成实际操作提案。

凭据只在请求进程内读取，未写入证据/日志/Git。用户授权后迁移到 /home/maoqh/.codex/private-vault/opencode_zen，目录 0700、文件 0600；本树原文件已不存在。没有服务重启、其他工作树写入、用户 DB 迁移、merge/push。

复验代码：packages/backend/decision/evaluation/jev_zen_probe.py。必须另明确实时授权、费用和累计尝试范围，传 --authorize-live 与 --credential-file；不是默认离线入口，不自动调用。current gateway profile 只允许本次已观测到的 jev-1.13-free 响应身份；正式默认 provider/业务规则未换成 Laya。
