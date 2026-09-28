# Quickstart / Validation

工作目录必须为自己的 worktree；不得复用根 .venv、editable 安装或 node_modules 写入。现有 known issues 只作线索，基线必须现场重跑。

## Spec Kit

```bash
export SPECIFY_FEATURE_DIRECTORY=specs/010-platform-core
bash .specify/scripts/bash/check-prerequisites.sh --json --require-spec --require-tasks --include-tasks
```

skills 已在 .qoder/skills；新 Qoder 会话可使用 /speckit-analyze、/speckit-implement。不要运行 specify/new-feature 重新建分支或覆写规格。若命令 UI 不发现 skills，直接读取相应 SKILL.md，按本线范围执行，不自行装插件。

## Backend setup（A/B；各树独立）

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r apps/server/lockfiles/server-linux-py312.txt
.venv/bin/python -m pip install -e 'packages/pacthold[dev]' -e packages/server-plugin-api -e 'apps/server[dev]' -e 'plugins/harness[dev]' -e plugins/workspace -e plugins/server-compat -e products/server
```

A 完成 runtime-compat 后增装本树该包；B 收到 A 完整提交后同样增装，不允许引用兄弟树路径。包不存在是未满足前置，不可绕过后假绿。

```bash
.venv/bin/python -m pytest packages/pacthold -q --junitxml=/tmp/ordessa-core-A-junit.xml
.venv/bin/python -m pytest apps/server -q --junitxml=/tmp/ordessa-server-B-junit.xml
.venv/bin/python -m pytest plugins/harness -q --junitxml=/tmp/ordessa-harness-B-junit.xml
.venv/bin/python -m pytest tests/acp_orchestration -q --junitxml=/tmp/ordessa-acp-B-junit.xml
```

上列 A 只强制第一个；B 全部。同机并跑时证据路径加本线+阶段，禁止覆盖他线结果。不要把可预期继承红退出码改成 0：保存原输出，单独计算分类结论。A 的跨旧产品调用破损必须经 B 适配闭环，A 报告明确边界。

各线实现后补本线 platform 测试并执行；不存在测试目录不是通过。A 独立 wheel 裸核心与 B 裸宿主验证必须在第二个全新 venv，缺业务包证据由 installed distributions 和全模块导入结果同时给出；不靠 monkeypatch sys.modules 代替真隔离。

## Frontend（C）

```bash
npm ci
npm run typecheck
npm test
npm run build
npm run test:electron
```

T003 冻结现有额外 workspace 测试命令；T021 后根聚合需显示每包 ID/计数/退出码。迁 Workbench 后单独运行其 workspace test，原套件不能因路径变化丢失。Electron 只用临时 userData/受控贡献插件，不连接真 Server。

C6 后增加 `npm run --workspace packages/desktop-platform/connections test` 与 Agent connections 所属包测试；包脚本必须在 T027/T028 实现。缺包/缺测试不是通过。CN-01–08 逐项报结果，原连接领域测试保留 ID 映射。只装 connections+非 Agent 替身的测试不得安装或启用 Workbench 来补隐式依赖。

## Gates

| 门 | 反例/拒绝行为 | 缺席时 |
| --- | --- | --- |
| 核心资源/幂等 | 丢回执后同键重发，重复 spawn 则红 | 未跑为未验证，不放行 |
| 核心实例 | 关闭 A 后 B 仍可读写 | 只测单实例不能通过 |
| 联合注册 | Core/wire 任一冲突，贡献/资源零泄漏 | 没 A 真实实现只能标替身通过 |
| 卸载/恢复 | 同 App 旧 endpoint 不可用、busy 拒绝 | 不许用新 App 避开 |
| Token | 变异生成重复 Token 必须抓住 | 只 typecheck 不通过 |
| 历史数据 | 旧夹具+重复启动+SQL 摘要 | 无夹具不能宣称兼容 |
| 账本 | 基线/当前逐 ID/原因差分 | 无原日志不能引用旧数字 |

## Report

reports/A.md、B.md、C.md 至少含：branch/base/head、任务状态、source→owner/test-ID 映射、命令/退出码/证据路径、继承红差分、反例、未测与阻塞。本线完成写 IMPLEMENTATION_REVIEW_READY，不写全项目完成。真实模型/用户数据/Windows 未测照实标记。
