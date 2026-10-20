# 设计轨迹 B：负评返工、等待并恢复

**合成的设计示例；非执行输入、非运行结果，不是 Ordessa fixture。**

1. Blueprint/spec 已获当前周期批准，第一次 patchset 收到 `-1`，指出兼容性论证不足。Gerrit 报告保存评论 URL 和精确 patchset；结果是 `changes_requested`。
2. Owner 回复评论，补充回归测试和设计说明，推送新 patchset。旧 patchset 结果不继承；新 patchset 重新经过 Zuul check。
3. reviewer 尚未复审，owner 报告 `waiting`，包含所等的 reviewer 回应、change/patchset URL、责任人和最近检查时间。Ordessa 不监听上游事件，也不自动唤醒。
4. reviewer 后续给出正面意见并按项目规则批准。Owner 再次核对周期批准仍有效、patchset 未变且 check 为绿，再报告恢复；进入 Zuul gate。
5. 如果等待期间 feature freeze 已过或周期已换，旧批准不能沿用：回到本周期/下一周期 Blueprint/spec 讨论。此处暂停直到 Nova 有权角色重审。
