---
name: ordessa-incremental-package-review
description: 审核实施包忠实完整且可分工
---

# 审核实施包忠实完整且可分工

冻结原/目标DID、apply receipt、接受、源码和包版本。正向逐条变更/保持约束到任务/验收，反向逐任务到批准规定或授权自由；检查新增兼容链、恢复规则、阈值和删除遗漏。核对依赖无环、共享写权及测试资源、缺资源停止范围。缺重要决定回提案，转换失真回converter。结论PACKAGE_REVIEW_CLEAR/PACKAGE_REVISION_REQUIRED/SOURCE_DECISION_REQUIRED/PARTIAL_REVIEW_CLEAR，不自动派工。

资源身份以当前 work.method_ref 固定的编译资源为准，不读 latest。所有副作用使用已注册 operation、稳定 request_id 与精确refs；能力缺失明确阻塞，Skill不自造后台状态。
