goal: 无人值守完成 specs/026-open-environment-migration 007→012 全部可推进工作（用户已就寝，
2026-10-04 晨前）。遇到阻塞不停滞：记录阻塞+选项+建议后立即切换到下一个 ready 项，绝不空转、
绝不为了等用户而停机。禁止事项不变：不 push/不合 main/不装系统资产/不碰真实数据与用户服务/
不调真实模型/不读秘密；本地检查点提交继续。纪律不变：最多 2 并发子代理（槽满即转）、测试槽串行、
我唯一持 Git/契约/status；红集 stash 对照；不删断言不 skip 求绿；U 未验永不报 DONE。

执行循环（每轮）：① 收割完成的子代理→复核（亲自复跑其套件）→pathspec 提交→台账勾结；
② 立即回填槽位（按下方队列）；③ 我本人并行做独占工作（合同/裁决/报告/归组/收口）；
④ 每单收口写 order-XX-report + status + 检查点提交。上下文不足时依赖 status.md 与
evidence/order-*.md 恢复状态，不重做已完成项（git log + tasks.md 勾选为准）。

队列（严格按序，单内切片并行）：
- 007 收口：P 验收合入 → 批次3（mcp/subagents/lsp/runtime-preferences 顶层化）→ T007-02/03
  补测 + T007-06 穿透验证 → 样例#1/#3 若桥面允许 → order-007-report 定稿 → 007=DONE(codeReady)。
- 008：按 evidence/order-008-f5-freeze-plan.md 执行 S1→S6（S1=T008-11 冻结+台账增量；
  复用裁决已定：自建、零新 npm 依赖）；物理迁移 frontend 包组（manifest/lock 我独占）；
  A96–A103/A109 S/I 证据；收口。
- 009：桥/交互面（E2/F4；surface 输入 ticket/IME 边界补测；dialog 能力；诊断复用）。
- 010：Agent 唯一 owner（A1 落地；含 bootstrap_native_profile=False 产品翻转——当时机成立）；
  T010-12..14 公共消费者迁移。
- 011：受控全链（capture/fingerprint/reconcile；kill 窗产品级）；真实模型/GUI=U 不做。
- 012：退役清账（C95-1..7 逐项）、docs 清扫（012-07 写权内）、发行产物验证（本地 staging）、
  A96–A111 总回归、最终交接报告。

预裁决（夜间不再询问，按此执行）：复用=自建（F5 plan）；runtime-preferences 保持顶层化+登记
用户裁决项；electron 腿只用本地 staging（不装 /opt）；产品 bootstrap 翻转等 010 显式绑定路径
就绪才动；mcp 扁平 import 名冻结；docs/** 仅 012-07 动；agent-server 装配开关与 ui-foundations
padding 属用户/012 裁决不擅改。

终止条件：012 收口，或全部剩余项均需用户输入——此时写最终交接（SHA 链/勾选账/缺口/待裁清单/
可试入口），停在已提交状态。晨起第一入口：status.md 顶部 + git log --oneline -30。
