# 侦察 · mcode(MiniMax Code CLI)——按 harness-configuration 盘点模式 v1

状态:**侦察第一版,供分类与派单审阅;不是实施授权,也不是已验证能力声明。**
查询日期:2026-09-29。方法:`docs/design/information-recon-priority.md` 信任阶梯
(L2 官方源码钉 commit → L3 官方文档 → L4 官方公告;无 L6 断言入册)。未启动
harness、未调真实模型、未读取用户配置。

## 1. 身份与固定源(L1/L2)

| 项 | 值 | 证据级 |
| --- | --- | --- |
| 品牌/命令名 | mcode(MiniMax Code CLI,"MiniMax Code") | L2 |
| 官方仓库 | `github.com/MiniMax-AI/minimax-code` | L2(API 探测 200) |
| main HEAD(抓取时) | `68284bb101bb`(2026-09-28T16:22Z) | L2(HEAD API) |
| 最新 release tag | `v0.5.8` @ `e3d78551c241`(其前 v0.5.6/v0.5.5/v0.5.4/v0.5.3) | L2(tags API) |
| 发行基线注记 | README 以 npm `@minimax-ai/code@0.4.12` 表述数据目录默认值语义——这是**开源起点版**的表述基线,与 tag 线(v0.5.x)是两条版本线;钉版建议(§4)只认 tag 线,0.4.12 仅作历史语义参考 | L3@commit(README) |
| License | **MIT**(仓库 license API + LICENSE-STATUS.md "First-party default license: MIT";另有 NOTICE/THIRD_PARTY_NOTICES/LICENSE-STATUS 三件) | L2(license API)+L3@commit(LICENSE-STATUS) |
| 技术底座 | `third_party/pi-mono`(Pi 框架)+ `third_party/sandbox-runtime`(沙箱 fork),pnpm workspace | L3@commit(docs/architecture.md) |
| Node 兼容 | 22.19+(22.x)/24.2+/25/26;官方安装器落 `~/.minimax-code`,数据目录 `~/.minimax`(`MINIMAX_DATA_DIR`/`MAVIS_DATA_DIR` 可覆盖) | L3@commit(README) |
| 官方文档站 | agent.minimax.io/docs/cli/*(quick-start/features/faq) | L3 |

引用均为 `raw.githubusercontent.com/MiniMax-AI/minimax-code/68284bb101bb/...` 固定
commit 抓取(2026-09-29);主分支≠发行版,两者已分开登记(阶梯§二.1)。
**证据级口径(审阅修订)**:按阶梯字母义,本仓 README/docs/* 属官方**文档**——钉
commit 抓取不改变其文档性质,一律记 **L3@commit**;仅 GitHub API 对仓库元数据的
枚举(存在性/license/tags/HEAD)按 **L2**(官方源·钉 ref)。下表已按此口径标注。

## 2. 入口与通道(L3@commit,README 入口表)

| 入口 | 命令 | 备注 |
| --- | --- | --- |
| TUI | `mcode [prompt]` | 权限/变更审查在 TUI 内 |
| Headless | `mcode exec [prompt]` | CI/批处理;headless 模型覆盖走只读账户态检查(architecture.md) |
| **ACP** | `mcode acp` | **一等入口**(README 入口表 + architecture.md:"packages/tui owns … the headless and ACP adapters")——对 Ordessa ACP 适配层是直接可挂接形态 |

## 3. 配置面盘点(L3@commit,按 classification.md 十二类走查)

| 面 | 已核事实 | 缺口(待核) |
| --- | --- | --- |
| 模型/供应商 | BYOK:`mcode provider add --name --base-url --api-format {openai-completions, openai-responses, anthropic-messages} --model --api-key-env [--context-limit --output-limit] --use`;存于活动 profile 的 `config.yaml` `custom_provider` 段;`minimax_api` 段为官方保留;自定义 auth header(config.yaml,Anthropic 兼容 Bearer 中继);`/provider` 斜杠切换;`mcode provider list --json` | config.yaml 完整键集;模型级 overrides 单run覆盖(headless 有,键名待核) |
| 数据/凭据 | OAuth Core 管凭据刷新与登出(architecture.md);API key 走 env 引用(`--api-key-env`),值不进配置 | keychain/OAuth 存储独立性未核 |
| 指令 | `mcode init .` 生成/更新项目 `AGENTS.md`;仓库自带 AGENTS.md | AGENTS 发现规则、SYSTEM/APPEND 分层:未核(Pi 系语义,可参照 pi 家族但不得默认等同) |
| Hooks | Claude 格式 hook 注册 JSON(事件→command/timeout,`${PLUGIN_ROOT}` 展开;Stop 事件 `systemMessage` 展示语义已核:展示≠turn 失败状态) | 事件全集、阻断语义(hook 失败是否拦截操作):未核——**不得默认 Claude 等价** |
| 插件 | MiniMax-format Plugin manifest(hooks 数组引用);本地插件管理目录(examples.md §4) | 插件 ABI/自定义工具注册面:未核 |
| 权限 | `packages/local-runtime` 供 permissions 设施(architecture.md);TUI 内权限审查 | 权限规则键、approval 模式、是否可配置化:未核 |
| 沙箱 | `third_party/sandbox-runtime` 实沙箱 fork 在仓(architecture.md) | 沙箱配置键与平台限制:未核 |
| 遥测 | docs/telemetry.md 在册 | 内容未读;入册前须核 |
| 浏览器/多模态 | README 宣称 browser control(读页/填表/上传) | L3 官网级,未到 L2 源码核 |

覆盖度自查:以上为 README/architecture/hooks 三份 L2 文档走查所得,**不是**封闭
全集(阶梯§二.2);source-index 式逐键索引未做,列为下一轮侦察项。

## 4. 与 Ordessa 的接缝初判(侦察结论,非裁定)

1. **ACP 通路成立概率高**:`mcode acp` 一等入口 + Pi 底座(与 pi 家族同源),
   ACP adapter 形制可参照既有 pi/codex/claude 三家;但 ACP 版本/能力面
   (session/new、set_model、permission 请求)须 L5 受控探针(E2 假端点)后才可入册。
2. **provider 配置同构**:api-format 三值恰为 Ordessa `CANONICAL_PROTOCOLS` 四值
   之子(缺 gemini-generate);`provider add` 是 CLI 状态命令而非纯文件投影——
   model-provider 域接入需先核 config.yaml 是否可直接文件投影(与 CLI 命令的
   等价性,L5)。
3. **hooks 是 Claude 格式**——对 EXT 域是"格式同源"线索,但"同名不等于同 ABI"
   (classification.md §四.4),阻断语义必须逐事件核。
4. **建议 pin**:追 tag 不追 main;当前建议 `v0.5.8`(`e3d78551c241`)。npm 线
   `@minimax-ai/code` 与 tag 线版本号不同步(见 §1 发行基线注记),选 npm 钉版时
   须单独核对该 npm 版本对应的源码 tag,不得默认同名。主分支变更频繁
   (2026-09-28 当日仍有 fix),不钉 main。
5. **license**:MIT 主仓;`third_party/pi-mono`、`sandbox-runtime` 的许可与
   NOTICE 链在引入前须单独核(LICENSE-STATUS.md 是入口),不因主仓 MIT 而推定
   全树 MIT。

## 5. 下一轮侦察清单(按价值排序)

1. config.yaml 全键集 + profile 机制(L2:`packages/config` 源码)。
2. ACP 会话面能力矩阵(L5 受控探针:假端点驱动 `mcode acp`)。
3. 权限/审批键与 TUI 审批的配置化(L2:`packages/local-runtime` permissions)。
4. hooks 事件全集与阻断语义(L2:`docs/hooks.md` 全文+agent-modules 源码)。
5. AGENTS.md 发现/分层规则(L2;与 pi 家族差异表)。
6. telemetry.md 内容审查(入册前置)。

来源:[MiniMax-AI/minimax-code](https://github.com/MiniMax-AI/minimax-code)@`68284bb101bb`(README/docs/architecture.md/docs/hooks.md)、[tags API](https://api.github.com/repos/MiniMax-AI/minimax-code/tags)、[官方文档站](https://agent.minimax.io/download)、[开源公告](https://x.com/MiniMaxAgent/article/2089561311722258817)(L4,仅作发现线索,已升级 L2)。
