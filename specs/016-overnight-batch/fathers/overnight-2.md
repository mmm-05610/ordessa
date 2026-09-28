# 父会话 overnight-2 · 内容资源+可执行扩展线（EXT → PX → CMP-skills → CMP-subagents）

本会话工作根 = /home/maoqh/projects/ordessa/worktrees/overnight-2（本目录；它不是 git 仓库）。
一切产出写 ./reports/；specs 与脚本用下面的绝对路径读。**git 纪律：只允许`git -C <儿子路径>` 的只读命令（status/diff/log）；主仓根的任何 git 写操作一律禁止。**

你是夜批编排者。逐个完成儿子包，串行：

1. /home/maoqh/projects/ordessa/worktrees/overnight-2/son-ext-extensions → /home/maoqh/projects/ordessa/specs/016-overnight-batch/dispatch/EXT-extensions.md
2. /home/maoqh/projects/ordessa/worktrees/overnight-2/son-px-prompts → /home/maoqh/projects/ordessa/specs/016-overnight-batch/dispatch/PX-prompts-ext.md
3. /home/maoqh/projects/ordessa/worktrees/overnight-2/son-cmp-skills → /home/maoqh/projects/ordessa/specs/016-overnight-batch/dispatch/CMP-skills.md
4. /home/maoqh/projects/ordessa/worktrees/overnight-2/son-cmp-subagents → /home/maoqh/projects/ordessa/specs/016-overnight-batch/dispatch/CMP-subagents.md

## 执行方式（每个儿子包）
1. **必须用封装脚本，禁止裸调 CLI**：/home/maoqh/projects/ordessa/specs/016-overnight-batch/bin/run-qoder.sh <son相对路径> <dispatch绝对路径> [超时秒]（默认 5400s）。退出非零可原样重试一次；再失败**你自己顶上做完**，报告标注「qoder 失败、zcode 代打」。
   **降级条款（仅当脚本自身无法运行**：语法/环境/权限/CLI 缺失——**qoder 执行任务
   退出非零不算**）：允许裸调 qoder CLI，但必须 `timeout 5400 qoder -p -w <儿子绝对路径>
   --permission-mode default -m qwen-3.8-flash "<提示词>"` 且 tee 留痕到
   specs/016-overnight-batch/reports/logs/；模型**只许 qwen-3.8-flash**；
   report 里记「封装失效原因+裸调已用+模型白名单遵守」。
2. 完成后你先自检：tasks 勾选与代码一致、测试真的跑过（留命令与计数）、写入面没越界（git -C 儿子 status 只在己目录）。
3. 审阅也走封装：/home/maoqh/projects/ordessa/specs/016-overnight-batch/bin/run-review.sh <son相对路径>（pi+mimo-v2.6-pro，物理只读）。产物在主仓 specs/016-overnight-batch/reports/ 下（绝对路径去读），把结论摘要抄进该包 report「审阅」节；脚本失败=记「未审阅+原因」，不阻塞下一包。**降级条款（仅当脚本自身无法运行）**：
   裸调 `timeout 600 pi -p --no-session --no-tools --model mimo-v2.6-pro
   --append-system-prompt "<审阅指令>" "<diff 内容>"`，模型**只许 mimo-v2.6-pro**，
   结论落 reports/<son>-review-fallback-*.md，同样如实留痕。
4. 提交留在儿子分支上（qoder 在儿子树内提交）；**绝不 merge/rebase/动其他分支**。

## 汇报
写 ./reports/overnight-2-summary.md：每包一段（结果/测试计数/qoder 与审阅记录/卡点/复用与自建清单），如实不粉饰。

## 阶段二（全部儿子完成后才做；只写文档不改代码，产出同样落 ./reports/）
1. **四家设计**：extensions/prompts/skills/subagents 四个域的四家扩展设计——把本线各包三态表中 hermes/opencode/dsh/kilo 的格子写成可派单方案包草案（每域一份 phase2-design-*.md）。
2. **新品牌侦察（本父会话只负责一份）**：qoder 侦察——按 docs/design/harness-configuration 盘点模式 + information-recon-priority.md 信任阶梯，落 ./reports/recon-*.md。
3. 阶段二产物也过一轮审阅（把文件内容直接喂 run-review 所用模型口径即可）。
先读 /home/maoqh/projects/ordessa/specs/016-overnight-batch/dispatch/../spec.md 的共同红线（复用优先第 7 条、CMP 三档口径、品牌优先级节）。
