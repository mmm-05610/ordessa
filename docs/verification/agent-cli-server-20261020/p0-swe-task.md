# P0（2 小时版）：一句话 → 多步工程任务（2026-10-21）

## 结论：✅ SUCCESS

用现成链路 + 一处配置上限调整，在**不重构异步语义**的前提下跑通"一句话让品牌自主修代码"：

1. 造一个**测试失败**的迷你仓库（`calc.py` 里 `add` 返回 `a-b`；两个 pytest 断言失败）；
2. 把这个仓库作为 local environment 的 work root；
3. 一次 `agents.prompt`（同步等待，`requestDeadlineSeconds=600`）：
   「这个仓库的 pytest 有失败。请阅读代码并修复 calc.py，让 pytest 全部通过。完成后只回复 DONE。」
4. codex 在 `workspace-write` 沙箱内**自主**读文件 → 改代码 → 回复 DONE；
5. **宿主机独立验证**：`pytest -q test_calc.py` → **2 passed**；`git diff` 显示 `return a - b` → `return a + b`。

真实模型调用 **1 次**（codex/ChatGPT 登录通道）；全程无人工干预、无权限弹窗、无异步轮询。

## 代码改动（唯一一处）

`requestDeadlineSeconds` 上限从 **300s 提高到 1800s**（`service_configuration.py` 与
`registry_runtime.py` 的校验），否则长任务无法在一次 wire 调用内完成。其它全部复用已有能力。

## 复现

```bash
bash tmp/p0_demo_swe.sh     # 初始坏测试 → 一句话 → 独立验证 → 打印 diff，约 1–3 分钟
```

原始 receipt：`raw/p0-swe-task-receipt.json`；脚本：`tmp/p0_swe_task.py`、`tmp/p0_demo_swe.sh`。

## 边界（如实）

- 这是**同步等待**版：回合时长必须 < deadline（当前 600s 配置）。5–10 分钟以上的任务仍需异步提交+轮询
  （之前的 P0 正式方案），本小时版不覆盖。
- 单回合内品牌自己完成多步（读/改/跑），不需要我们做规划器；
- 崩溃恢复/Use 泄漏仍是已知缺口（与长任务无关时可忽略）。
