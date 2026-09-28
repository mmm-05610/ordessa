# 父会话 overnight-2 · 内容资源+可执行扩展线（EXT → PX → CMP-skills → CMP-subagents）

你是夜批编排者。逐个完成儿子包，串行：

1. /home/maoqh/projects/ordessa/worktrees/overnight-2/son-ext-extensions → /home/maoqh/projects/ordessa/specs/016-overnight-batch/dispatch/EXT-extensions.md
2. /home/maoqh/projects/ordessa/worktrees/overnight-2/son-px-prompts → /home/maoqh/projects/ordessa/specs/016-overnight-batch/dispatch/PX-prompts-ext.md
3. /home/maoqh/projects/ordessa/worktrees/overnight-2/son-cmp-skills → /home/maoqh/projects/ordessa/specs/016-overnight-batch/dispatch/CMP-skills.md
4. /home/maoqh/projects/ordessa/worktrees/overnight-2/son-cmp-subagents → /home/maoqh/projects/ordessa/specs/016-overnight-batch/dispatch/CMP-subagents.md
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
全部完成后写 specs/016-overnight-batch/reports/overnight-2-summary.md：
每包一段（结果/测试计数/qoder 与审阅记录/卡点/复用与自建清单），如实，不粉饰。
先读 specs/016-overnight-batch/spec.md 的共同红线（特别是第 7 条复用优先与
CMP 甄别三档口径）。
