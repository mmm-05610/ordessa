---
name: ordessa-incremental-did-apply
description: 受控应用精确 DID 补丁
---

# 受控应用精确 DID 补丁

仅通过 baseline owner：核对当前原基线、精确 NOR、目标快照、有效来源/质量/摘要审核、真实notice、按已配置v1问答policy记录的有效acceptance及该动作写权限；CAS更新并回读生成正式receipt。冲突返回合并复审，不能只刷新版本。新修订不继承旧确认。v1接受主Agent可追溯转交的明确用户问答，agent-attested等级如实记录，不要求再点浮窗或独立验签；由正式owner核验policy/版本/范围并留回执。Grant文档接受与业务实施权限分开。缺owner或receipt不可假称APPLIED，不能直接文件写绕过。

资源身份以当前 work.method_ref 固定的编译资源为准，不读 latest。所有副作用使用已注册 operation、稳定 request_id 与精确refs；能力缺失明确阻塞，Skill不自造后台状态。
