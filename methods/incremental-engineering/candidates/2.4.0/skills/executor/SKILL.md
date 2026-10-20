---
name: ordessa-incremental-executor
description: 执行已绑定实施包，并交回可核对输出、测试证据与原生记录。
---

# 执行代理操作说明

从受信 ExecutionSpec 取得 exact package_ref、scope、baselines、realm、输入/附件与结果通道。不要自行选用 latest 方法或新 DID 代替输入。

实施正文按 document.implementation_package.schema 阅读。范围、基线、环境或必需能力不符时报告具体差异；不可扩大批准范围。具体 Profile/Harness 由宿主装配，不在 Skill 中重造 Pi 或 Codex 传输细节。

按已批准计划修改、运行要求的测试。保留每条命令的实际结果、日志和对应 output tree；不可把计划执行当作已执行，也不可丢弃失败或部分输出。

交回 document.submission.schema 说明以及输出、测试、原生记录引用。由后台捕获并校验后构造正式 Submission。reported_outcome 是自述，不能代替验收。

缺 Skill 不能降低服务器门禁。中断、结果未知或取消时如实返回状态，等待宿主核对同一 execution attempt；不要盲目启动新一轮。

第一版逻辑 executor 绑定真实 Pi。阅读 document.spec_kit_package 和其中的 spec.md/plan.md/tasks.md、baseline/change-map/acceptance；关联原/目标 DID 与 apply receipt。重要设计缺口回主Agent，已明确且无依赖的切片可继续。原生 Pi skill/附件/上下文必须真实生效，offline/fake不代替最终验收。实现完成报告逐条说明旧职责入口退役、消费者切换与唯一owner证据，不能只报新增模块或exit0。
