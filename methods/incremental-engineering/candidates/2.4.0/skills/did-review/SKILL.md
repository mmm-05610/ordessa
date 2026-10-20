---
name: ordessa-incremental-did-review
description: 分别审核来源语义、工程标准与摘要忠实度
---

# 分别审核来源语义、工程标准与摘要忠实度

冻结 proposal/baseline/sources/standard/summary。来源逐项审 add/modify/delete/retain，调用逻辑 semantic_judge（JEV真实adapter）得到支持/不足/冲突/无法确定及原生结果引用。不可挑有利来源或换提示刷通过。工程质量逐项对选定标准原文内容证据，标题齐全不证明合规；标准未选或裁剪无接受不得CLEAR。摘要覆盖重要删除、取舍风险、未决和精确版本。意见不批准。缺上下文先补事实；冲突显式裁决；unknown不通过。最终真实JEV质量待验证不得用offline/fake替代。

资源身份以当前 work.method_ref 固定的编译资源为准，不读 latest。所有副作用使用已注册 operation、稳定 request_id 与精确refs；能力缺失明确阻塞，Skill不自造后台状态。
