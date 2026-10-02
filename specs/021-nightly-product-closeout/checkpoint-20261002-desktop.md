# Desktop 阶段检查点 — 2026-10-02

状态：PARTIAL / 可用开发版；不是发行验收通过或合并批准。
恢复标记：`checkpoint/021-desktop-20261002-input-stable`。
工作目录：`/home/maoqh/projects/ordessa/worktree/021-ordessa-product-closeout`。
当前开发分支保持不变；根仓 main 不动，不 push。

## 今日实际验收

- [x] Pi：选择带模型 Profile，首次消息收到真实回复。
- [x] 模型控件读取实际会话模型，Profile 应用后不再显示空模型。
- [x] 用户报告：单独切换模型后，后续发送成功。
- [x] 用户报告：切模型后中英文输入告警闪烁已消失。
- [ ] 切回 Profile 后的后续发送：最新截图与 journal 仍为 unknown。
- [ ] 输出期间修改配置：当前输出不打断、下次发送应用。
- [ ] Codex 官方登录两轮聊天与配置切换。
- [ ] Claude API 两轮聊天与配置切换。
- [ ] 三品牌同时存在时配置互不影响。

用户报告不是自动探针证据，不把其范围扩展到未测试场景。
最后定向回归：model contribution 96、Chat 73；typecheck、默认产品
18 扩展 build、diff-check 均通过。另有 Python 323 与 Pi 扩展 12 项
此前定向证据，详见 takeover-progress.md；不是此检查点全仓重验。

## 已知缺陷

Profile 逆向应用失败：14:37:03 UTC journal unknown，原因
`Native provider restoration is unproven`。保留失败草稿，不自动重发、不清
needs_recovery。真实 Pi 适配器无推理逆向注册探针通过，故不能简单断言
“Pi 原生不支持”；需定位生产绑定/核对环节。

## 源码保存口径

保存当前产品源码、测试、计划文档，包括此前继承的未提交实现；这只是
可恢复快照，不代表所有继承改动已经审阅通过。明确排除他属
`docs/ui-preview/01-empty.png`、`.zcodeignore`；不提交 key.txt、运行数据、
依赖、构建产物、安装候选或 .cleanup-evidence。截图/安装产物留在原位置。
恢复时先比对本地改动，禁止 reset --hard 或自动覆盖用户后续工作。

## 环境依赖（不在 Git 快照内）

- 数据根 `/home/maoqh/.ordessa`；系统密钥环与登录不复制。
- Pi：`/opt/ordessa/harnesses/profile-pi-startup-admission-v2/artifacts`。
- Codex：`/opt/ordessa/harnesses/profile-codex-catalog-fast-off-v6/artifacts`。
- Claude：`/opt/ordessa/harnesses/profile-claude-provider-restoration/artifacts`。
- 开发 Python runtime `.cleanup-evidence/product-dev-runtime-URGO6TDv`。
- 当前正常应用 launcher 716827 / Electron 716895 / Server 716943；
  loopback 35261，exec session 91483。此为时间点记录，不据旧 PID 杀进程。
- 未授权夜间执行、真实模型调用、用户数据修改或服务重启。

夜间范围提案见 `night-proposal-20261002.md`；用户确认后才执行。
