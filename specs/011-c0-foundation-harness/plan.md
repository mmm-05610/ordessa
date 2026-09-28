# C0 实施计划

分支：`codex/011-c0-foundation-harness`；工作目录：`/home/maoqh/projects/ordessa/worktrees/011-c0-foundation-harness`。

1. 读 [共同 plan](../011-plugin-rollout/plan.md) 和原包，确认当前 cwd/branch、干净起点和旧实现来源。主代理只派单包子代理实现/改测试，自己审差分、跑验证、维护文档和 git。
2. 设置 `SPECIFY_FEATURE_DIRECTORY=specs/011-c0-foundation-harness`、`SPECIFY_FEATURE_NO_PERSIST=1`。本树携带现有 Spec Kit 模板/项目 skills；按 spec→plan/contracts→tasks→analyze→implement→converge 实施，不运行脚手架覆盖已写规格。
3. 先审核 A/C 平台及侧栏，准备 Harness 契约与独立测试。platform-server 原会话继续收尾，本线只读其已提交报告，不接管未完成项；等它发布最终检查点后固定 SHA，按共同 plan 集成验收并修剩余缺口，发布 foundation。随后落实 Harness/ACP 真实类型与 proof，发布 harness-api。
4. 依赖检查点：本线发布 foundation/harness-api；全链随后消费业务完成检查点。按 [协议](../011-plugin-rollout/contracts/checkpoints.md) 固定 SHA 正常 merge 后复跑，不读他树脏文件。可选 UI glue 未就绪不阻止后端/纯域条目。
5. 按 tasks 完成实现与反例；普通错误在边界内修到过，不因阶段提交、首个红例、文档状态旧或上游尚在跑就宣告整线完成。真正跨契约语义问题记录后只暂停相关项。
6. 各阶段 commit；导出 `api-requests.md` 和 `integration-request.md`。产品/根锁/compat 公共清理归 C0。完成发布 `codex/011-c0-ready` 与 report.md；主线合并/推送另行处理。
