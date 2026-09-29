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

## D-021-6 · 无 sudo 下的 C2 安装/启动验收策略

- **Context**：本机非交互 sudo 不可用（SC-2 实测），但 `unshare --map-root-user` userns
  可用；`clean-machine-accept.sh` 能在 chroot 里真实 `dpkg -i`，但从不启动 GUI/服务端。
- **Options**：(a) 只跑 clean-machine-accept 就宣称安装成功；(b) 三层组合：
  ①chroot `dpkg -i` 证安装与依赖清洁；②从解包 deb 的树以 `ORDESSA_BUNDLED_ROOT`
  覆盖 + xvfb 跑真实 GUI/服务端 smoke 作为 installed-launch 证据；③gold：chroot 内
  apt 装 xvfb 跑 GUI（时间允许）。
- **Decision**：(b)。三层证据分开记录，不互相冒充；与 `/opt` 真装的差异（路径前缀）
  在 final-report 如实标注。
- **Reason**：验收合同要求"真实安装成功"+"installed 启动正常"两件事；环境无 root
  时用 userns chroot + env 覆盖是最接近真实的可复现组合；脚本绿 ≠ 产品可用（SC-2
  风险 5 明示测试盲区）。
- **Immediate Implementation**：Release-Engineer 按 ①②执行 C2，③作为加分项。
- **Deferred Debt**：若日后获得 sudo，补标准 `/opt` 安装复验。

## D-021-7 · EA-1 裁决：wire seam 复用 C-03 WirePort；native harness 启动走桌面 argv

- **Context**：四个资产域桌面扩展（skills/mcp/model-provider/sandbox）激活形态全坏
  （无 default export / 对象非 factory / factory 期望注入）；SC-1 建议产品侧 provider。
  EA-1 复核发现 SC-1 选项 (a) **早已存在**：C-03 WirePort（`ordessa.wirePort.v1`）
  端到端已布线（宿主 service → IPC → 渲染代理），但 `HttpWirePort` 信封是平铺体，
  server wire/1 是严格 JSON-RPC 2.0 → 每调必 400，且零 live 覆盖所以无人发现。
- **Decision**：
  1. **Q1**：不新增任何 seam。修 `wire-port.ts` 信封对齐 JSON-RPC；渲染代理
     scope/ready 诚实化；四入口改 `requires:[WirePortToken]` + 各自 ≤15 行适配器；
     `extensions.json` 装配四扩展。禁止新建 capability/owner 扩展/域 carrier；
     foundation/server-bridge/extension-host 不得出现业务词。
  2. **Q2**：native harness 启动参数由**桌面主进程**构造、经 `ServerBridgeOptions.args`
     透明追加（env `ORDESSA_NATIVE_HARNESS` 门控）；server 默认组合维持
     `launch=None`（诚实缺席是正确行为）；server-bridge/electron 壳不做 flag 语义解析。
- **Reason**：令牌唯一通道是 C-03 立意（FR-031），第二传输面=第二令牌面；装配料
  （随机端口/token）只有宿主知道，静态 config 结构性装不下；launch 事实
  （acpBridge 路径/plugin_root）是桌面安装布局事实，归桌面所有。
- **Immediate Implementation**：I-001（wire-port+入口+装配）→ I-002（lifecycle args+
  main.ts 门控+deb stage harness 树与 node PATH 核查）。wire-port 修复是所有资产 UI
  与 C3 的单点前置，最优先。
- **Deferred Debt**：server 请求级 principal 注入面；`Refused` 类型化 code；chat
  resolver 可扩展化；`wireCallerOf` 若第四处出现提升为 contracts 助手；C-03 冻结文本
  勘误注记；deb 捆绑 node。
