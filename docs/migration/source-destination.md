# Ordessa 根目录切换：source→destination 表与恢复步骤（草案 v1，切换前定稿）

状态：定稿待确认。候选 main 最终 HEAD `af31e92dc5eb...`（tag `baseline/cp-monorepo-0`，见 §0）；报用户确认后才执行切换。
本表覆盖 `/home/maoqh/projects/ordessa` 根内全部现存条目与根外相关路径。

## 0. 候选仓最终状态（2026-09-25 实测）

- 候选 main HEAD：`f8309c33f4a8`（tag `baseline/cp-monorepo-0`，已随收尾提交前移），祖先链 = 旧远端 main `6c14ea8d` → 8 个迁移提交（cd24ddd8 桌面 / 974e643a 后端 / b6a08cec 根文档 / db5ac119 workspaces 修复 / f70829f 文档与红账本裁定 / df632757 补 2 文件 / c0ff0479 移除桥二进制 / fa461219+573d5c15+af31e92d 记录）。
- 干净检出门 9/0 全过（verify-clean-run3.log）；独立审阅 docs/migration/independent-review.md。
- 历史 refs：594 archive + 3 reference + 基线 tag；`git fsck` 干净。

## 1. 根内条目去向

| # | 条目（根内） | 现状 | 去向 | 方式 |
| --- | --- | --- | --- | --- |
| 1 | `AGENTS.md`、`README.md`、`cleanup-report.md` | 旧工作区说明 | 被新 monorepo 根 `AGENTS.md`/`README.md` 取代；原文进 `docs/migration/legacy-workspace/`（历史参照） | 新仓提交 |
| 2 | `control/`（独立 git 仓，56 项未提交） | 调度与决策记录 | 历史→`refs/archive/control/*`（含 checkpoint `4fc80571`）；有效决策蒸馏进 `docs/`；原目录整体移至根外 `ordessa-legacy/control/`（保留原样，不再作为权威入口） | 目录搬迁（用户确认后） |
| 3 | `repos/backend`、`repos/desktop`、`repos/studio-legacy`（符号链接→根外主仓） | 链接 | 链接删除；目标主仓本体不动，历史已在 `refs/archive/agent-box*` | 删链接（目标保留） |
| 4 | `repos/harness-profile`（实体 git 仓 @1191a41b） | 独立插件，无活动写者 | 历史已存 `refs/archive/harness-profile` + bundle；目录整体搬至根外 `ordessa-legacy/repos/harness-profile`，独立开发继续在那里 | 目录搬迁（用户确认后） |
| 5 | `repos/harness-provider`、`repos/harness-workboard` | 同上（@e925f23 / @9168313） | 同上 | 同上 |
| 6 | `worktrees/harness-desktop-002/bc-native`（agent-box 工作树 @a0b343e0） | HD-002 后端候选；2 个 qoder 会话驻留；57411 服务腿运行中 | 历史进 `refs/archive/agent-box/heads/work/hd002-bc-native`；**定案：原位保留**（服务腿运行中）；退役=§3 步骤 9 **[USER GATE B]** | 原位（环境例外） |
| 7 | `worktrees/harness-desktop-002/fc-functional`（desktop 工作树 @450944bd） | HD-002 桌面候选；1 个 qoder 会话驻留 | 历史进 `refs/archive/agent-box-desktop-next/heads/work/hd002-fc-functional`；会话结束后退役（另批） | 保留原位（本轮） |
| 8 | `worktrees/harness-desktop-002/` 其余 16 个子树（bc、fc、e、f0–f3、h、s、profile、provider、fc-candidate 等） | HD-002 执行树群 | 全部历史在两主仓分支（work/hd002-*）；目录与会话退役另批处理 | 保留原位（本轮） |
| 9 | `worktrees/desktop-ui-codex`（desktop 工作树 @95aec192） | 1 个 qoder 会话驻留（其分支已并入 fc-functional） | 历史已存 archive；退役另批 | 保留原位（本轮） |
| 10 | `worktrees/integration-linux/{backend,desktop}` | LNX 集成树（backend @92a2d2ba） | 历史进 `refs/archive/*/heads/integration/linux-native-0`；目录退役另批 | 保留原位（本轮） |
| 11 | `worktrees/backend-loop/` | BE-LOOP-001 运行沙箱+12 隐藏工作树 | 全部分支历史在 archive/agent-box（work/be-*）；目录退役另批（含 worktree 记录清理） | 保留原位（本轮） |
| 12 | `worktrees/desktop-minimal`、`desktop-modular-v1` | 早期桌面线（后者 27 项未提交已快照） | 历史在 archive/agent-box-desktop-next；退役另批 | 保留原位（本轮） |
| 13 | `worktrees/pi-loop/` | C1-001 暂停态 | 历史在 archive；退役另批 | 保留原位（本轮） |
| 14 | `worktrees/harness-desktop-001/` | HD-001 旧树群（9 子树） | 历史在 archive；退役另批 | 保留原位（本轮） |
| 15 | 符号链接外部树（backend-service-env-provider、backend-runtime-round1、desktop-chat-wsl-round1、desktop-settings-round1、scheduling-legacy-server-round1、legacy-*、studio-*） | 指向 `/home/maoqh/projects/agent-box*` | 链接删除（根内）；目标本体全部保留在 projects/ 下不动 | 删链接（目标保留） |
| 16 | `archive/`（362M：2026-09-20 bundle、legacy-scheduling、workspace-backups 等） | 上一轮保全产物 | 整体搬至根外 `ordessa-legacy/archive-20260920/`（与 20260925 批次并列，不删除） | 目录搬迁 |
| 17 | `backups/`（hd002-transport-only-20260924） | HD-002 快照 | 搬至 `ordessa-legacy/backups/` | 目录搬迁 |
| 18 | `releases/`（candidate/current/previous 清单骨架） | 版本清单 | 搬至 `ordessa-legacy/releases/`；新仓 `docs/baseline.md` 承接版本事实 | 目录搬迁 |
| 19 | `runtime/native-pi-user`（运行数据） | 用户运行数据 | **定案：原位保留**，成为新根环境例外（.gitignore）；迁移运行数据另批 **[USER GATE C]** | 原位（环境例外） |
| 20 | `tools/`（excalidraw、lumino-host-probe、theia-probe，748M，多为 node_modules） | 探针/工具产物 | 搬至根外 `ordessa-legacy/tools/`（不进 Git） | 目录搬迁 |
| 21 | `.c1-001-runtime/`（686M，含 64B token 600） | C1-001 运行材料+凭据 | **定案：原位不动**（凭据与运行材料永不进仓），新根环境例外（.gitignore 忽略） | 原位（环境例外） |
| 22 | `.c1-001-secrets/`（drwx------） | 凭据目录 | **原位不动**，永不读取/复制/进仓 | 原位 |
| 23 | `.mimocode/`、`.qoder/` | 会话工具 | **定案：原位**，新根环境例外；随服务结束的清理另批 | 原位（环境例外） |
| 24 | 新 `main` 源码树 | — | 候选仓经 §3 v3 父目录换名落位为 `/home/maoqh/projects/ordessa`（对象库原样，不重建） | 换名落位（§3 步骤 8） |

## 2. 根外路径（不动 / 仅登记）

| 路径 | 处置 |
| --- | --- |
| `/home/maoqh/projects/agent-box`、`agent-box-desktop-next`、`agent-box-studio` 及全部 worktree 本体 | 不动；对象库完整保留，是历史第一还原源 |
| `/home/maoqh/ordessa-builds/acp-adapter` + go1.24.13 工具链 + cache | 不动；桥源码已入新仓，本地构建材料继续可用 |
| `/home/maoqh/ordessa-acceptance/`（hd004b 数据/会话/日志） | 不动（57411 服务腿在用） |
| `/home/maoqh/.agentbox-*` 数据根、`.pi/`、秘密定位器 | 不动 |
| `/home/maoqh/projects/ordessa-preservation/20260925/` | 本轮保全批次（9 bundle+12 快照+checkpoint），长期保留 |
| `/home/maoqh/projects/ordessa-monorepo-candidate` | 候选仓；切换后其对象库成为正式根 `.git` |
| `/home/maoqh/projects/ordessa-migration/` | 迁移工作区（契约、子代理产物、SWITCH 文档）；可归档至 `ordessa-legacy/` |

## 3. 切换步骤（唯一方案 v3：父目录换名 + 环境例外搬回，确认后执行）

设计要点（回应阻塞审查）：**绝不向非空目录 mv 候选仓**。落位方式 = 先把整个旧根
换名让出 `ordessa` 这个名字，再换入候选仓，然后把环境例外目录逐个**搬回新根原路径**
（同文件系统 rename，瞬时完成；不使用符号链接，终态零间接层）。由此：

- 活动目录（`worktrees/`、`runtime/` 等）**终态物理路径与切换前完全一致**；
- 旧根中**任何**未登记条目（包括任何时候出现/重现的 `.git`、`.agents`、`.codex`
  存根）自动随旧根进入 `ordessa-old-root/`，不丢失、不冲突、不阻塞流程；
- 每一步都是单条 rename，可逐步反向回滚。

已知隐藏目录实测（2026-09-26 00:20）：`/home/maoqh/projects/ordessa/` 内
`.git`/`.agents`/`.codex` **不存在**；存在的是 `/home/maoqh/projects/.git`
（mimocode 存根，9-21）、`~/.agents`、`~/.codex`（HOME 级，`.codex` 活跃）——
后三者在本流程交换范围之外，**一律不动**。若切换预检时发现旧根内出现任何隐藏
目录/未知条目，按"随旧根进 `ordessa-old-root/`"处理并在 GATE A 清单中列明。

每步一条命令路径。执行者=本会话主代理；**[USER GATE]** 步骤必须先获用户明确答复。

前置条件：用户对本表无异议；验证门全过（数量门禁 run6 + 逐 ID 账本，分别见
`docs/migration/README.md`）；审阅发现闭环。

**阶段一：旧根瘦身（可在 GATE A 前执行，全部可逆 mv）**

1. 冻结候选：记录 `git -C candidate rev-parse main`（= tag `baseline/cp-monorepo-0`）；`git fsck` 留证据；确认 `git status` 干净。
2. 建立接收目录：`mkdir -p /home/maoqh/projects/ordessa-legacy/{repos,workspace-root}`。
3. 搬迁旧工作区容器（§1 中 disposition="搬 ordessa-legacy" 的条目，逐条 `mv` 原名）：`control`、`repos/harness-{profile,provider,workboard}`、`archive`→`archive-20260920`、`backups`、`releases`、`tools`；`ordessa-migration`→`ordessa-legacy/migration`。
4. 删除符号链接（只删链接，目标一律不动）：`repos/{backend,desktop,studio-legacy}` 与 `worktrees/` 下 11 个指向 `/home/maoqh/projects/agent-box*` 的链接。
5. 让位旧根文档：`mv ordessa/{AGENTS.md,README.md,cleanup-report.md} ordessa-legacy/workspace-root/`。

**阶段二：[USER GATE A] 换名落位（单脚本顺序执行，见下方窗口说明）**

6. **[USER GATE A]** 停点：报告 (a) 阶段一实际执行清单逐条 src→dst；(b) 预检输出（见步骤 7）；(c) 环境例外清单与隐藏目录实测。用户答复后才执行步骤 8。
7. 预检（脚本自动，全部通过才继续）：候选仓存在且 HEAD=tag 且 status 干净；`ordessa-old-root` 不存在；`ls -A ordessa` 盘点存档；活动进程清点（57411 腿 pid 与 4 个 qoder 会话 pid 的 `/proc/<pid>/cwd` 记录——rename 不影响已打开句柄与 cwd inode，此记录用于事后核对字符串不变）。
8. 换名落位（四条同文件系统 rename，连续执行，总耗时亚秒级）：
   ```
   mv /home/maoqh/projects/ordessa                     /home/maoqh/projects/ordessa-old-root
   mv /home/maoqh/projects/ordessa-monorepo-candidate  /home/maoqh/projects/ordessa
   for d in worktrees runtime .c1-001-runtime .c1-001-secrets .mimocode .qoder; do
     [ -e /home/maoqh/projects/ordessa-old-root/$d ] && \
       mv /home/maoqh/projects/ordessa-old-root/$d /home/maoqh/projects/ordessa/$d
   done
   ```
   `.git`/`.agents`/`.codex` 等任何其他旧根条目**刻意不搬回**（`.git` 存根若进入
   新根会遮蔽真 `.git`），留在 `ordessa-old-root/`，去向在 GATE A 清单列明。
9. 事后核对：`git -C ordessa rev-parse HEAD` = 步骤 1 记录值；`git -C ordessa status`（预期仅环境例外被忽略，无其他脏项）；活动进程 `/proc/<pid>/cwd` 字符串与步骤 7 记录一致；`ls ordessa/worktrees/harness-desktop-002/bc-native` 路径可解析；不重启、不触碰任何服务进程。

**窗口说明（诚实登记）**：步骤 8 第一条与最后一条 rename 之间存在亚秒级窗口，
期间 `/home/maoqh/projects/ordessa/worktrees/...` 等绝对路径暂不可解析。运行中
进程的 cwd inode 与已打开句柄**不受影响**（rename 语义）；仅当某进程恰在窗口内
发起**新的**绝对路径访问才会失败一次。57411 腿与 qoder 会话均空闲；GATE A 时
用户可指定执行时刻进一步压低风险。

**阶段三：切换后验证与回报**

10. 在正式根按 `docs/baseline.md` 完整重跑：npm 侧（ci/typecheck/test/build）；Python 侧（venv + lockfile + editable 安装 + 四套件，`tooling/checks/verify-clean.sh` 已版本化可直接以其门禁参数对账）；桥重建 sha256 比对。
11. 回报 `BASELINE_ESTABLISHED_WITH_KNOWN_ISSUES`（或未完成项）。worktree/服务腿退役 = **[USER GATE B]**；`runtime/` 等运行数据迁移 = **[USER GATE C]**。

## 4. 回滚步骤（任一步失败即停，逐步反向；全部为同文件系统 rename，无覆盖）

| 失败时点 | 回滚动作（按序） |
| --- | --- |
| 阶段一任一步（步骤 2–5） | 对已执行的每条 `mv` 原路反向 `mv` 回 `/home/maoqh/projects/ordessa/`；删除的符号链接按 §1 条目 15 清单重建（`ln -s <target> <link>`） |
| 步骤 8 第 1 条后（旧根已换名） | `mv /home/maoqh/projects/ordessa-old-root /home/maoqh/projects/ordessa` |
| 步骤 8 第 2 条后（候选已落位） | `mv /home/maoqh/projects/ordessa /home/maoqh/projects/ordessa-monorepo-candidate`，再执行上一行 |
| 步骤 8 搬回段中途 | 对已搬回的例外目录逐条 `mv /home/maoqh/projects/ordessa/<d> /home/maoqh/projects/ordessa-old-root/<d>`，再依上两行还原 |
| 步骤 9–10 验证失败 | 同上整段反向还原（候选回原名、旧根回原名），验证失败证据留档；阶段一条目最后逆序还原 |
| 任何时点的历史恢复 | `docs/reference-index.md` §How to restore（普通 clone + fetch archive/reference；bundle；tar；checkpoint）——与根目录状态无关 |

隐藏目录去向（显式）：切换后旧根全部残余（含任何 `.git`/`.agents`/`.codex` 存根、
`repos/` 空壳等）位于 `/home/maoqh/projects/ordessa-old-root/`；回滚时随旧根整目录
还原，无需逐个处理。`/home/maoqh/projects/.git`（projects 级存根）与 `~/.agents`、
`~/.codex` 全程不动。

## 5. 服务影响

- **无服务被停止/重启。** 57411 腿（pid 381142 等）继续以 `ordessa-legacy` 之前的原路径运行；其工作树条目 6 定案为原位保留：§3 v3 的换名落位后，`worktrees/` 等环境例外目录被搬回新根**原物理路径**（§3 步骤 8 搬回段），服务腿的路径解析不受影响；仅存在亚秒级换名窗口（§3 窗口说明，GATE A 时可指定执行时刻）。会话与服务腿结束后再清理（[USER GATE B] 另批）。
- 4 个 qoder 会话（bc-native×2、fc-functional、desktop-ui-codex）的 cwd 在旧树；原位不动则不受影响。
- 18790/18810 试验服务器已在此前停止（2026-09-25 实测无监听），与本次切换无关。


## 6. 执行记录（2026-09-26）

- **进程停止**：4 个 qoder 会话此前已自行退出（无需处理）；57411 服务腿进程树
  （381142 python server → 394938 access-entry → 394946 桥）经单次 SIGTERM 于
  ~5 秒内全部退出，端口释放，父进程 systemd --user 未重启它。未按名杀进程。
- **保全预核验**：10/10 bundle verify + 9/9 SHA256SUMS 通过后才动目录。
- **新改动补存**：68 棵工作树逐一 status 比对，9 棵有脏内容者全量补存至
  `ordessa-preservation/20260926-pre-switch/workspace-backups/`（18/18 校验和，
  含 studio-ui-reconstruction 961 文件）；59 棵干净（bc-native/fc-functional 均净）。
  hd002 容器的 profile/provider 裸副本与 .git/.agents/.codex 存根另存
  `hd002-profile-provider-stubs.tar.gz`。
- **工作树退役**：三主仓 65 棵非主仓工作树全部 `git worktree remove`（44 干净 +
  24 保全后 --force 清理忽略产物），0 失败，随后 prune；主仓对象库与全部分支未动
  （抽查 work/hd002-bc-native=a0b343e0 等均在）。日志 RETIREMENT-LOG.txt。
- **搬迁**（SWITCH-MOVES.txt 逐条）：.c1-001-secrets/.c1-001-runtime/.mimocode/
  .qoder/runtime/worktrees 骨架(含 backend-loop 整体)/tools → `ordessa-legacy/env/`；
  control → `ordessa-legacy/control`；repos/harness-{profile,provider,workboard} →
  `ordessa-legacy/repos/`（三独立插件仓原样保留）；archive→`archive-20260920`、
  backups、releases → legacy；根三文档 → `legacy/workspace-root/`；悬空符号链接删除。
- **换名落位**：`ordessa→ordessa-old-root`、`ordessa-monorepo-candidate→ordessa`
  两条 rename 完成；mv-back 清单为空（例外已全部外迁）。亚秒窗口内无活动进程
  （服务腿已先停）。
- **验收**：见 §0 与 `verify-clean-run7-newroot.log`（新根为源的严格门禁克隆验证）。
