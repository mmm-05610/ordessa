# 检查点与依赖消费

## 生产者
| 检查点 | 唯一发布者 | 分支 |
| --- | --- | --- |
| foundation | C0 | codex/011-foundation-ready |
| harness-api | C0 | codex/011-harness-api-ready |
| profile-api | Z1 | codex/011-profile-api-ready |
| chat-api | Z2 | codex/011-chat-api-ready |
| permissions-api | Q5 | codex/011-permissions-api-ready |

检查点分支首次创建后保持不变；修订发布带 `-r2` 后缀的新检查点，在生产者报告明确兼容关系。消费者记录实际消费 SHA，不能跟着浮动分支自动重建。首版 feature 不可 force push/reset 已发布历史。

## 发布步骤
1. 在生产者本树完成本阶段代码/测试与整洁提交；字段/方法必须可导入、有受控调用 proof、明确 supported/unknown；API_READY 不冒充全产品完成。
2. 新建 `specs/011-plugin-rollout/checkpoints/<name>.json`，至少记录：
```json
{
  "schemaVersion": 1,
  "name": "foundation",
  "producer": "c0",
  "status": "READY",
  "planAnchorRef": "refs/heads/codex/011-plugin-plan",
  "implementationSha": "<上一笔已验证代码提交的完整 SHA>",
  "dependsOn": {},
  "publicExports": [],
  "commandsAndEvidence": [],
  "limitations": []
}
```
foundation 的 publicExports 包括实际核心 API/包位置；API checkpoint 列实际导出与所验证的生命周期边界。命令写实际退出码/收集数/失败 ID 对照，不能只写“通过”。limitations 不得隐藏该 checkpoint 的必需门未过。
3. 提交这份记录后创建上表的分支指向该记录提交。代码 SHA 必须是发布提交祖先。该分支是本仓共享 git 引用，兄弟树无需网络或用户转贴就能读。最终阶段另发 `codex/011-<role>-ready`，不修改先前 API checkpoint。

## 消费步骤
```sh
git rev-parse refs/heads/codex/011-foundation-ready
git show refs/heads/codex/011-foundation-ready:specs/011-plugin-rollout/checkpoints/foundation.json
```
记录得到的完整 publication SHA，核对 producer/status/implementationSha ancestry、planAnchorRef 和依赖。对方发布“PARTIAL/BLOCKED”不能当 READY。提交或保护本线变更后，把**固定 publication SHA**正常 merge 到自己的分支，跑本线基线与接口 proof；冲突按 owner 处理。禁止 rebase/强推改写已消费的公共历史。

## 依赖不构成整线停机
启动先形成实际符号缺口清单，保存在自己的 feature `api-requests.md`（调用者、目标操作、DTO、失败反例、请求 owner）。同仓其他主会话可用 `git show <consumer-branch>:<feature>/api-requests.md` 读取。生产者在发布前主动检查各消费者请求；不依赖用户复制粘贴。

未发布时继续本线内容/存储/纯编译/独立 UI/测试 fixture 等不依赖生产接口的条目；依赖型工作不得猜造 Token 或勾完成。完成独立任务后再查依赖；等待时用平台等待机制或有上限的间隔，避免高频空转。每次有检查点即可自动继续接线。若生产者明确 BLOCKED 或无法完成设计要求，交付已完成检查点和精确缺口，不无限等或假报全部实现。

C0/Z1/Z2/Q5 必须先做 API 阶段，不能以“等消费者全完成”拖延发布。最后生产全链允许在 C0 集成树验证，结果按具体消费 SHA回填各域报告，避免定义循环依赖。
