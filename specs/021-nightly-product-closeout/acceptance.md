# acceptance.md — 021 夜间产品验收合同

今晚唯一验收口径。所有条目以 checkbox 维护；状态：`[ ]` 未验证 / `[x]` PASS（证据进
evidence.md）/ `[~]` 部分通过（附说明与 ledger 引用）/ `N/A` 不适用（附理由）。
禁止为勾选而 fake green（见 §铁律）。

---

## P0 · Packaging / Installation / Launch

### 构建
- [ ] 从正常 checkout 可执行正式构建（`npm ci` → build 链）。
- [ ] dependency install 路径正常（npm 从 lockfile 安装；Python 侧按 baseline 锁文件）。
- [ ] Desktop build 成功（`npm run build`）。
- [ ] Backend/Server 所需内容进入最终产品（bundled server 正常启动或正确连接）。
- [ ] 必需插件进入产品 assembly（`products/desktop`）。
- [ ] `npm run build:deb` 成功。
- [ ] 生成 amd64 Linux deb。
- [ ] deb 不依赖开发 checkout 中的绝对路径。
- [ ] deb 不依赖用户手工复制文件。
- [ ] 不能只有 dev mode 可用。

### 安装（真实 Ubuntu Linux）
- [ ] 安装成功，无致命 package dependency 错误。
- [ ] desktop entry 正常；应用名称正常。
- [ ] 图标/启动项至少不妨碍使用。
- [ ] 普通用户可运行应用本体。

### 启动（必须从安装后的应用启动，非源码 dev server）
- [ ] Electron 主窗口出现；renderer 正常。
- [ ] Workbench 正常。
- [ ] bundled extensions/plugins 正常发现。
- [ ] Ordessa Server/backend 正常启动或正确连接；local token/connection 正常。
- [ ] 不需要用户额外开 terminal 启 backend。
- [ ] 无白屏 / 无无限 loading / 无启动即 crash。

### 生命周期
- [ ] 关闭后无明显异常残留进程。
- [ ] 再次启动正常。
- [ ] 不因旧端口、锁文件、token、data-root 冲突而失败。

## P1 · 普通 Harness Desktop 核心体验

### Project
- [ ] 添加/选择本地目录；Project 出现在 UI；可切换。
- [ ] 新 Session 正确绑定 project cwd；Agent 实际工作目录正确。
- 今晚不新增：remote / container / multi-root workspace、新 workspace 抽象（除非已存在只是接通）。

### Session
- [ ] 在 Project 中创建 Session；Session 出现在列表；可切换。
- [ ] 输入任务 → Harness 真正收到任务。
- [ ] 有明确 running / completed / failed 状态。

### Harness
- [ ] 能看到当前支持的 Harness；roster 来自既有 registry/capability 机制；通用 UI 不手写品牌列表。
- [ ] 未安装 Harness 明确 unavailable；executable detection 失败不使应用崩溃。
- [ ] 未登录、额度不足、外部服务错误诚实显示。

### 真实 Harness E2E
- [ ] A. 至少一个真实 Harness 完整任务 E2E PASS。
- [ ] B. 第二个不同 Harness 至少完成：real executable → real session → real prompt → real streaming。
  - 若第二 Harness 因用户环境（未认证/无额度/外部服务不可用）不能完整跑完，必须证明 Ordessa 已正确走到 external blocker 边界（discovery → launch config → process spawn → protocol init → external refusal）。
  - 环境允许时尽量让两个以上 Harness 完整 E2E PASS。

## Streaming / Conversation UI
- [ ] 用户消息正常。
- [ ] Agent 文本增量流式显示（非整轮一次性显示）；chunk 不重复；顺序稳定。
- [ ] 完成后不残留 loading。
- [ ] thinking/status：Harness 支持则正确显示；不支持则不伪造。

## Tool Call UI
- [ ] 至少真实执行一次 tool call。
- [ ] Tool Call 独立 UI：工具名可见；参数/输入合理显示。
- [ ] running / success / failure 状态正确；Tool Result 正确关联。
- [ ] 不生成重复卡片；tool call 与普通文本顺序合理。

## Permission / Approval

### Dynamic Permission Modes
- [ ] 权限模式来自 Harness capability/native support；不同 Harness 可展示不同模式。
- [ ] 不支持的模式不硬显示；Workbench 不写死某 Harness 品牌模式。

### Approval（至少完整跑一次）
`Agent 请求受控操作 → Ordessa 收到 approval → UI 显示 → Allow 或 Deny → decision 返回 Harness → Harness 继续/拒绝`
- [ ] approval card 出现且信息可理解。
- [ ] Allow 有效；Deny 有效。
- [ ] 不会发错 Session；审批后任务继续。
- [ ] 不支持 approval 的 Harness 不伪装。

## Profile

Profile = 某 Harness 的可复用预存配置。用户至少可以：创建 / 编辑 / 删除或停用 /
命名 / 绑定 Harness / 在 Session 中选择。

- [ ] 上述 6 个基本操作可用。
- [ ] 配置能力不只理解成 model/provider；仓库已有且目标 Harness 支持时应能承载对应 facet
  （provider/model、permission、instruction/prompt、MCP、Skill、runtime preferences、
  memory、hooks/extensions、其他现存 facet）。
- [ ] facet 来自 owning plugin；Profile 不重新实现这些领域。
- [ ] unsupported 必须诚实；不静默丢用户配置。

**Profile → Harness 是硬验收**（选择 Profile 启动 Session 后）：
- [ ] Harness 正确；Profile 配置正确 compile/project。
- [ ] Harness runtime 实际收到配置。
- [ ] Session override 不污染 Profile；两个 Profile 不串数据。
- [ ] 至少一个真实 Profile 完成实际 Session 启动。

## Skill

今晚不重做 Skill，目标是**接通**。
- [ ] 用户可看到/管理已有 Skill 资产。
- [ ] Skill 能进入 Profile 或对应 Session 配置；选择后进入有效 runtime 配置。
- [ ] 支持 Skill 的 Harness 得到正确 materialize/project；不支持的不伪装。
- [ ] 两 Session 不串 Skill。
- [ ] 至少一个最小 Skill 验证：不能只证明 database 存了——必须证明最终 runtime
  projection / harness input 确实含有它。

## MCP

做一个**本地可控 MCP smoke**（优先不依赖外部 API 的简单 stdio MCP server）。
- [ ] 能创建/导入 MCP 配置；能加入 Profile 或 Session。
- [ ] 正确投影给 Harness；Harness 实际发现 MCP。
- [ ] 至少一个 MCP tool 可以调用；Tool Call/Result 经过现有 Conversation UI。
- [ ] MCP 启动失败有明确错误；不支持 MCP 的 Harness 不伪装支持。
- 最好验证整链：Profile → MCP → Harness → Tool → Conversation UI。

## 其他已有配置能力

对已存在的：Prompts、Instructions、Model Provider、Runtime Preferences、Memory、
Hooks、Extensions、Subagents、LSP、Command Templates 及其他 assets：
- [ ] 不重新设计；不要求全部真实模型 E2E。
- [ ] 确认默认产品 assembly 无明显遗漏必要能力。
- [ ] contract/facet/contribution 可被发现；重要配置完成 compile/projection 验证。
- [ ] 禁止 UI"保存成功"但 runtime 完全不消费。
- 已有能力无产品入口时：属普通 Harness Desktop 必需 → 修；属增强 → 入 backlog。

## Persistence

重启 Ordessa 后至少：
- [ ] Project 仍存在；Profile 仍存在；Profile 配置仍存在。
- [ ] Session history 可找到；已完成会话可显示。
- [ ] 旧数据不导致启动 crash。
- 今晚不强制：运行中 Harness 在应用退出后继续后台执行。若无 runtime resume/reconnect，
  重启后可将旧 running Session 标记 interrupted/stopped——但不能假装仍然 running。

## Failure / Degraded Behaviour

以下单个失败不能拖垮整个应用：Harness executable 不存在 / 未登录 / 额度耗尽 /
MCP server 无法启动 / Skill 配置错误 / 某 Profile facet 不支持当前 Harness /
单个 plugin activation 失败 / 单 Session 失败。
- [ ] 每种都给明确错误；其他独立能力仍可用。
- [ ] 不 fake success；不 silent fallback 成完全不同的行为。

## Product Assembly（重点排查"代码存在，但产品没装进去"）
- [ ] `products/desktop` 默认 assembly 完整。
- [ ] 默认用户无需自己写 extensions.json 才获得核心产品。
- [ ] frontend extensions 正确 bundle；backend plugins 正确安装/注册。
- [ ] Profile facet providers 可发现；Harness registry 可发现；Asset plugins 可发现。
- [ ] packaging 含必要 runtime；deb 不依赖 repo-relative path。

## Multi-Harness

Ordessa 不能只是一个 Codex Desktop。
- [ ] 两个不同 Harness 使用同一 Session UI。
- [ ] 主流程无品牌专属硬编码；capability 改变 UI 行为。
- [ ] Harness A 配置不污染 Harness B；Profile A/Harness A 与 Profile B/Harness B 可共存。
- [ ] Session 切换不串事件；approval/stream/tool 有正确 session identity。

## Automated Gates

最终 candidate 至少运行 relevant：
- [ ] typecheck
- [ ] Desktop build
- [ ] root/frontend tests（`npm test` 聚合）
- [ ] extension/plugin boundary tests
- [ ] ACP connector streaming/tools tests（`tests/acp-connector` rig）
- [ ] project binding tests
- [ ] packaging deb contract tests（`test:packaging`）
- [ ] Electron/headless smoke（`test:agent-shell` / `test:electron`）
- [ ] 本轮修改模块局部 tests（Python 侧：pacthold / harness / server 相关套件）

Known-red / inherited-red 规则：
- 不通过删断言变绿；不通过 skip 藏起来。
- 与仓库登记 baseline 对比（`docs/known-issues.md`、`docs/baseline.md`、
  `specs/011-c0-foundation-harness/report.md`）。
- 只有**新增** regression 属今晚 blocker；每个新增 failure 必须有 disposition（进 ledger.md）。

## Real Product > Test Count

禁止"500 tests passed，因此完成"。最终权威路径：
```
installed deb → normal launch → project → session → Harness/Profile
→ real prompt → streaming → tool call → permission(如支持) → completion
```

## Architecture（第二优先级，产品稳定后才做）

目标形态：Workbench=通用前端平台；Pacthold=通用执行/治理内核；
Harness/Chat/Profile/Skill/MCP=业务插件；插件间经 public API/SDK/contract/
contribution/extension point 协作。

底线（今晚必须保持）：
- [ ] 不新增 plugin → sibling 私有实现 import。
- [ ] 不新增 plugin → host internals import。
- [ ] 不新增 generic host 中品牌硬编码。
- [ ] 不把 Harness 专属逻辑塞入 Workbench/Pacthold。
- [ ] boundary tests 保持绿色。
- [ ] 新跨域能力优先走既有 contract。

今晚明确不作为必须完成：全面退休 runtime-compat / 大规模 storage ownership
搬迁 / 重写 Server/Pacthold / 大规模 API redesign / 数千行纯架构搬家——除非直接阻塞 P0/P1。

## Morning Candidate（floor，不是 ceiling）

只有至少同时满足以下 18 条，才允许写 `MORNING_CANDIDATE = YES`：

1. [ ] deb build 成功
2. [ ] deb 安装成功
3. [ ] installed Ordessa 正常启动
4. [ ] Project/Session 可用
5. [ ] 至少一个真实 Harness 完整任务成功
6. [ ] 第二 Harness 有真实 multi-harness 证据
7. [ ] streaming 正常
8. [ ] tool call UI 正常
9. [ ] 支持 approval 的 Harness 至少一次真实 approval
10. [ ] Profile 可创建并用于真实 Session
11. [ ] Profile 配置实际进入 runtime
12. [ ] Skill 产品级 smoke
13. [ ] MCP 产品级 smoke
14. [ ] 核心 persistence 正常
15. [ ] 无新增未解释 P0/P1 regression
16. [ ] candidate commit 明确
17. [ ] deb 明确（文件名 + SHA256）
18. [ ] report 完整（final-report.md 填成）

达成后：立即形成 C-MC1 绿色 checkpoint，然后**继续**（见 continuous-operation.md §Morning Candidate 之后）。

## 铁律（禁止 Fake Green）

严格禁止：删除失败断言 / 无理由 skip / swallow exception / 把 unsupported 返回
success / 假的 UI success state / fixture 替代真实 installed-product smoke /
test pass 就声明真实产品 pass / 手工改全局环境后假装 deb 自包含 / 为让包装通过
复制第二套 business logic / hardcode 某 Harness 到 generic host。
