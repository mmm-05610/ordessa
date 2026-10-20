# 设计轨迹 A：成功走到正式版本

**合成的设计示例；非执行输入、非运行结果，不是 Ordessa fixture。**

1. Owner 报告已登记的 Nova Blueprint `bp-demo` 和周期 `cycle-X`。报告记录链接与问题摘要。
2. Spec screening 报告 `spec_required=true`；Nova reviewer 对设计提出意见，owner 更新 spec。Nova drivers 确认 spec 和 Blueprint 对 `cycle-X` 获批。
3. 实施报告绑定获批 spec revision，说明测试、文档、发布说明已准备，并提交 Gerrit change 和 patchset。
4. Zuul check 对精确 patchset 通过并在 Gerrit 显示 Verified +1；所需 code-review votes 完成，core reviewer 标记 Approved +1；Zuul gate 通过并显示 Verified +2。
5. Gerrit/Zuul 合入后，报告绑定合并 commit SHA。发布准备报告确认目标 Nova 分支、release note 和冻结要求。正式版本报告引用官方 Nova release page、版本号和被包含 commit。
6. 每一步各自使用 `phase-report` 报告；一次 `engineering.artifacts.create` 仅记录一个阶段。Ordinal graph completed 只表示该份 artifact revision 持久化。
