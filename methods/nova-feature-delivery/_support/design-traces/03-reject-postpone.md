# 设计轨迹 C：拒绝并延期到下个周期

**合成的设计示例；非执行输入、非运行结果，不是 Ordessa fixture。**

1. Spec screening 因影响范围不清，判定必须有 spec。Spec 讨论后仍未解决安全/升级问题，Nova reviewer 本周期拒绝设计。记录拒绝者的上游角色/记录链接/理由，结果 `rejected`；不开始实现。
2. 若 owner 选择继续，进入待处理状态并说明不在本周期推进。该决定不是同意延期或预批准。
3. 下周期重新登记周期信息和 Blueprint/spec 版本，由 Nova reviewer/drivers 再审；必须取得该周期的明确批准后方可实现。若 owner 决定放弃，则登记取消原因并由其自行处理 Launchpad/Gerrit 记录。
4. `engineering.artifacts.create` 返回 `completed` 只说明拒绝/延期报告已存入 Ordessa，不能覆盖上游 `rejected` 决定或把拒绝改成批准。
