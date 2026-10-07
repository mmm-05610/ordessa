# 固定来源与整合门

采样日期：2026-10-07。固定整合源码：`665ef379819bc2bac3afa68486cf8377b73975d5`，分支 `codex/architecture-cleanup`，实施目录 `/home/maoqh/projects/ordessa/worktree/032-architecture-cleanup`。以下来源已合入并做接缝复验，具体数字见 integration-report.md；不是整个产品完成声明。

## 来源

| 来源 | 固定 HEAD | 处置 |
| --- | --- | --- |
| 主树 main | `b4bf7cd90951d0fa9bcf3a3de2e66b7db6a62aa0` | 保留脏文件及未跟踪方案；不在这里直接强行合并 |
| Agent Tools | `20558870b3c1afaf62b1c1b585e6a0739f5acc95` | 建议整合树起点，已包含 main 与 021 已提交线 |
| 026 | `b12296ad4444c1cf0c1cdb891be2ca55cc850536` | 核对后纳入下面 3 个独立提交 |
| Jev | `3bbf68b41b01988b644934e5b436885b213eaecf` | 合并已提交成果，人工处理核心接口冲突并回归 |
| consolidated-core | `c20ce5853dba682602e1aa52ef6949d5fa190088` | 已是 Agent Tools 的祖先，无独立提交需合并 |
| 021 | `7951bf06a258d2dc41402556eb61319b8bab5cbe` | 已是 Agent Tools 的祖先；未提交成果另行保留 |
| i003 | `61a41b264df199bf3e2aff99fb70e198387d890c` | 旧桌面路径补丁；检查新树是否覆盖，不能直接重放 |
| w019 | `2b050e24674132e88dd381e47bed149aa7fa0b44` | 旧验收断言补丁；核对现行测试，不直接套旧基线 |

026 的 3 个独立提交：`5df67c464662d84969e99dfb5829bd6c608b7d9b`、`2dbbc209573dac05eaf10ed984457d9dfece86c5`、`b12296ad4444c1cf0c1cdb891be2ca55cc850536`；整合树对应 `f86999f381`、`b06158f1d9`、`c5a356d81c`。

## 整合顺序

1. 获确认后，新建干净整合树，建议路径 `/home/maoqh/projects/ordessa/worktree/032-architecture-cleanup`，分支 `codex/architecture-cleanup`；起点使用上表固定 Agent Tools HEAD。
2. 核对纳入 026 的 3 个提交，确认 UI 命令只有一个 owner，没有覆盖当前树已有修复。
3. 将 Jev 固定 HEAD 合入整合树。`git merge-tree --write-tree` 已发现 4 个冲突：`docs/known-issues.md` 以及 `pacthold/agents/{providers.py,public.py,runtime.py}`。不得选择整边覆盖；合并 Agent Tools 的最新材料/配置能力与 Jev 的纯读能力，不新增权威。
4. 核对 Jev 自动合并的 Codex provider 与生命周期文件；文本无冲突不代表语义正确。
5. 对 i003/w019 每项记录“已覆盖/仍必要/已过时”及对应源码或测试。若仍必要，在新结构原接缝实现同一行为，不引入旧平台路径。
6. 将主树新写入的重构纪律、032 方案及必要设计材料逐文件核对后纳入。已有 spec 的重复副本比较后保留有效内容，不用 root 未跟踪目录覆盖已提交新版本。
7. 检查隔离安装的模块来源、运行边界和离线回归。写入整合完整 SHA、冲突处理说明、测试结果后才冻结迁移起点。

上述步骤已按固定快照完成。Jev 合并提交 `7b6528689a8efa2f5c71d2aca3c37555a25e6b62`；组合守卫与评估指纹修复 `1cfc3199ddab381a720d19a7c7bdd6836db62d24`；当前产品构建锁同步 `665ef379819bc2bac3afa68486cf8377b73975d5`。迁移只能以此已提交源码为起点，不复制其他树当前脏文件。

## 未提交成果的保护

- Agent Tools 当前有未提交的 Harness 声明、Kilo、dsh、grok-build 及文档，不能复制进整合提交。
- 026 当前有未提交的 workspace/UI 命令与相关测试，不能整树替换或遗漏不登记。
- 021 当前有未提交的原生历史恢复及 Profile UI 改动，且运行着用户服务，不能改工作树或重启。
- 主树 `.gitignore`、文档 zip 和未跟踪设计目录不随方案提交。

迁移前记录这些脏路径的 Git 状态和文件摘要，不读取凭据内容。后续纳入必须来自独立已审查提交，并重新检查路径/职责归属。若新提交仍依赖旧链，只移植必要功能到目标归属，不能为接收成果恢复旧链。

## 当前验证边界

整合和本包列出的核心/Decision/Codex/UI 接缝测试已在新隔离环境实跑。其他 Server/Harness 全量继承红、GUI、真实模型、服务重启、运行数据迁移未验；其历史缺口保留在 docs/known-issues.md，不提升为完成。

项目内工作树容器统一到 `worktree/`：`consolidated-core` 已通过 git worktree move 移入；`.20260928-consolidation` 与 `server-core-cleanup-evidence-0016dc45` 同名移入。原 worktrees 目录已迁空并移除，历史证据不改写。`.codex/worktrees` 和 `.git/worktrees` 是外部应用/Git 管理路径，不属于待统一的项目容器，不能改名。
