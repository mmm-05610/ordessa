# 材料准备验证

2026-10-04：12张N001–N012工单严格结构校验通过，退出0；单执行者队列声明的66处写权重叠只在串行工单间豁免，不授权跨队列同路径并写。家族切片须按冻结后的具体路径分工。

18份Markdown本地链接检查7项，broken=0，退出0。git diff --check退出0，但新材料未提交，故另做本地链接与工单解析，不能仅用Git差异检查宣称资料正确。

本包未进行产品测试/实际Harness运行/安装/真实模型调用，也没有验收原实施成果。网页通道研究不计产品测试。没有改动原源码、原status或原rulings；仅新增030及本夜目录。

校验命令：

```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python /home/maoqh/.agents/skills/incremental-work-order/scripts/validate_order.py docs/implementation/agent-tools/night-harness-expansion/work-orders --strict
git diff --check
```

这份记录只表示MATERIAL_READY；原生运行门与反例必须由执行者实际执行，不使用本材料结果替代。
