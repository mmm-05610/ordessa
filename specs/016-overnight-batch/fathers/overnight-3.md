# 父会话 overnight-3 · 服务绑定+存量补完线（LSP → CMP-mcp → CMP-profile → CMP-chat）

你是夜批编排者。逐个完成儿子包，串行：

1. /home/maoqh/projects/ordessa/worktrees/overnight-3/son-lsp → /home/maoqh/projects/ordessa/specs/016-overnight-batch/dispatch/LSP.md
2. /home/maoqh/projects/ordessa/worktrees/overnight-3/son-cmp-mcp → /home/maoqh/projects/ordessa/specs/016-overnight-batch/dispatch/CMP-mcp.md
3. /home/maoqh/projects/ordessa/worktrees/overnight-3/son-cmp-profile → /home/maoqh/projects/ordessa/specs/016-overnight-batch/dispatch/CMP-profile.md
4. /home/maoqh/projects/ordessa/worktrees/overnight-3/son-cmp-chat → /home/maoqh/projects/ordessa/specs/016-overnight-batch/dispatch/CMP-chat.md
## 执行方式（每个儿子包）
注：dispatch/方案文档一律用主仓绝对路径传给 qoder（如
/home/maoqh/projects/ordessa/specs/016-overnight-batch/dispatch/xxx.md），
因为部分儿子树内没有 specs/016；执行与提交仍在儿子树内。

1. 你可开子代理；优先尝试用 qoder CLI 执行：一包一进程，cwd=儿子工作树，
   把 dispatch 文档路径+「/goal 完成该文档的所有要求」交给它；记录退出码。
   先探测 qoder 的 CLI 用法（--help），失败两次即放弃 qoder，**你自己顶上做完**，
   报告标注「qoder 失败、zcode 代打」。
2. 完成后你先自检：tasks 勾选与代码一致、测试真的跑过（留命令与计数）、
   写入面没越界（git status 只在己目录+reports）。
3. 然后调审阅：探测 pi CLI（`pi --help`），用 mimo-v2.6-pro 模型对儿子目录的
   git diff 做审查（把 diff 或关键文件喂给它），结论记入该包 report「审阅」节。
   审阅调用失败：记「未审阅+原因」，不阻塞下一包。
4. 提交留在儿子分支上；**绝不 merge/rebase/动其他分支**。

## 汇报
全部完成后写 specs/016-overnight-batch/reports/overnight-3-summary.md：
每包一段（结果/测试计数/qoder 与审阅记录/卡点/复用与自建清单），如实，不粉饰。
先读 specs/016-overnight-batch/spec.md 的共同红线（特别是第 7 条复用优先与
CMP 甄别三档口径）。

## 阶段二（全部儿子包完成后才做；只产出设计/侦察文档，不改插件代码）

1. **剩余四家设计**：hermes/opencode/dsh/kilo 的覆盖扩展设计稿——对照
   specs/016 各包的三态表，把"四家格"写成可派单的方案包草案，落
   specs/016-overnight-batch/reports/phase2-design-<域>.md（每域一份）。
2. **新品牌侦察（三份）**：mcode / qoder / zcode TUI——按
   docs/design/harness-configuration 的盘点模式（固定仓库快照 HEAD、配置入口、
   扩展面、license、与 ACP/CLI 的通道证据、建议 pin）；zcode TUI 从 ZCode 官方
   GitHub 仓库取证。落 reports/recon-<品牌>.md。互联网检索遵守
   docs/design/information-recon-priority.md 的优先级路径。
3. 阶段二产物同样走审阅与"未审阅如实记"规则。
