# recon-qoder · Qoder CLI 侦察(016 夜批 overnight-2 阶段二)

状态:侦察文档(仅侦察不实施,spec.md §品牌优先级 3)。方法=docs/design/
harness-configuration 盘点模式(配置入口→扩展面→通道→license→安全面)+
docs/design/information-recon-priority.md 信任阶梯。**每条事实带梯级标注**;
L6(记忆/第三方)一律不入正文。

  - 本地钉版(梯级:L5 一手观测;分级用本文信任阶梯 L1-L6,与 q3 线的
  「证据强度 L1/L2/L3」无关):qoder CLI **1.1.62**(对本地安装这一事实而言
  属仓库内可复算的稳定记录,引用时注明实测日期即可)(`/home/maoqh/.local/bin/qoder`,
  2026-09-29 `--version` 实测);安装形态 npm 全局(`qoder.cmd` 见官方 ACP 文)。
- 官方文档(L3,抓取日 **2026-09-29**):docs.qoder.com/cli/{permissions,settings,
  acp,overview}.md、/llms.txt。官方仓库:未见公开源码仓(文档站为主;L2 暂缺,
  下列"必须补证据"已标)。

## 一、配置入口(L3+L5)

- 配置根:`~/.qoder/settings.json`(L5 实测在案;`QODER_CONFIG_DIR` 可改,L3);
  项目级 `<project>/.qoder/settings.json`、机器本地 `settings.local.json`(L3)。
- 优先级(L3):schema 默认 < user < project < local < `--settings` < CLI 参数
  < 会话内 `/allow`;对象递归合并、部分数组并集合并;project/local 仅在目录受信时生效
  (`security.folderTrust.enabled` 默认 true)。
- 键族(L3):`permissions.{allow,deny,ask,additionalDirectories,trustDirectories}`、
  `general.defaultPermissionMode`、`security.{disableYoloMode,folderTrust.enabled,
  blockGitExtensions,environmentVariableRedaction.enabled}`、`model.name/
  reasoningEffort`、`tools.*`、`mcpServers/mcp.{allowed,excluded}`、`ui.maxTurns`
  (默认 1000,不影响 `-p`)。
- **permission-mode 五+1**(L3):`default`(安全读自动/敏感操作询问)、
  `accept_edits`、`auto`(agent 自判,含两级分类器与熔断)、
  `bypass_permissions`(YOLO,保留路径形状保护)、`dont_ask`(不问即拒)、
  `plan`(legacy,= default+Plan 态)。非受信目录强制回落 default(L3)。
- **L5 一手关键观测(016 夜批实测,三父会话独立复现)**:`qoder -p -w <tree>
  --permission-mode default` 下,一切需询问的写/执行按文档决策序落到
  "headless auto-denies"(L3 原文)——**实测自动拒绝 Write/Edit 与全部命令执行,
  会话严格只读**。结论:无人值守实现类任务在 default 档不可用;若未来要用 qoder
  代打,需 `accept_edits`+预置 allow 规则或 ACP 通道由客户端应答授权
  (本夜批未采用,纪律锁定 default)。
- 其他 L5:模型白名单实名单 `Qwen3.8-Max`/`Qwen3.8-Flash`(`--list-models`;
  小写 id `-m qwen-3.8-flash` 不可用,自动回落),账户为 credit 订阅制
  (额度尽即拒服务,实测)。

## 二、扩展面(L3)

- **Subagent**(https://docs.qoder.com/cli/subagent.md)、**Skills**
  (https://docs.qoder.com/cli/Skills.md)、**Plugins**
  (https://docs.qoder.com/cli/plugins.md + /cli/plugins-reference.md)、
  **Hooks**(https://docs.qoder.com/cli/hooks.md + /cli/hooks-reference.md)、
  **Commands**(/cli/commands.md)、**Agent Teams**(/cli/agent-teams.md)、
  **MCP**(/cli/mcp-servers.md + /cli/mcp-reference.md)、Built-ins
  (/cli/built-ins.md + /cli/builtins-reference.md)。以上页面为 llms.txt 索引
  (2026-09-29 抓取)在案链接,本次仅深读 permissions/settings/acp 三页,
  其余登记待读。
- 规则语法(L3):`ToolName(content)`、Bash 精确/前缀/通配、`mcp__<server>__<tool>`;
  Hook 决定可越过模式(“bypass_permissions 下 PreToolUse deny 仍阻断”)。
- ** Ordessa 对接注意**:qoder 的 subagent 在 bypass 声明时被**降级为
  acceptEdits**(L3,`security.disableYoloMode` 行)——与 C4 权限语义对齐时
  必须登记该降级。

## 三、通道(L3)

- CLI:`qoder [query]`、`-p/--print` 非交互、`-i` 交互续聊、`--resume/-c`、
  `--output-format`、`--agents <json>`、`--tools/--allowed-tools/--disallowed-tools`、
  `--add-dir`、`-w <dir>`、`--list-models`(L5 `--help` 实测与 L3 cli-reference
  索引一致)。
- **ACP**:`qoder --acp` 起 stdio ACP server;两档模式(default/yolo);
  登录态与 CLI 共享(`QODER_PERSONAL_ACCESS_TOKEN`);支持 IDE 侧文件/终端操作。
  **对接价值最高**:授权询问经 ACP `requestPermission` 回客户端(L3)——
  可解 -p 只读死结。
- **Agent SDK**(L3):官方 SDK(TypeScript/Python;https://docs.qoder.com/cli/sdk/overview.md),
  `canUseTool` 回调做授权(/cli/sdk/permissions.md,llms.txt 索引在案;本页未逐读,
  该句为索引摘要转述——梯级降为 L3-索引级,待核),tools/mcp/agents/skills/
  plugins/hooks 全暴露——比 ACP 更细的控制面。
- Remote:`--remote`/remote-control 守护(未深查,标注待核)。

## 四、license 与供给(L3/L5)

- 专有产品;Terms = qoder.com/product-service(未逐条审阅,标注待核);
  **无公开源码仓**(L3 站内未见 GitHub 链接)→ 无法 L2 钉版;版本只能钉发行物
  (npm 包/`--version`)。credit 订阅供给,额度制(L5 实测"credit usage limit")。

## 五、安全面(L3+L5)

- 目录信任(folderTrust)、保护路径(.git/.bashrc/.mcp.json 等)、路径形状防护
  (UNC/8.3/保留名)、YOLO 可被管理端禁用、环境变量脱敏开关、git 扩展拦截。
- Headless 决策序:L3 明示 headless 对 ask 自动 deny(与 L5 实测一致——本次
  夜批唯一可用的安全组合)。

## 六、建议(逐条可驳回)

1. **通道选 ACP 优先**:若未来把 qoder 纳入 harness 家族,经 `--acp` 对接
   (default 档+客户端应答授权)是唯一不解锁 YOLO 的无人值守路径;-p+default
   已实测不可用于实现类任务。
2. **钉版**:钉 npm 发行版 1.1.62 + 文档抓取日;升版走受控复核(-p 权限行为
   与 allow 规则语法为回归点)。
3. **模型面(硬闸)**:内置仅 Qwen3.8 系,与 Ordessa 现行 qwen 除名裁定直接
   冲突——**对接的前置条件=用户明示解除或模型白名单改道**(Custom Models 通道
   另核,L3 有 custom-models 页,未深查);在此之前不派任何实施单。
4. **缺口清单(全部"待核实")**:官方源码仓缺失(L2 悬空);hooks-reference
   逐事件语义;subagent 降级规则的精确矩阵;`--remote` 云面;SDK license 条款。

## 证据索引

- L5(路径根=主仓 specs/016-overnight-batch/reports/logs/。同源注记:下述汇总文件 worktrees/overnight-2/reports/
  qoder-unavailable-record.md 与这些日志是**同一受阻事象的多批记录**(overnight-
  1/2/3 三批封装运行+一次裸调探针,非同一批次),汇总文件是其中一份转写;路径根
  不同仅因产出目录不同)
  ,逐一列名:
  son-ext-extensions-qoder-20260928-232334.log 与 -20260928-234137.log
  (overnight-2 两次)、son-lsp-qoder-20260928-234131.log(overnight-3,
  同款只读受阻)、son-pe1-permissions-qoder-20260928-234151.log(overnight-1,
  同款)、son-ext-extensions-qoder-fallback-probe-20260929-000302.log(降级条款
  裸调探针:模型回落+credit 耗尽);父会话 worktrees/overnight-2/reports/
  qoder-unavailable-record.md(汇总)。
- L3(2026-09-29 抓取):docs.qoder.com/cli/permissions.md、/cli/settings.md、
  /cli/acp.md、/llms.txt(各页原文要点已入上行,未贴全文)。
