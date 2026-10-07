# 本地 Laya 真实冒烟评测

用户“测试一下/继续”授权本地合成样本推理；不授权 Jev 云端或 Harness。
使用原部署的 Laya SDK 0.3.20，缓存快照 55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851 下的 multilingual 权重。
原权重、tokenizer 和配置 SHA-256 前后全部一致；配置复制到本树临时目录后加载，避免上游 tokenizer 修补写入原快照。
凭据环境不传入子进程，HF 缓存独立且 offline，socket 连接禁止；不启动/重启用户服务。

已完成 25 次真实推理、49 个 typed questions；25 个模型评分场景中 9 个符合预定标签。另有 1 个缺授权硬规则场景零模型拒绝，不能计入模型成功。
第一次工具进程随轮次中断消失，日志为空且无 raw 回执，其推理次数 UNKNOWN；核实无模型进程后只恢复一次。上述数字只计有完整回执的调用。

- 明确中文任务、单交付任务仍被六维 rubric 全判 unknown；补充更完整任务并按每维正确绑定状态分别调用，仍全部 unknown。
- “否则取消套餐”的 Noul 仅给 0.0972；简短肯定/否定对照与显式中文 criteria 后，肯定场景仍低于预设 0.5。
- 简单部门分类识别 billing；明确指定候选身份在交换顺序后稳定。但按成本选择从 slow 变为 fast，存在本样本的顺序敏感性。
- 第三方注入文本的直接分类题选择 start（0.8686），未知配置直接分类题选择 ready；都是模型质量失败，没有触发任何实际操作。核心硬授权/owner 义务仍应独立阻止这些提案。
- 20/66 个选项都返回；66 候选误选 candidate_18。源码显示该场景每选项缩到约 4 tokens，可能丢失 cost 描述，所以不能把这个结果当作完整信息下的大候选能力证明。
- 多组概率经四位小数舍入后和为 0.9999/1.0001，违反当前 Jev 1e-6 容差；confidence 定义和 model ID 也不同。不能靠改 endpoint 直接声称等价。

结论：本地可运行且快，但当前权重/SDK/题目策略不达到当前任务的质量门；不能默认替代 Jev。保留 Jev provider；后续若选 Laya，需要独立适配、截断检查、领域验证/校准或微调。原 JD010/T60 真实 Jev 仍 NOT_RUN。

[机器汇总](summary.json) · [原始冒烟响应](laya-evaluation/raw.json) · [冒烟评分](laya-evaluation/report.json) · [单维与布尔对照响应](laya-controls/raw.json) · [对照评分](laya-controls/report.json) · [固定输入](laya-evaluation/inputs.json) · [对照固定输入](laya-controls/inputs.json) · [权重摘要](laya-evaluation/checkpoint-manifest.json)。

复验程序在 packages/backend/decision/evaluation/laya_probe.py，prepare/report 使用本树 venv；infer 使用既有 Laya venv，必须传隔离后的本地 checkpoint 和清洁/offline 环境。源码及输入均保留，不需要下载新模型。

此处 Jev NOT_RUN 是 Laya 评测时的历史状态；后续单独授权的真实 Jev 已运行为 PARTIAL，见 [Jev 新账本](../jev-zen-20261005/README.md)。
