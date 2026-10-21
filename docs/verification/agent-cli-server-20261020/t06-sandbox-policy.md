# T06：codex provider sandbox 政策（用户批准变更，2026-10-21）

## 背景

`plugins/harness/codex/.../provider.py:106` 把 `thread/start` 固定为 `sandbox:'read-only'`、
`approvalPolicy:'never'`，导致 Codex 工具无法写入 agent 工作目录 —— 这是"多轮工具操作"的结构性阻断。
子任务在 T06 干跑中发现：T05 原生 rollout 的 `turn_context` 显示
`sandbox_policy{"type":"read-only"}`、`permission_profile.file_system=restricted/root:read`。

## 用户决策

2026-10-21 用户批准：**改成 workspace-write**（写入仍限制在 agent 工作目录内，不弹权限请求）。

## 改动

`plugins/harness/codex/src/ordessa_harness_codex/provider.py:106`：
`sandbox':'read-only'` → `'workspace-write'`；`approvalPolicy` 保持 `'never'`。
这是 **provider 自有的 sandbox 政策**，profile 里的 sandbox 覆盖仍被拒绝（`SESSION_CONFIGURATION_UNAVAILABLE`），
未放宽其它权限面。

## 状态

- `python_workspace.py --install` exit 0。
- codex 自身测试在本环境有既有 collection error（缺模块，与 HEAD 一致），不能用它验证；
  **真实写入验证待下一轮用真实 prompt 完成**（创建文件 + environments.files 独立取回 + sha256）。
- 未做：approval/权限请求回传（`approvalPolicy` 仍 never）。
