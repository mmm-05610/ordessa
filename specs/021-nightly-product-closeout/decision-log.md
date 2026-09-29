# decision-log.md — 长期有效裁决

格式：Context / Options / Decision / Reason / Immediate Implementation /
Deferred Debt。只记真正需要长期记忆的裁决；普通 bugfix 不写在这里。

## D-021-1 · worktree 的 git 排除方式

- **Context**：integration worktree 放在仓库根 `worktree/` 下，会污染 `git status`。
- **Options**：(a) 改项目 `.gitignore`；(b) `.git/info/exclude` 本地排除。
- **Decision**：(b)。
- **Reason**：任务约束"不要仅为 worktree 目录修改项目级 `.gitignore`"；排除是本机夜间安排，非产品事实。
- **Immediate Implementation**：`/worktree/` 已加入 `.git/info/exclude`。
- **Deferred Debt**：无。

## D-021-2 · Phase 1 头号调查假说：装配缺口

- **Context**：默认桌面装配 `products/desktop/extensions.json` 仅 14 项 enabled；
  skills/mcp/prompts/permissions/model-provider/memory/lsp/subagents/runtime-preferences
  域不在其中（018 已把它们并入 main）。这符合"代码存在，产品没装进去"模式。
- **Options**：(a) 假定全部是桌面扩展、直接往 assembly 加；(b) Phase 1 先核实每域的
  producer/consumer 形态（桌面扩展 vs server 侧插件 vs 未收尾），再按"接通现有 >
  修现有 > 扩展现有 contract > 新增机制"处理。
- **Decision**：(b)。
- **Reason**："没找到入口"不等于"功能不存在"；盲加 assembly 可能装进未收尾能力，
  也可能漏掉 server 侧注册路径。
- **Immediate Implementation**：ledger W-001；Phase 1 盘点产出能力域×装配形态矩阵。
- **Deferred Debt**：无（盘点本身即今晚任务）。

## D-021-3 · 真实模型调用授权口径

- **Context**：AGENTS.md 规则 9 要求 real-model 调用需用户事先授权；今晚 brief 明确
  要求真实 Harness E2E（streaming/tool call/approval）作为硬验收。
- **Options**：(a) 全晚不用真实模型（无法满足验收）；(b) 以今晚 brief 为授权依据，
  真实 Harness E2E 在克制成本下执行。
- **Decision**：(b)。
- **Reason**：brief 即用户指令，含验收硬性要求；同时约束"使用现有登录态只读、
  不修改认证状态、不覆盖用户配置"。
- **Immediate Implementation**：真实 E2E 用隔离 data-root + 临时项目；不动用户凭据。
- **Deferred Debt**：大规模/高成本模型调用仍需单次授权（沿袭规则 9）。

## D-021-4 · 架构工作位次

- **Context**：020 盘点显示 runtime-compat 大头是承重件搬家 epic；017/010 留有
  S1c 等架构尾巴。
- **Options**：(a) 今晚推进架构 epic；(b) 架构第二优先级，仅守 boundary 底线，
  只有直接阻塞 P0/P1 才动。
- **Decision**：(b)。
- **Reason**：最高产品目标是可用 deb；acceptance.md §Architecture 明确今晚不必须
  完成 runtime-compat 退休/storage 搬迁等 epic。
- **Immediate Implementation**：W-009 等标 DEFERRED；boundary tests 保持绿色即可。
- **Deferred Debt**：020 波 2（依赖 pi 两顶裁定）、S1c 组合决策——留给白天主线。

## D-021-5 · 真实 E2E 模型后端：DeepSeek 官方 key

- **Context**：用户分两步提供 E2E key（23:5x OpenCode Go key；00:14 换为
  **DeepSeek 官方 key**，不限额度，声明可用于所有 harness），置于 nightly worktree
  根 `key.txt`。该文件首查未被 ignore（nightly 视角 `?? key.txt`）。
- **Options**：(a) key 直接入上下文人工保管；(b) key 不可读、只许脚本运行期消费，
  本地排除保证不进 git；(c) 不用 key，E2E 停在外部 blocker。
- **Decision**：(b)。`/key.txt` 已入共享 `.git/info/exclude`；处理铁律与逐 harness
  接法见 api-key-usage.md；key 有效性以零 token `/models` 探针验证（HTTP 200）。
- **Reason**：用户明示"不可读、只可用脚本使用"；DeepSeek 官方与仓库自带
  bounded-acceptance 模板（deploy/opencode/opencode.json）及 harness 注册表对齐，
  是最通用的后端选择。
- **Immediate Implementation**：Phase 3 起真实 Harness E2E 以 DeepSeek 为后端；
  首选组合按"本机已装 pi + 需安装的 opencode"现场以真实可用重排。
- **Deferred Debt**：OpenCode Go 端点研究留作 fallback（api-key-usage.md §资源）；
  逐 harness provider 物化的诚实验证是 Phase 4 任务。
