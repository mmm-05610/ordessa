# 2026-09-30 接手检查点：启动接缝与 Profile 管理

状态：部分实现，**不是完整 Harness Desktop 验收通过**。
所有改动在 `nightly/021-ordessa-product-closeout`，根工作树保持 main。
未合并、未 push、未启停既有用户服务、未重建 deb。三品牌后端真实聊天已通过；Codex Desktop 已通过 Profile 首发与同会话下一轮切换，两条真实回复。完整三品牌 UI/发行验收仍未完成。

## 最新验证（2026-10-01，Harness 差异归属收口）

- 按用户裁定：Profile 保存/合并配置，model-provider 管理和解析供应商资源，所有原生品牌差异归 Harness。已把产品接线中的 Pi 目录需求、Codex 登录启动参数/账号创建与三品牌安装路由校验迁入 `ordessa_harness.configuration.model.backend`。它不导入 Profile 或 model-provider；产品仍负责连接服务、资源版本校验与会话操作身份，不负责原生策略。
- Profile 生产配置端口删除隐含 Pi 默认值和内置品牌枚举，未显式声明路由时拒绝；受控新品牌可消费相同中性端口。model-provider 的配置端口删除三品牌默认名单，按当前 Harness 的实际 facet 声明发现能力；可选组合名单只能收窄，不能制造未注册能力。
- 先红后绿：三个产品 AST 边界测试原先各自发现真实品牌泄漏；model-provider 三个反例复现未注册 Codex 被宣告、新品牌被遗漏、显式过滤表误当能力声明。没有跳过、删除受保护断言或靠返回固定成功修复。
- 独立复跑：model-provider server **198P**；Harness 新边界/服务测试 + products/server **153P**（其中产品 **145P**、Harness **8P**），exit 0。`git diff --check` 通过。这些是定向回归，不是全仓发行门禁。
- 迁移后再次使用真实 Electron、已验证独立开发 runtime 与 Codex 原生账号跑 `--during-output --native-tool`：四个成功标记齐备，首发 completed、只读原生工具可见、输出期间选择未提前应用、第二轮同 SessionRef 且配置摘要改变并 completed；最多两条短提示。没有改全局配置/登录/系统资产，没有启停用户服务。
- **仍未完成**：生产已有历史跨 provider 切换。当前凭据绑定仍只允许原准备认证路由，原生恢复接口尚未连接到 Profile 发送应用链；不能把本次职责迁移或同 provider 模型切换记作完成此项。旧 UI preview 夹具与完整三品牌 UI/发行包门禁也仍待收口。

## 前一检查点（2026-10-01，原生权限边界与真实 Desktop Profile 发送）

- 用户明确裁定：Harness 自己决定原生工具权限；Ordessa 默认只维护认证、通道归属与生命周期。外部 permission/sandbox 插件不得成为普通聊天必备许可。默认 ACP relay 选择原生模式，产品不再自动注入 PermissionsAcpAdmission；显式外部模式仍保留原有单次许可反例。原生模式不宣告外部授权端口 ready，也不自动批准原生权限请求。
- 真实 Electron DOM + 实际 WS relay：连接 Codex、选择项目和 Profile、首条发送、真实非空回复 completed；同一会话选另一 Profile（gpt-5.5 → gpt-5.6-sol），第二条发送 completed。两轮均有 harness-api-confirmed 回执，configDigest 改变、SessionRef 相同、可见会话相同。另跑 --during-output：第一轮 run=running 时选择，当前轮正常完成，第二次发送前应用次数仍为 1，第二轮才应用；不宣称点击瞬间恰有流式 token。每次最多两条短消息；无未知结果自动重试。
- 探针第一次双轮检查漏收 beginTurnApplication 直接返回的回执，故报失败；修正收集路径后在新独立测试数据根复跑通过。此前失败记录保留，不伪造成功。成功根在 Electron 正常退出后精确清理，不碰用户数据/登录/系统资产。
- 定向回归：Server relay + products/server **165P**（新增同 App WS 原生发送/未认证/未知通道/外来会话拒绝、原生选项与模式防误注入）；ACP **63P**；Profile Chat **45P**；typecheck exit 0。未跳过/删掉外部模式反例。首次三个契约测试的红来自构造器未提供原生模式，不冒称完整生产行为先红后绿。
- 尚待：实际全局预设/逐项覆盖/失败草稿/未知结果场景、已有历史跨 provider restart/resume、多品牌完整 UI 与全仓回归/发行包。固定 TODO 不扩张、不把 model-only 切换当跨 provider 已完成。
- --native-tool 另验：实际 Codex 在自有测试项目执行只读 pwd，原生工具卡片出现在 Chat，当前轮 completed；没有外部 permit 请求、没有自动批准原生权限请求、没有读写用户文件。仍是两条短消息的同会话切换探针，四个必需成功标记均出现。
- 完整 npm test 实跑 **31/39 suites green**，不能记全绿：server-bridge 使用旧 .venv 缺 Profile 包；六组 Electron 使用未指定 bundled runtime 的环境而失败；旧 UI preview 是退役插件/DOM/IPC 的真实夹具破损。指定独立集成 Python 后 server-bridge **68P**；指定已验证开发 bundled runtime 后 Electron **6/7** 通过，仍只有旧 UI preview 失败。构建 18 扩展、typecheck 与所有其他发现的 workspace/产品/ACP rig suites 通过。没有修改断言或 skip。旧预览截图已有脏改动，不纳入提交；后续应使用独立输出路径。

## 已解决阻塞（2026-10-01，实际 Desktop Profile 选择→发送，以下为修复前记录）

- 新增产品所有的可重跑 Electron DOM 探针 `products/desktop/probe-profile-ui.mjs`、driver，以及无模型种子脚本。独立项目/数据根与实际安装资产；保留真实 HOME 让 Harness 读取 Ordessa 自有原生账号，不复制登录。使用现有 smoke seam，不改 host。普通浏览器不能代替 Electron 原生 bridge，故 webapp-testing 的实际页面检查在 Electron DOM 上执行。
- 实际页面完成连接 ACP Codex、项目选择、Profile 选择及点击发送。创建前准备、canonical 注册、selectForSession、beginTurnApplication、inspectSessionConfig 均返回成功；真实账本 settled，应用 journal confirmed，receipt=harness-api-confirmed。最后一轮相关应用请求约 44–129ms，非 15s wire 超时。
- **发送失败，未报成功**：实际 UI 留在 draft，显示发送结果未知。隔离定位表明 Profile guard 返回 ready、Chat gateway 已调用，失败发生在 ACP prepared-send 的 prompt promise；没有自动重发任何未知 attempt。固定 TODO 的 UI 项保持未完成。
- 源码接缝：`apps/server/.../acp_admission.py:admit_client_frame` 要求每个 session/prompt 先有匹配的 C5 submission permit；现有 Chat 普通/首条发送走 `startTurn`，未走 `authorizeSubmission`。另外当前 `PermissionsAcpAdmission` 对无 commandId 的普通消息以 PERMISSION_UNKNOWN_TOOL 拒绝。后端探针直接走 transport，不能证明 WS relay + UI 准入，因此之前的后端聊天证据不升级为 Desktop 证据。
- 此时曾提出普通消息准入方案；用户随后明确拒绝默认外部许可前置，按上方原生权限边界实施。未凭空补 commandId/configurationDigest，认证和通道归属围栏保留。
- 所有临时生产诊断已移除并重建；未改登录/系统资产/主树/既有服务。失败测试数据仅在 ignored `.cleanup-evidence/ordessa-profile-ui-*`（另有一次跨设备保留失败的自有 `/tmp/ordessa-profile-ui-gkdwiW`），作为诊断证据，不纳入 git。已退出自有 Electron，未做用户服务恢复。

## 最新验证（2026-10-01，已安装官方 Codex Profile/C4 与真实对话）

- 用户成功执行 repair，正式发布 `/opt/ordessa/harnesses/profile-codex-managed/artifacts`；资产摘要不变。已安装版 ACP 无模型复验通过。产品开发启动器及 mount 探针默认 Codex 根已切到此正式资产；Pi/Claude/普通资产不变。
- 新增 `products/server/scripts/probe-installed-codex-managed-profile.py`，真实产品装配/wire/SQLite/Profile/canonical owner/generation/C4，两个官方会话与一个无官方登录 API 会话。首次应用均有 C4 receipt；全局官方 Profile 改为 gpt-5.6-sol，仅 A 在下轮应用，B 和 API 保留 gpt-5.5，三个 native IDs 独立。无模型模式 `new=3/prompt=0/本地API HTTP=0` 通过。
- 已按用户授权另跑官方真实聊天模式：A 首轮 gpt-5.5、更新 Profile 后下轮 gpt-5.6-sol，恰两条短 prompt，均 end_turn 且非空文本；B/API 配置未变化；本地 API 网关零请求（不代表官方推理零网络）。两次探针均释放自有通道和停止临时产品，未改登录。**这是后端实际产品聊天，不冒称 Desktop UI 发送验收。**
- model-provider 设置页提供中性原生账号选择，官方路线保存时无 credential/endpoint；编辑保留该模式和其他控制字段，API Key 不进 React state、不自动登录/探测。两条 UI 反例先红后绿，设置页 37P。React skill 约束用于事件内显式操作与 ref 请求身份保留，未新增自动副作用。
- 本轮产品 Server 140P，ACP 63P，Profile Chat 45P，准备 29P，资源解析 25P，Harness 账号/选择/编译 25P（重叠范围不累加）；typecheck/build exit 0，18 扩展。完整 Desktop mount-only ready/rootMounted/nodeAbsent=true、errors=[]、prompt=0。开发运行根为 `.cleanup-evidence/product-dev-runtime-URGO6TDv`，真实 Go 1.24.13 重建桥摘要 `714044a5b490a53d5fa89aade993c496e5fa3a5f7c614b4465c4990575185cbd`；不是 deb 发行验收。
- 旧 /tmp 测试环境已不存在，重建独立 `.cleanup-evidence/product-integration-venv`，未重指共享 .venv。该开发环境按各包 pyproject 安装，不替代发行闭包锁定。证据 `evidence/codex-managed-installed-product-20261001.json`。尚未完成项：已有历史跨 provider restart/resume、完整 UI 发送与操作场景、全仓回归/发行包；固定 TODO 不扩张。

## 前次验证（2026-10-01，Profile 启动前认证选择，候选待安装）

- **安装失败已定位并修复**：执行者漏同步安装校验器的 extension 精确字段集，新增 managedAccountScope 被旧五字段规则拒绝。旧脚本没有完成发布，正式目录仍不存在，失败 staging 为 `/opt/ordessa/harnesses/.codex-managed-install-HqTKQimG`。新增反例先红后绿；修复只允许 Codex 的显式 true，false/string/null、其他品牌及未知字段均拒绝；安装边界 **22P**。用修正校验器对该实际 root staging 全树只读校验已通过，资产摘要不变。请勿重用旧 /tmp 安装脚本，改用工作树 `.cleanup-evidence/install-codex-managed-profile-repair.sh`：仅更新该 staging 的校验器，完整核验后原子发布，不再次复制资产、不动旧版本/登录。校验器新 pin `e13db8892e49445dde88356182618a2344c33cb571bfdcaade5ddad4d1b86e67`。尚待用户 sudo 完成发布。

- Chat 将已保存 Profile 引用传到 prepareSession，再进入 `acp.channel.open`；后端产品装配解析当前 Profile/model-provider 配置，由 Harness 选择官方账号或私有 API 实例。客户端不传账号目录、token 或应用证明。启动与首次创建之间 Profile/供应商记录变化会拒绝；同一保留 attempt 不得更换 Profile。
- model-provider 增加中性的显式 `authentication: managed-account` 配置选择；它不解释品牌差异。Harness 当前只允许 Codex/openai/responses、无 endpoint/credential 的官方路线。官方账号查询与刷新仍全部交给原生 Codex，未实现 OAuth/token 复制。
- 增强 ACP 新增官方初始模型准备及真实 thread 路由回读；官方实例拒绝会话客户端的认证、供应商改写和注销入口，API 实例不使用官方账号目录。安装清单显式声明 managedAccountScope，旧资产不得冒充该能力。
- 最新完整摘要 `sha256:1ee5358b82e4727051158eaf61ebe5ae12ec1a4e55105e8acb5ffd5682837dd5`。实际候选 ACP 同时验证官方已登录/API 未登录，官方 gpt-5.5 原生创建与配置回读成功，session/new=1、prompt/modelCalls=0；自有进程已关闭。**这是适配器实际证据，尚不是生产 Profile/C4 或 Desktop 实际发送验收。**
- 定向验证：products/server **140P**；Harness 相关文件逐文件独立 Python 进程合计 **148P**；Profile preparation/model resolver/channel selection **60P**（与前述有重叠，不累加）；ACP **63P**；native-profile Node **40P**；typecheck/build exit 0，18 扩展。组合 Python 跑法曾报 DB 初始化/临时夹具错误，拆分后通过；未复现旧基线前不擅称继承红或全套通过。沙箱偶发 /tmp 挂载配额错误，只读诊断显示磁盘尚有空间，未删除用户临时文件。
- 锁定候选仍在开发树，旧 /opt 资产未变。已生成加法式安装脚本 `/tmp/ordessa-install-codex-managed-profile-verified.sh`，目的地 `/opt/ordessa/harnesses/profile-codex-managed`，不覆盖旧资产或登录。需用户执行 sudo 后继续已安装资产与实际产品链验证。当前还没有把默认产品切到不存在的新安装根。
- 证据：`evidence/codex-managed-profile-20261001.json`。固定 TODO 第 6 项继续推进但未完成，第 7 项未完成；不新增阶段，不更改 main/host，不动他属截图。

## 前次验证（2026-10-01，Codex 原生账号接缝）

- Ordessa 专用浏览器登录成功，独立 CLI 状态及原生 app-server account/read 均确认已登录，使用系统密钥环，不读取/复制用户原有全局登录。
- 新增 Harness 内 CodexManagedAccount：仅 initialize/account/read，原生负责续期；不导出 token、不实现 OAuth、不复制凭据、不自动弹浏览器。13 个新测试；连同 Codex 既有定向与产品 Server 测试 **168/168**，入口隔离 Node **4/4**。实际专用账号经新封装 refresh=True 查询 exit 0，modelCalls=0。该封装尚未加入默认产品工厂，不报会话认证已接入。
- 版本阻塞：已安装 Codex 0.147.0 自行生成的 LoginAccountParams schema 将 chatgptAuthTokens 标记为“FOR OPENAI INTERNAL USE ONLY - DO NOT USE”，与最新网页仅称实验性的描述不同。先前推荐外部 token 代理的方案不作为可执行接线，未读取/导出密钥环 token，未调用该接口。
- 已验证原生替代路线的有限事实：两个自有 app-server 同时使用 Ordessa 账号 CODEX_HOME，分别以 -c 设置 low/high reasoning；account/read 均 authenticated=true，config/read 均匹配各自覆盖，modelCalls=0。未创建 thread、未测试资源文件/Skills/MCP 隔离、未测试 token 过期并发，不证明完整多会话隔离。探针均退出。
- **决策已收口**：用户要求测试后可行即通过，暂只维护一个官方账号；每个 Codex 进程配置独立，允许官方登录和第三方 API 进程并存。混合实测已通过，详见文末最新记录。官方账号目录只供官方认证路线，API 路线保持实例 CODEX_HOME。现有入口尚未接入官方分支，守卫仍保留；决策通过不等于生产接线完成。
- 本轮继续：Harness transport 新增后端显式 `codex_account_directory`，不接受继承环境或客户端 launch environment 选择账号；增强资产烘入品牌、严格校验独立私有账号目录。官方 native 子进程强制 keyring，HOME/XDG 仍为实例目录；API 的 CODEX_HOME 仍为实例目录。移除继承认证变量及原始 RPC trace，官方 ACP 禁止改写/取消登录/注销共享账号。
- 锁定源码候选已构建、完整摘要 `sha256:8dbe3e60ae5e57bb054706271ad25e92ce1be343fa25fa46ebaf7fe8a20b6d8f`。真实候选 ACP 官方/无账号 API 同时 initialize/status，通过有效 API-key 登录拒绝与两条注销拒绝并复查账号不变；modelCalls=0、sessionCreations=0。混合配置探针也通过。**候选未安装、默认产品尚未选择官方分支、Profile/Chat 真实链仍未验收**；不把开发候选视为 root 管理生产资产。
- 本轮反例先红后绿：入口账号隔离/认证环境继承、transport 显式选择。Python Harness+products/server 定向 **213P**，native-profile Node **38P**，安装入口 **22P**，diff-check 通过。只改 Harness 与证据文档，未改 host/main、未动他属截图/已安装资产/用户服务。沿用现有 Spec Kit 和增量验收纪律，单会话实施，不新建派工单/工作树。
- 固定 TODO 第 6 项仍未完成；其余未验收项不变。下一接缝是把 Profile 的认证路线选择提前到通道创建前，而非先启动 API 子进程再借 token 切换；不得把所有 Codex 通道默认指向账号目录。下文为按时间保留的历史记录，不以历史未开始/旧资产/旧门禁读数覆盖本节状态。

## 前次验证（2026-10-01，Pi provider 安装完成，历史状态）

- 用户已授权真实聊天与配置切换验收。实际调用尚未开始：默认 `~/.ordessa` 只有 backups/logs/secrets，没有业务数据库或已登记模型供应商；运行环境未提供 OpenAI/Anthropic/Pi/Ordessa API 配置变量。三品牌全局登录文件存在（仅检查文件存在，未读取、复制或验证登录有效性）。下一步须确定使用现有官方登录还是指定 API 供应商，以及测试费用范围；授权不等于接入信息已具备，不可擅自将全局凭据复制进独立实例。

- 用户完成新增 Pi provider 系统资产安装，路径 `/opt/ordessa/harnesses/profile-pi-provider/artifacts/pi-profile-runtime`；旧资产和全局配置未覆写。
- 主代理通过真实已安装三品牌产品探针：真实产品装配、wire、SQLite 账本、Profile、canonical owner/generation、C4、系统密钥环。每品牌两条独立会话，首次配置确认后更新全局模型、只在 A 下一轮应用，B 仍保留原模型；Codex `gpt-5.6-sol/gpt-5.5`、Claude `haiku/sonnet`、Pi `synthetic-provider/second/first`，native IDs 分离。`new=6/prompt=0/HTTP=0`，exit 0。通道、精确合成密钥、自有产品均已清理。不是 UI 发送、真实推理或已有历史跨供应商恢复证据。
- 产品原生启动器与安装探针的默认增强资产根改为上述 Pi 根和 `/opt/ordessa/harnesses/profile-native/artifacts`，仍完整验证来源与实例隔离、保留环境变量覆盖及显式普通 Pi 路线。未改 host；根 `npm dev` 仍是原隔离预览，完整产品入口是 `node products/desktop/run-native.mjs`，两者不能混称。
- 无资产环境变量覆盖的完整 Desktop 挂载探针 exit 0：`ready=true/rootMounted=true/errors=[]`、Chat/Skills/Sessions、`prompt=0`。这是 mount-only，不保证全部异步业务/UI 提交完成。
- Product native preparation 回归 **27/27**、typecheck exit 0。扩展 Electron 同根重启失败已复现并修复：测试驱动 `app.exit()` 绕开 before-quit，改用 `app.quit()` 执行宿主清理；调用者仍强制检查 ready/nodeAbsent，不丢掉旧失败判定。修复前双启动第二次 Server 退出 1、clean=false；修复后两次 errors=[]、clean=true。扩展九场景与 UI 服务五场景均 exit 0，host digest 未变，额外钉住每次 clean 标记。
- Shell 测试迁到真实 Chat DOM/导航，不要求单视图出现标签条。缺少 handoff 用刻意缺失的 runtime 复现（空 origin 现在会被宿主自动补齐，不再等于缺席）；仍断言连接器拒绝、无伪造连接、无内嵌连接 UI。hello-only 对端使用从 shipping 清单核对的 shell 组合，不启用需要业务 API 的 Skills/Profile 等插件，严格保留两次认证 hello、零其它请求；全产品装配另由 installed probe 验证。该定向回归 exit 0，不冒称原 full manifest 测试全绿。
- 旧 visual-preview 仍引用已退役 `ordessa.agent-conversation`、旧 DOM 和缺失 IPC；尚未迁移，完整根回归未收口。已有历史跨 provider 恢复、用户授权真实聊天仍未完成。

## 前次读数（2026-10-01，首次准备并行集成；以下保留历史状态）

- Pi 新 provider/API Key 准备链已接入 Harness 和产品装配，host/Pacthold 未改。私有实例使用锁定上游 ModelRuntime 的内存注册/runtime-key 接口（避免普通配置字符串的命令解释），只做 offline refresh。初始模型目录按资源修订围栏取值；C4 仍要求真实 owner/generation 与启动后的独立读回。已有无凭据 model-only 路径保持原样。
- 主代理当前定向回归：Product/Harness/model/owner **303P**，Profile **195P**，Pi Node **60P**；新增准备、未知查询、竞态、模型路由、凭据守卫反例。真实 ACP 首次启动抓出自定义查询缺 parser，已补且强化注册夹具；不是用夹具结果代替真实启动。
- 最终构建/来源门分别复跑 **12P / 22P**。最初 /tmp 大文件反例被 -122 提前截断；之后混跑并设置 NVMe TMPDIR 又破坏了来源测试对 /tmp 的夹具假设（32P/2F），没有改断言，改为仅 builder 使用 NVMe TMPDIR、来源套件保留原环境后两者全绿。Codex/Claude 已安装真实产品探针在 Pi 源码修改后又复跑成功（4 次 new、0 prompt、0 HTTP，精确清理）。这些定向绿不覆盖此前登记的 4 项 Electron 集成失败或真实聊天验收。
- Pi 真实开发候选探针通过：两个独立进程，供应商名相同、端点不同；模型读回 `ordessa-probe/second` / `ordessa-probe/first`，零持久化凭据、零 models.json、prompt=0、HTTP=0。上游可以创建空 auth.json，这不等于保存凭据。候选 `/home/maoqh/ordessa-builds/pi-initial-provider-runtime-20261001-r2`，treeDigest `sha256:48ca796468d254d2e13b3bc135b9b7609232fcb415c47b08d201801cc19df0ae`，15463 entries / 64935823 bytes。**尚未安装/尚未 Pi 完整产品确认**。安装脚本 `/tmp/ordessa-install-pi-provider-verified.sh`，仅新建 `/opt/ordessa/harnesses/profile-pi-provider`，原资产和默认启动路径不变。
- 构建环境记录：/tmp 两次复制返回 -122，仓内输出被既有策略拒绝；没有放宽构建策略，换到仓外 NVMe 路径后成功。首次候选保留用于失败复现，r2 是拟安装候选。
- 用户已安装增强 Codex/Claude 到 `/opt/ordessa/harnesses/profile-native/artifacts`，前后完整校验均通过。主代理真实宿主身份复核完整 Desktop 增强清单：ready/rootMounted=true、errors=[]、Chat/Skills/Sessions，prompt=0。不是用户真实聊天验收。
- 新的实际产品验证不再使用 ledger/installation 夹具：同一原生产品、真实 wire/账本/Profile/C4/已安装资产/系统密钥环；Codex 与 Claude 每品牌两条独立会话，首次准备→session/new→canonical 登记→C4 确认，全局 Profile 更新后只应用会话 A，B 配置保持。实际读回分别 `gpt-5.6-sol/gpt-5.5`、`haiku/sonnet`，native ID 不同；session/new=4、prompt=0、供应商 HTTP=0。所有本次通道已释放、合成 keyring 条目精确删除、临时产品停止。探针已固化到 `products/server/scripts/probe-installed-profile.py` 并复跑成功；可在 Pi 候选安装后显式设置 `ORDESSA_PROBE_PI_ARTIFACT_ROOT` 验证三品牌。仍不证明历史跨 provider resume 或 UI 提交。
- 继续收口 API Key 输入链：已冻结 model-provider 自有 import/query 入口，操作预留先于密钥库效果，未知结果只查询；前后端仍在各自目录完成测试，尚不记为交付。主代理复跑当前 products/server 与 native credential catalogue：**140P**。Linux store 新增内存字节导入，无明文临时文件；真实系统内存导入、独立进程读取、删除合成条目已通过。
- 发现并补齐两个此前受控夹具未暴露的生产缺口：原生 Harness 目录未声明 api-key 凭据类型；provider wire 保存未传协议/端点给既有解析器。目录声明已补且不改变原始目录，wire/UI 正在同批对齐。前端操作身份必须匹配后端 `key-import:<requestId>`，不能以夹具中的不同格式冒充真实成功。这些不改 host，也不代表 Pi 新 provider 启动已完成。
- 主代理实际系统验证：真实 GNOME store + model-provider wire import/query + providerModels.create + ProfileModelChoiceResolver + 后端凭据读取全链通过；合成 Key、临时数据根、loopback 未监听端点，零模型调用，精确删除本次密钥环条目。首次探针暴露手工模型缺必填 displayName，已交前端补齐；另一次不可解析 synthetic.invalid 端点被既有校验诚实拒绝，最终使用 loopback 地址成功，未放宽校验。探针 `/tmp/ordessa-key-entry-product-probe.py`；不是完整 Electron 操作或原生 Agent 应用确认。
- 两条执行线现已停止写入：后端最终 **194P**、前端 **35P**（均主代理独立复跑）；新增畸形 store 返回只清本次可证 locator、操作 ID 前缀、模型四字段、协议/端点保留和保存不升级会话 ready 反例。扩大 Product/Harness/owner 回归首次发现精简目录描述符兼容错误，修复后 **300P**；Profile **195P**、安装来源 Node **22P**。Sessions/ACP/Profile Chat **45/62/45P**。未据此声称全仓通过。
- 真实宿主身份下完整旧安装资产 Desktop mount-only 探针通过：ready/rootMounted=true、errors=[]、Chat/Skills/Sessions、renderer 无 Node，prompt=0。root 管理资产在隔离 UID 视图被诚实拒绝，没有削弱信任；增强 Codex/Claude 候选仍待用户 sudo 安装。根 npm test 当前已是全 JS 聚合，不再只测 desktop；终版聚合运行中，后续记录所有失败，不将 18 扩展构建代替全量回归。
- 根无环境修正的 JS 聚合终版 **31/39 suites green，exit 1**：ServerBridge live 旧共享 .venv 缺 Profile（改用本轮独立 interpreter 后同套 **68P**）；6 个 Electron 入口缺默认 bundled Python/bin，agent-shell 另有 Conversation 页面断言；ui-preview 仍启用已退役 ordessa.agent-conversation，history 阶段失败。未删除断言或称作新旧红集合相同。正在以显式开发 runtime 与临时截图输出重跑 Electron 门禁，不动用户服务；原聚合的预览测试会生成 docs/ui-preview/01-empty.png，该文件不纳入本检查点。
- 显式开发 runtime 后 Electron 单独重跑 **3/7 通过**：empty-host、agent-ui、ui-foundations 通过；extensions/ui-service 在其夹具场景 Server 提前退出，agent-shell 页面断言未过，ui-preview 仍引用已退役扩展并缺 IPC handlers。后三组错误未作基线同因证明，保留待排查，不用完整产品 mount-only 成功掩盖。第二次预览输出明确重定向至 `/tmp`。
- 已提交实现恢复检查点 **daf7f01d81**，58 文件；没有纳入截图，没有合并 main/发布。下一项用户协助：执行 `bash /tmp/ordessa-install-native-profile-verified.sh`，新增 `/opt/ordessa/harnesses/profile-native/artifacts` 中增强 Codex/Claude 资产，单次原子落位、安装前后完整摘要验证，不覆盖普通/Pi 资产。此项尚未执行；执行后才能记安装和真实产品应用证据。Pi 新 provider、已有历史跨 provider 恢复、真实聊天及上述剩余门禁仍未完成。
- 首次提交的公开准备钩子已接通：独立通道 initialize 后、session/new 前，后端解析 Profile/model/provider/credential，保留操作身份并核实原生结果；Unknown 只查询，不重新创建。前端清空选择不能绕过已开始的准备或 C4 检查，显式丢弃才能结束该草稿 attempt。
- Codex/Claude 产品显式增强资产选择和逐实例目录已接线；默认仍使用原安装资产，增强候选未安装。后续同一认证路由可切 model 或更新 Profile；凭据移除/轮换、endpoint 漂移或 owner/generation 变化拒绝，不通过删除 credentialRef 假装匿名成功。
- 主代理本轮独立复跑：products/server + Harness configuration_model/owner **250P**；Profile **195P**；model-provider server **162P**；Agent Sessions **45P**、ACP **62P**、Profile Chat **45P**；native 安装/启动 Node **22P**。根 typecheck、18 扩展 build exit 0。Python 套件分进程，避免既有 conftest 同名导入冲突；这些不是全仓 Server 回归数字。
- **明确未完成**：设置页人工操作验收；Pi 新 provider/credential 初始配置；已有历史的跨 provider restart/resume；增强资产可信安装；完整 Desktop UI 应用和用户真实聊天验收。Ubuntu 存储实现及直接导入源码已完成，并有真实密钥库/wire 证据，但不能代替设置页操作和 Agent 应用验收。固定顶层待办不扩张。
- 实施前 Ubuntu 只读核查：系统 Secret Service 有会话总线 owner，GNOME keyring/libsecret 已安装；当时产品没有安全存储实现、缺省 secret_store=None，声明 credentialRef 在原生效果前拒绝 CREDENTIAL_UNRESOLVED。后续实现及验证见上文；未读取现有密钥，不落明文，不用 MemorySecretStore 冒充生产。
- 用户认可系统密钥环方向后，新增产品层 LinuxSecretServiceStore，复用 SecretStorage 3.5.0 与既有 SecretStore 协议；产品 default/native/sidecar 注入，裸宿主行为不变。固定 Python 闭包增加 SecretStorage/Jeepney/cryptography 及依赖，deb 推荐标准 keyring/PAM 包。当前仍在验证，未宣告凭据 UI 已可用。
- 实际 GNOME 探针首次保存后的核验失败：系统添加 `xdg:schema=org.freedesktop.Secret.Generic`，旧严格属性集拒绝。已只按本次创建时刻/自有格式/唯一条目删除该合成测试条目，未读取现有秘密；正在加精确兼容及保存后失败清理反例。不因系统测试失败改为跳过验证。
- 该缺陷现已修复，只允许上述精确系统属性，其他额外属性/错误 schema 仍拒绝。存储 **39 条**反例通过；主代理产品/Harness 定向和既有 Linux 裸宿主测试合计 **294P**（零 skip）。实际系统合成值两次 roundtrip 成功，其中一次在**另一个 Python 进程**读取成功，测试条目均已删除；没有读取已有秘密。
- 保护范围：默认 persistent alias、加密 Secret Service session、每次调用/整轮超时、禁止后台 Prompt/Unlock/创建集合/明文回落、自有应用+数据根+随机 locator 精确搜索。返回 create 对象后的校验失败只清理该对象；若 create 超时且对象尚未返回，不能确认 daemon 是否留有条目，明确报失败、不报成功，保留此不确定性限制。
- 产品输入体验仍有缺口：model-provider 设置目前仅输入 credentialId，没有直接输入 API Key 的 wire/UI。下一步应在 model-provider 自有入口中以内存字节导入，复用 CredentialRecords 和可选 store.import_bytes，不绕账户资产、不生成明文临时文件，不扩张 Pacthold 的强制协议。
- Electron 默认命令再次暴露开发环境没有完整 `/opt` bundled Python/bin（未隐藏）；指定既有独立开发运行根的空宿主 smoke exit 0、ready=true/errors=[]，只记空宿主，不记完整产品 UI。两品牌实际 C4 无模型探针再次通过（Codex gpt-5.5→gpt-5.6-sol、Claude sonnet→haiku），ledger 仍为夹具、候选仍未安装。
- 打包契约测试本轮 **24P/1F**：现有旧 deb 提取后缺 `ordessa_profile`；本轮没有重建 deb，不能将旧包检查记为新包已验收。日志 `keyring-deb-contract.log`。
- 下一步 UI 同批必须处理三项真实缺口：直接输入 Key 的 domain-owned import/Unknown 处理；provider create/update 缺 required requestId；新供应商配置发送空 models 被后端拒绝。模型获取须显式操作，不自动发外部请求。本轮只完成安全存储，未据此宣告设置页完整。
- 本轮并行继续沿用同树文件所有权：后端准备、前端消费、真实适配器/只读环境审计三条线；主代理契约/产品装配/集成门禁/文档，子代理无 git 写入。不更改 main、host、原系统资产、用户服务或他属截图。

## 已落地

- i003 `61a41b264d` 经审阅收编为 `7f5e1aaa68`：启动事实刷新、平台令牌同名载体接线。
- ServerBridge 的 `args` 透明转发接缝（decision-log Q2），参数做快照、拒绝 NUL；不解释业务 flag。产品启动计划尚未绑定，不能据此声称 Harness 可用。
- Profile 插件自己的 `profiles.v2.*` 管理入口：独立 SQLite、真实创建/查询/改名/归档/恢复，CAS 与幂等复用既有业务规则。
- 所有 wire 成功结果使用 `{data: ...}` 对象包装，适配 C-03 不接受顶层数组的事实；前端按同一规则解包，Unknown 不重试。
- Profile API 的构建载体公开 service/token；frontend 真实激活，复用已有 Harness→Profile 管理视图，经 WirePort 调后端。
- 默认 Server 产品显式组合 Profile；打包源包清单追加 Profile。裸宿主无业务依赖增加。
- Harness 目录只读后端实际注册项，不在前端列出虚构品牌。默认无 Harness 的组合会返回空目录。
- 管理页面明确注明：当前只持久化预设，尚不改变 Agent 配置。未宣告 clone、save patches、会话应用等尚未接线的方法。

## 验证

- `apps/desktop` 的 `tests/wire-facts.test.ts`：5/5。
- `packages/desktop-platform/server-bridge` 的 lifecycle 测试：16/16。
- `plugins/profile/frontend`：11/11；包内 typecheck 通过。
- 独立 venv 的 `apps/server/tests/test_plugin_host_gate.py` + `plugins/profile/tests`：205/205（49 + 156），无跳过。包括真实 TestClient 鉴权 wire 请求、持久化/重启/卸载反例。
- `npm run build`：17 个启用扩展；lock 由构建生成。
- 根 `npm run typecheck` **仍失败**：错误位于未修改的 MCP frontend/status、model-provider chat contribution，以及缺依赖的 agent-ui-probe 示例。不能把本检查点称为全仓绿。
- 以上为受控验证；尚未实际 Electron 操作、真实 Harness 对话或装机验证。

测试使用新建 `/tmp/ordessa-closeout-test-jDOBxj/venv`，没有重指其他工作树的 editable 安装。未固定这套临时测试环境的第三方闭包，不代替发行锁文件验证。

## 剩余主链（按顺序，不扩展协作机制）

1. 产品层构造 native Server argv 并使用 ServerBridge.args；Harness 插件补桌面原生的受管适配器启动策略。当前 access-launch 仅认可只读 `/runtime/artifacts` 路由，不能直接塞安装路径或移除来源校验。应分别证明品牌 pin、路径约束、配置隔离与 OS 确认释放。
2. 单 Harness 先跑通受控 initialize/session/new，再补多 Harness 的后端权威目录与路由；上层不得根据本机 CLI 猜可用性。native 产品路径需同步组合 Profile，不能仅默认组合有入口。
3. 将真实运行端接到 Harness ConfigurationApplicationService；Profile 配置提供者与会话身份接线，确认配置 receipt/readback。当前受控 Runtime 注入测试不是此项的生产实现。
4. Profile Chat 入口改成合法 factory，注册 picker 渲染与 next-submit 应用路径；选择不打断输出、只在提交时应用、失败保留草稿、不把临时覆盖写回全局。当前 entry 仅命名导出，尚未完成。
5. 修资产 frontend 的契约错位，收编/核对 w019 外壳；再交用户启动开发版，人工验证真实模型和 Profile 切换。不要先花时间重做 deb。

这几项是当前源码里确认的生产接线缺口，不能以“构建成功”或“组件测试全绿”替代。

## 追加：并行边界与 native 来源裁定

用户授权本会话内子代理并行，沿用此树与 Spec Kit 计划，不开新工作树/长期任务、不初始化另一套工单。借用协作 skill 的文件所有权、反例和主代理复跑要求；按用户偏好豁免默认的工单/清单初始化。子代理不得提交、改公开契约、扩大写权或继续分派。

- Harness 子代理：先修 builder 的旧摘要导入/PYTHONPATH，限 `plugins/harness/packaging/builders/**` 与包内测试；native 策略后续单独交底。
- Profile 子代理：限 `plugins/profile/integrations/chat/**`，修真实 sessionId、选定 Profile 的 backend registration 与无切换结果确认，不能编造 runtime evidence。
- MCP 子代理：限 `plugins/assets/mcp/frontend/**`，按现有 API 修 DTO 消费；canonical/运行上下文缺席则明确禁用相应操作，不覆盖已有定义、不伪造已应用。
- 主代理：装配与接缝集成、共享文档、统一测试/提交；其他子代理均不触碰这些文件。
- 不运行真实模型或改用户全局凭据；运行期验证仍交用户。

用户本轮选择：native 桌面接受 root 管理、普通用户不可写的安装树与完整内容校验。此来源策略与原 `/runtime/artifacts` 真实只读策略分离；后者不放宽。普通用户拥有的开发树，即便 chmod 555 或旁置摘要一致，也不能冒充这种系统安装来源。需要开发场景时另建清晰来源方案，不能静默降级。

本轮子代理费用/精确 token 消耗不可读取，不伪造花费数字；并发最多三名子代理，主代理只做轻量检查，重型构建/最终测试串行。

### 本轮已复跑的插件微修复（尚待统一提交）

- Profile Chat：20/20、包内 typecheck 通过。使用真实 `ChatLocation.sessionId`，提交时注册最终选择，未切换结果必须核对后端确认记录；生产 Chat submit hook 与 ACP 配置应用仍未接通。
- MCP frontend：39/39、包内 typecheck 通过。按既有 DTO 消费；API 不返回 canonical 时禁止编辑覆盖，未绑定运行上下文时不查询运行状态。未宣告真实 MCP 可用。
- model-provider Chat contribution：显式 props 泛型修复，21/21；全仓类型检查中该错误已消失。
- 全仓 typecheck 此时仅剩 `examples/agent-ui-probe` 所用的 `@assistant-ui/react` 缺失。该示例被产品 UI 测试消费，故由 `products/desktop` 声明已记录版本 0.15.21 的 devDependency；不向 desktop host 添加业务依赖、不移除测试。安装及最终复跑尚在进行。

复跑更新：依赖安装后，全仓 `npm run typecheck` 通过；产品 UI 测试 3/3（真实 assistant-ui runtime）。安装审计返回 4 项报告（Vitest/mocker、Electron/extract-zip 链），未盲目 `audit fix`，本检查点不宣告发行依赖安全审计完成。

native 校验主代理复跑：新增安装来源测试 7/7（正例明确模拟 root 元数据，实际文件内容与 Python v1 摘要交叉验证；真实 user-owned chmod555 树拒绝）；builder 路径迁移 + access route 15/15，Python startup argv 6/6。尚未安装系统资产、未证明真实品牌启动，产品 argv 仍待绑定。

最终补充：Python startup argv 增加非规范双斜线根路径反例，主代理复跑 7/7；`npm run build` 17 扩展通过，lock 由 build 刷新。原生来源策略、插件契约消费微修复与产品测试依赖作为独立检查点收编，不合并 main、不发布、不执行真实模型。`sourceLockDigest` 目前仅验证格式；未绑定可信源锁文件，故不声明做过锁内容对比。

## 下一检查点：原生产品装配与透明启动计划

- 产品 CLI 增加 `--native-installed-artifact-root`，只允许 native 路径；规范绝对路径在创建数据根前验证。通过产品→compat composition→Harness transport 的 startup argv，不进入 connect 消息。
- 原生产品显式注入 ProfileServerPlugin，Harness 目录来自实际 native 注册项；受控装配证明配置预设可创建/读取，未宣告会话应用方法。
- compat 仅提供可追加插件实例的装配参数，不导入 Profile 实现。
- 产品补齐已使用的 model-provider / permissions-backend 发行依赖；Q5 历史测试按当前 9 插件精确组合更新，保持两个审批路由分别归原 owner，未放宽成子集断言。
- Harness 的 `packaging/native-server-plan.mjs` 复用唯一 managed descriptor 与校验策略，拥有品牌/包/入口路径；产品只传 harnessId/pluginRoot/artifactRoot。
- 桌面主进程经通用 `productServerArgs` 解析 `ORDESSA_SERVER_ARGS_JSON` 后转交 ServerBridge。拒绝非数组、非字符串、NUL、超限输入，不作 shell 分词，不解析业务 flag；错误仍走既有故障 UI，不回落成另一个组合。
- 开发产品入口 `products/desktop/run-native.mjs` 默认选 pi，可显式设 `ORDESSA_NATIVE_HARNESS`。需要真实 root 管理的安装资产和既有 bundled Python；没有资产会在启动前拒绝。该入口不安装资产、不关闭 Electron sandbox。
- 本检查点仍为单 Harness 产品装配，不能宣称同时多 Harness 或真实对话已验收。

主代理验证：产品/宿主/Profile/startup 定向 76/76，后加的 transport startup-only 装配反例单文件 7/7；server-bridge 参数与生命周期 25/25；native 策略＋三品牌启动计划 7/7（root metadata 正例为模拟）；全仓 typecheck 通过、17 扩展 build 通过。无模型、无装机、无发布。

### Profile 实际应用的下一段（避免仅修入口假绿）

1. Chat toolbar 当前 resolver 仅识别自己的 connection badge，必须消费现有通用 UI binding/outlet，而非 import Profile 组件。产品需要启用 UI service 并指定组件实现选择。
2. Profile Chat 当前 entry 非 default factory；激活后应通过上述公开面注册与装载 picker，目录更新须能刷新，不能靠启动时一次 catalog 缓存。
3. Chat 公共 API 目前无 scoped 提交前钩子；需要一条保持提交快照与草稿版本、异步拒绝不发送、不打断输出、无重复提交的接缝。
4. Harness ConfigurationApplicationService 当前明确拒绝 InvokeAction，没有生产 live owner。须先由 ACP 的实际会话观察绑定 canonical SessionRef，再实现受控配置 action 的授权、执行、应答/readback；不能伪造 receipt 或把 session/new 观察当配置确认。
5. Profile 服务只有管理 wire 方法；会话方法必须等配置应用与上述钩子接通后再宣告。跨 provider 重启恢复、多会话隔离要单独验收，不能根据同品牌 model 切换通过推断。

## Chat 配置准备与资产检查（后续接线进行中）

- Chat API 增加 scoped submission guard：只在显式提交时运行，按 order/id 稳定排序；异步准备期间贡献卸载、增加 guard 或消费者上下文变化，均不继续发送。明确拒绝、未知结果分别保留；抛异常也归 unknown，不能把丢回执冒充未执行。没有 guard 时仍走原 gateway。
- ChatContributionView 保留注册者原始 key（兼容旧贡献为可选字段），不可按字符串重新构建 UiComponents key，否则触发真实组件身份冲突。Chat 前端正在接通公开 binding/outlet；产品启用通用 UI 服务，不向 host 注入 Profile 组件。
- 主代理复跑 Chat API 31/31，包括准备拒绝/未知/异常、scope 卸载、变更上下文、gateway 丢回执零自动重发等反例。前端验证待子代理完成后独立复跑；这些不等于 Profile 原生配置已经应用。
- Pi 资产在独立临时源树按既有锁构建，主代理复算 Python v1 全树摘要：15458 entries、64909674 bytes、sha256:afe238d3439df45af77581f7bc969897aa445a1c7b9a686c36c9a31dafa8420f，与旁置 manifest 一致。路径 /tmp/ordessa-canonical-assets-ucPlfB/pi-runtime；仍为 uid1000，不能通过 root 安装来源要求。安装 /opt 的权限另询用户，不修改全局 Pi 配置或登录，不启动模型。
- 原生 Pi 配置审计发现 setModel/setThinkingLevel 会通过 SettingsManager 写默认值。生产应用必须隔离实例配置目录，不能只看到 session/set_config_option 有响应就声称多会话互不影响。首发需要 session/new 成功后、prompt 前应用；当前 draft 没有可确认的原生 SessionRef，不得猜身份或跳过应用。

主代理追加验证：Chat frontend 59/59（含真实 UI service 注册、卸载/重激活、局部错误隔离、输出中 Enter 不绕过）；全仓 typecheck 通过，18 扩展 build 通过。产品 UI 平台测试由“尚未启用”的历史断言更新为显式 Profile provider 选择，仍保留 foundations 不组合 UI 实现、API-only carrier 和共享 token 严格身份断言，定向 3/3。

根 `npm test` 实际为 39 suite 聚合，本次未经配置的运行 28/39：wire live test 默认共享解释器缺 ordessa_profile，显式指定独立集成 venv 后该 workspace 68/68；Skill session guard 一项红（126P/1F），其 runQuery 路径本轮未改，未做完整基线归因，待后续收口；产品 UI 历史未启用断言已如上修正；ACP 独立 rig 仍红、未分类；多项 Electron gate 无 bundled python/bin，未达到启动链；preview 另含退休 ordessa.agent-conversation fixture。不要把这次根聚合登记成全绿，不跳过这些门禁。补齐真实运行环境与更新退休 fixture 仍是产品接线工作。

Pi 系统安装已获得用户授权，但本机 sudo 需要交互认证；提供 /tmp/ordessa-install-pi-verified.sh，由用户终端运行。脚本只创建缺席安装目标，在 root-owned staging 验证真实完整摘要后无覆盖落位，最后再验证；失败 staging 保留，不递归删除。安装完成前仍不得登记系统可信资产已具备。

Profile Chat 有限入口接线已由主代理复跑 23/23：合法 default factory、共享 token、公开 UI provider、真实目录首次/显式刷新、同步失败后可再次刷新、选择仅记录临时意图、无生产会话身份/应用端口时明确拒送。用户显式清除选择后可回原发送，不自动清除失败选择。此入口仍不能称为 Profile 实际应用；真实服务端配置 admission/C4 owner 未落地。

收尾验证：根 typecheck 与 18 扩展 build 通过；产品 node 边界门禁全量 16/16（新版显式选择断言已纳入）。全仓 preview 测试改写的一张跟踪截图已仅还原本次生成变化，不纳入源码提交。根 main 保持原分支且干净；本检查点只留 integration 分支，不合并、不 push、无真实模型调用。

### 系统资产与 Profile owner fence 追加验证

- 用户已执行 Pi 安装。主代理独立重验真实 root 管理资产、锁与完整摘要；通过真实 AccessEntryTransport 对安装的 pi-acp 0.5.0 发 initialize，protocolVersion=1，随后确认进程释放。配置与会话目录均独立，session/new=0、模型 prompt=0；这是安装/协议握手证据，不是 Profile 应用或真实对话验收。
- Codex ACP 1.1.14 与 Claude ACP 0.81.2 已按锁构建，主代理复算全树摘要分别为 9051b844a8feeb241667dd0cc03e80d082e140e88e49ecb3f195385e209f2ca1、03324c056754cf7e7a0d117a5abdab02705ef38993d82847b9bb30b2f5d542c5。用户已执行安装脚本；主代理独立复验三品牌系统资产与 nativeServerPlan 全通过，Codex/Claude 经真实 AccessEntryTransport initialize 全通过、进程释放确认。独立 HOME/品牌配置目录，session/new=0、模型 prompt=0，不涉及登录。
- Profile carrier 必须消费后端 owner 显式解析的 ApplicationTarget，不再从 realm/nativeSessionKey 猜 server/channel，也不以确认缓存猜 runtime generation。计划记录完整 target fence；应用前重新解析，server/channel/generation 任一变化均在申请 permit 与 effect 前拒绝。三个新增反例修复前全红、修复后全绿；carrier + real-service 定向 27/27。生产 owner 与原生配置应用仍未接通，不冒充完成。
- 已构建临时真实开发运行根 /tmp/ordessa-native-dev-runtime-bNpAO6zy：独立集成 Python venv 加当前仓 Go 桥（Go 1.24.13，CGO=0，digest 714044a5b490a53d5fa89aade993c496e5fa3a5f7c614b4465c4990575185cbd）。这是开发验证环境，不是发行安装包或历史基线桥摘要。
- 追加 Profile 后端全套 173/173（Starlette 弃用告警一条）。真实开发运行根下空宿主 Electron smoke 通过；完整启用清单 + 真实 native Server 探针根界面挂载成功，但因 Skills 前端调用 skills.catalogue 而 native 产品未组合 Skills 后端报错，故产品探针退出 1。native_runtime 当前仅追加 Profile；default_plugins 也未组合 Skills。这是已确认装配缺口，不作完整产品可用声明；后续须连同贡献点、Profile/权限端口正确组合，不通过隐藏错误或伪造能力解决。

### 原生产品领域装配（继续推进，完整产品待重验）

- native_runtime 追加真实 ModelProvider/Skills（保留 Profile），产品显式声明 Harness C2 贡献点，使用公开注册/激活面，不修改 Server/Pacthold 核心。插件选择包含追加项，停机重启会重新激活全量选择。
- ProductSkillsPlugin 仅在产品内补 Profile 依赖与当轮 ProfilePluginServices。Skills 的权限可选边通过现有 callable 注入，从当前活跃 authorizer 读取 ceiling；不缓存被处置轮次的对象、不将读取失败当无约束。不可直接依赖 permissions 全部端口：其 acp.admission.gate 与宿主同名，会被既有冲突门正确拒绝。没有放宽冲突门。
- 原生装配 9/9：真实库 wire、Profile assets.skills 配置贡献、重启换服务实例、重启后权限 consulted、追加激活失败后同数据根重试，均通过。整个 Skills 后端＋产品测试＋Profile 后端 625/625，1 条 Starlette 弃用告警。Skills 引用证据中的 Claude 行号因源码调整过时，已改到实际版本行，未改版本主张或断言。
- 产品发行依赖与打包本地闭包补 ordessa-skills；deb 合同检查追加 Profile/Skills/product skills 模块。尚未重建 deb，不能把源码闭包更新记为安装包验证通过。
- Skills 管理页 gateway 还使用另一套历史方法名/DTO，仅补装配不足；有界子代理仅处理 plugins/assets/skills/desktop 下协议映射。完整 Electron 产品探针须等待这段实现后重跑。普通 default_plugins 的领域选择本轮不变，追加能力限定 native 产品路径。

### Skills 前端与真实产品启动收口

- Skills desktop 已改为实际后端方法名、裸 DTO 与逐行 rowVersion CAS；skills 请求单独补 params.requestId，workspaces 请求不混入该字段。导入声明与分片使用相同排序。不具备的 source 管理、非公共归属导入、已有内容更新及 layer-draft preview 明确拒绝，不伪造成功。预览 script body 不进入 UI，不声明后端已停止传输该内容。
- Skills 133/133、根 typecheck、18 扩展 build、产品 node 边界 16/16 均通过。旧会话 guard 测试改为分别持有两个真实 query record，原新会话结果与陈旧结果不得覆盖断言保持不变；另有全测试文件 TS 检查的既有参数错误，不将该独立口径记作全绿。
- 真实 native Server + 完整 Electron 清单探针通过：Chat、Skills、Sessions 挂载，rootMounted=true、errors=[]、renderer 无 Node。临时用户目录与开发运行根；未登录、未发送模型请求。产品边界测试会构建共享 dist，探针与其必须串行，最终 build 后复测成功。lock 仅由 build 刷新 Skills entry 摘要。
- 此结果证明启动与基本读取，不证明 Profile 原生配置应用、会话内配置切换或同一产品同时多 Harness。上述三项仍继续接线，main 未合并、未发布。

### ModelProvider 的 Profile 贡献收口

- native 产品显式组合既有 ModelProviderFacetProvider，声明 profile-contribution 发行依赖与打包闭包。首次装配与 stop/start 后均保留 assets.model-provider 贡献；不是自行实现另一套 Profile 注册表。
- 保存反例暴露接口错位：Profile 保存/会话覆盖校验原先传空 reference_facts，模型贡献只认识 camelCase Harness。现传 Profile 持有的 harness_id；贡献消费 Python snake_case 与既有 camelCase，冲突身份拒绝，不从用户配置推断归属。
- 同版本重新加载原先被模型贡献判为 MigrationUnsupported，导致合法配置重启后被隔离。现同版本完整合法 ModelChoice 保持，损坏或未知版本仍拒绝。实际 Profile 存储→重启→新 core 读取，完整 choice 非隔离；跨 Harness 写入拒绝。尚无配置应用回执，测试显式断言 config_port 仍未组合。
- 产品＋模型 Profile 贡献＋Profile 后端 216/216，Skills 后端另进程 433/433。将两套测试同进程聚合会发生既有 conftest 裸导入碰撞并收集中断；本轮独立进程复跑，未删除测试或假报聚合通过。未重建 deb，未调用真实模型。
- 下一项仍是原生 session/new 后 prompt 前的真实配置应用：canonical 身份、实例隔离、配置授权与独立 readback 缺一不可。目前 ACP 产品单 Harness identity 也仍限制同一产品多品牌，不能把三品牌 initialize 通过写成该能力完成。

### 同一原生产品多 Harness 装配收口

- 产品默认组合 Pi、Codex、Claude Code，显式 ORDESSA_NATIVE_HARNESS 保留单品牌启动。Harness 启动计划逐资产复核，额外绑定由产品 CLI 转交插件组合；Server/Pacthold 内核无改动。每个品牌拥有独立 native profile identity，hello 的 acpChannelHarnesses 为后端权威目录，前端只消费并校验，不自行发现品牌。
- 产品受控多绑定测试 8/8；安装资产与启动计划 9/9；ACP workspace 43/43；Profile 后端独立进程 173/173；产品及模型 Profile 贡献 51/51。根 typecheck 与 18 扩展 build 通过，lock 由 build 生成。
- 相关 native 后端回归 37P/1F；唯一失败 test_native_first_send_completes_with_reviewed_fake_acp_peer 在 a6ba4c4cd3 只读源码快照中独立重跑同因失败（退役 worker-entry 执行链），不登记为全绿、不更改其断言。
- 真实安装资产＋同一产品 Server＋同一项目同时开出三品牌通道，各自 initialize 成功（Pi ACP 0.5.0、Codex ACP 1.1.14、Claude ACP 0.81.2），connection/execution 标识独立，三者释放均确认。探针 /tmp/ordessa-real-multi-initialize.py，独立 HOME 与品牌配置目录；session/new=0、prompt=0，无登录或模型费用。
- 最终 build 后完整 Electron 原生产品冒烟 ready=true、Chat/Skills/Sessions 挂载、errors=[]、renderer 无 Node。此项只证明启动与读取，不能替代真实对话、Profile 应用/切换或发行 deb 验收。

### Profile 配置保存接口接通（编辑 UI 与应用仍未完成）

- profiles.v2.saveProfile 接入既有 ProfileServiceClient 的 ItemPatch 契约，不新造业务格式。set/unset 同事务，校验所有条目后写新修订；unset 只清新修订中的值，不删除历史数据。保留既有 set_facet_values 的调用及无清除时的幂等请求形状。
- 反例先得到 8 红（接口缺席），随后新增非字符串 op 反例；Profile 后端 182/182，产品＋模型 Profile 贡献 51/51。覆盖 malformed/重复 patch、CAS、重复请求、混合有效/非法 patch 全部不落账、清除后历史保留；产品测试用真实 wire 保存模型 choice，stop/start 后验证完整保留。
- 此接口不改变任何原生 Agent，也不宣告 beginTurnApplication。ConnectedProfileManager 尚未接配置编辑器。原生应用的关键缺口仍为真实 owner/generation、实例配置隔离、action grant 与独立 readback；不能用 set_config_option 的应答伪造已生效证明。

### Profile 编辑页与 Pi 独立配置读回（2026-09-30）

- Profile 管理页通过公开 C7 装载配置编辑器，不 import ModelProvider UI。Profile API 提供共享身份 `profileFacetEditorKey(facetId)`，组件 props 包含真实后端描述符、schemaVersion、Profile target/revision、draftGeneration、resolved items 和有界 ItemPatch 回调。消费者与实现者均从产品 API carrier 导入同一 key。旧 ProfileContributions 参考注册表未冒充已接入本路径。
- ModelProvider 注册 `assets.model-provider` 编辑器，读取自己的本地供应商目录，按 Harness 过滤，provider/model 作为一个完整 choice 原子修改。尚未支持的 schema 只读；保存的失效引用不自动替换。清除/放弃只处理草稿，显式保存才调用 saveProfile；丢回执不自动重试。移除 UI 提供者只隐藏控件、不删除数据。
- Profile wire DTO 适配实际 Python `items` 描述符与 profile-only resolved item source/revision；不递归改用户配置值，也未声称 session preview 已规范化。Profile 前端 20/20、API 10/10、ModelProvider desktop 10/10、产品 UI 3/3；包内及根 typecheck 通过，18 扩展构建通过。新增反例包括保存同事件双击、异步旧请求返回、加载重试、提供者卸载、未知 schema 只读、丢回执保留草稿。
- 用户授权先实现与验证 Pi 增强资产，保留现有安装/登录/全局配置。新增 `packaging/pi-profile` 复用锁定 upstream 标准 ACP handlers，仅增加 `_ordessa/session/configuration`。返回 live session 的独立配置读回及对象 generation，拒绝未知/关闭会话与额外输入。启动要求预先分配的私有实例目录，设置 Pi 的配置/会话目录；不复制全局登录。实例隔离不是 sandbox，也不宣称一个实例内多个 session 默认设置互不影响。
- builder 默认路径/上游入口保持原样，`--profile-bridge` 才加三个审计模块并纳入全树摘要。builder＋query＋入口边界 15/15。真实增强 Pi 无模型探针创建 session、修改推理配置、重新查询、验证独立 settings 写入和模拟全局 sentinel 未变、close 后查询拒绝及进程退出 0。使用明确 synthetic fixture key，零真实凭据、零 prompt；不冒充模型/provider切换验收。
- 验证资产 `/tmp/ordessa-canonical-assets-ucPlfB/pi-profile-runtime-verified`：15461 entries、64915208 bytes、digest `sha256:f990065957b6920b9a7bfd5f61d7a8c19dd7e230b0f5542c81f35a3f855d5272`，source lock `sha256:8e6a4962ee2befc1a5ed1a8533c0ae7a749cce5e81030f68ca7a643a9daae95d`。仍是 developer asset，未安装系统、未替换旧资产；现有 installed 默认入口不会隐式接受增强入口。
- 当前沙箱 UID map 为 `1000 0 1`，root 资产显示 nobody，信任校验正确拒绝。改在真实宿主环境复跑既有无模型完整桌面冒烟成功：ready=true、rootMounted=true、Chat/Skills/Sessions、errors=[]、renderer无Node。未放宽 root 信任策略，未修改 `/opt` 权限。
- 尚未完成：增强资产的显式可信启动路线、ACP canonical owner＋generation 生产绑定、受限 configuration action grant/receipt/readback、Profile next-submit 应用、Codex/Claude provider restart/resume。保存 UI 和 standalone Pi 查询不等于这些生产链路完成，根全量聚合旧红也未据此下账。main 保持原分支且干净，不合并、不 push。

### ACP 后端独立读回接缝（后续应用进行中）

- Harness 的 live channel/registry 提供只读 `query_native_configuration`，仅接受该通道真实 session/new 应答确认的 native session；不接受任意 RPC method/action，不从 UI key 猜身份。它返回真实 channel/execution/ledger session/native session owner、opaque native generation、busy 与不可变配置快照，不返回 applied receipt。
- 后端自有请求使用保留 ID；只拦截对应的 Agent response，正常聊天通知与双向 Agent request 仍进入 relay。客户端复用保留 ID 在发送前拒绝；超时不重试，迟到应答不进入聊天；断连唤醒等待者，读回后再验 registry 所有权，容量耗尽零帧拒绝。畸形、跨会话、重复选项与非有限 JSON 不产生证据。
- 新只读接缝 15 条反例及既有 C4/managed channel 定向回归共 60/60（单条 Starlette 弃用告警）。真实增强 Pi 的 probe 加 `--owner-rpc` 再次通过，使用真实后端 query/response 分流代码；ledger 字段为夹具，不冒充完整产品 canonical Profile 绑定。零 prompt、仅 synthetic fixture key，实例设置写入/模拟全局配置不变/关闭后拒绝/进程退出均再次确认。
- 旧路径 `plugins/connectors/acp/sessions` 已不是 workspace；一次按旧路径的 npm 命令未运行测试，不记作回归结果。改用实际 `plugins/connectors/acp` 后 43/43；仅 Vite 的未来 configLoader 兼容告警。没有修改 Server/Pacthold/前端 host 或全局安装资产。
- C4 `InvokeAction` 仍保持默认拒绝：当前 generation materializer 也明确拒绝 action/secret，不会为了接 Pi 就放宽这两个保护。下一段需要专门的 action-only 授权与执行接缝（owner/facet/item/action/schema 精确绑定、计划/permit/operation journal、独立读回），以及 opaque native generation 到 C4 整数 generation 的宿主-owned fence；不能把本段查询成功替代这些证据。

## Profile 真实应用：固定待办与本轮检查点

用户授权有界子代理并行，沿用本树；不新建工作树、Goal 或工单，不动 main、不发布、不调用真实模型。使用协作技能的文件所有权/反例/主代理复跑要求，继续豁免另一套调度账初始化。三名子代理分别只读支持矩阵、实现可信入口、实现 owner fence；主代理负责产品接线、测试、文档及最终检查。精确子代理费用不可读取，不伪造预算统计。

### 固定待办（部分实现不勾为完成）

- [x] 核对当前产品三品牌与已注册 facet 的支持矩阵。
- [x] 增强 Pi 系统资产安装、显式启动及实例目录管理的真实产品验收（不等于 Profile 应用确认）。
- [x] 后端 canonical Profile 会话注册与真实 owner/generation 完整生产绑定。
  - [x] Pi 真实产品 wire 路径登记 canonical 身份并绑定真实 owner/generation；双实例无模型配置应用已验证。
  - [x] 两品牌原生证据读取、显式运行换代票据与旧 target 失效守卫已实现/受控验证。
  - [x] 三品牌共用 C4 live-model runtime/factory 已接入；Codex/Claude 的同 provider model 应用有受控确认、幂等及独立读回反例。
  - [x] Codex/Claude 配置 port/factory 和首次创建前准备源码已接线；受控完整身份/凭据守卫与真实适配器 C4 分别验证。
  - [x] 最终可信资产安装后的真实产品 wire/Profile/C4 应用确认（Pi 前轮，Codex/Claude 本轮；不含 UI/prompt）。
- [ ] Chat 首次/后续发送前应用接线，不打断正在输出的 Agent。
  - [x] 提交 guard/preparation/登记/应用/发送链已实现并受控验证；输出中选择不调用配置接口。
  - [x] 完整启用清单的实际 Desktop 挂载通过无模型探针。
  - [ ] Desktop UI→生产 Profile→原生配置→prompt 的完整端到端验收。
- [ ] 实际应用链验证全局预设/逐项临时覆盖/失败草稿/未知结果语义。
  - [x] 全局预设与逐项临时覆盖隔离、清除、失败草稿、Unknown 只查询，以及 revision 竞争已有受控反例。
  - [ ] 在实际产品链上完整执行这些场景。
- [ ] Codex、Claude 实际切换与跨 provider restart/resume、多会话隔离。
  - [x] 两品牌增强候选首次 provider/model 配置与独立读回通过实际无模型探针。
  - [x] 独立实例入口、品牌锁定和显式增强来源校验及最终增强资产安装已完成。
  - [x] Codex/Claude 真实产品首次准备、同 provider model 切换及每品牌双会话隔离通过。
  - [ ] 已有历史跨 provider 恢复。
- [ ] 产品完整回归及用户授权的真实聊天、配置切换验收。
  - [x] Pi 新供应商/API Key 私有准备源码、受控回归、真实候选适配器双实例无模型验证。
  - [x] 增强 Pi 供应商资产安装后，实际产品 wire/Profile/C4 完整确认（三品牌实际探针，零 prompt/HTTP）。
  - [x] 多次定向回归、构建/类型检查及完整产品挂载已有证据（各次范围见下文，非本轮全仓绿）。
  - [ ] 全量回归收口与用户实际操作验收。

口径校准（2026-10-01）：未勾选顶层表示仍缺整项验收，不表示尚未实现。当前收尾目标是多 Harness＋Profile 基础配置 Desktop；不以未来所有资源 facet 应用能力作为该目标的额外完成门。

### 支持矩阵初次实测（历史源码审计，后续 config_port/应用进展以上文为准）

native 产品真实注册的 Profile facet 只有 `assets.model-provider`、`assets.skills`。模型有 Pi/Codex/Claude 编译器，但没有 production config_port。Skills 的 Profile contribution 当前编译零 intents；原生内容投影不能用“已选择”替代。其他资产存在包内实现不代表已注册到此产品的 Profile。

模型 Profile 保存 `{harnessId,providerConfigId,modelId}`，C2 需要解析后的 `{provider,model,protocol,...}`；应用前必须由模型域解析当前目录/secret 引用与真实实例事实。现 C2 的 session-local 结果仍转为 SetField，未执行 live ACP action；不能用 generation 文件生成假 applied receipt。

### 本轮已实现（不是 Profile 已可用）

- 独立 `pi-profile-runtime` 可信变体，精确入口 `ordessa-profile.mjs` 与增强 manifest 标记、root 来源、完整树摘要全部校验；默认 index.js 不变。仅显式 `--native-pi-profile-bridge` 经过产品→compat→Harness startup argv 生效，connect 不能选择变体或覆盖实例目录环境。
- 每次 Pi 进程 launch 分配随机的私有实例目录，配置不按 Profile 分目录，不复制全局登录。目录退出后保留、不删除恢复内容。新增数据根在 runtime 取得所有权后收紧权限；既有用户根不静默 chmod，不安全根拒绝。
- 新 `ProfileSessionOwner` 接受后端明确注册的 canonical UID，对 registry 确认 owner 与独立 readback 绑定；opaque generation 只作 equality token，使用本地单调 fence，ABA/失活/忙碌/跨身份拒绝。此组件尚未组合到 production Profile wire；跨 Server 重启需 incarnation 或持久 fence authority。
- owner 生命周期采用观察对象身份，不仅比较标识字段；同 ID 的新 session/new 在查询期间替换旧 owner 时拒绝。新增反例先红后绿。未改变公共契约或放宽 C4 action/secret 默认拒绝。

### 主代理验证

- Python 产品装配/实例目录/owner/readback/C4 定向：105/105，exit 0。首次直接用 worktree venv 跑产品测试缺 Profile 发行包而失败；改用明确本树 PYTHONPATH 后复跑，没有删除或跳过测试。最后两条用真实 registry/channel observer 配受控传输钉住同 native ID 替换与两个会话 generation 交错；独立审阅未发现本轮新增阻断，仍不冒充完整运行验收。
- Node 安装策略/启动路线/Pi builder/增强入口：37/37，exit 0；root 正例仅模拟元数据，实际 user-owned 来源仍拒绝。
- 真实开发 Pi 资产 `probe-nomodel.py --owner-rpc`：session/new=1、prompt=0、配置独立读回/隔离 settings 写入/全局 sentinel 未变/关闭后拒绝/process exit 0。ledger 仍是夹具；不是系统安装路线或完整产品会话应用证据。

### 仍须完成，不能隐藏

增强资产尚未安装 `/opt`，产品默认不启用增强路线。registry 当前按 harness+project 复用进程，尚不具备同项目不同会话的实例隔离；分配“每进程目录”不能证明“每会话隔离”。接下来须解决会话 launch scope，再接 canonical 注册、模型引用解析、action permit/journal/readback、Skills 内容应用及 Chat prompt 前/next-submit 时序。Host/Pacthold 本轮零改动。

### 继续推进中：会话隔离与模型引用解析

- 两名限定所有权子代理已交付客户端隔离和模型目录解析；主代理正在审阅并补后端/桥接反例，尚未提交或宣布集成通过。
- 客户端改为项目选择只读，每次新会话分配独立 acquisition scope；同项目旧会话仍保留自身路由。后端正在接收该可选 scope，兼容旧的不带 scope 请求。正在核对释放、重放和并发获取语义。
- 模型解析器消费真实供应商目录及注入的 C2 schema，拒绝失效/歧义引用，只传凭据引用、不读取秘密；子代理定向验证 36/36，尚待主代理复跑和生产接线。
- 固定待办不变：这些组件通过不等于 Profile 已在真实产品发送前生效。无需用户协助的接线与受控验证继续推进。

### 集成复跑与原生操作（继续进行，不是完成声明）

- 主代理实跑：同项目 scope 装配 9/9、owner/独立读回 45/45、模型解析与边界 25/25、会话门面 42/42、ACP 独立集成 81/81；root typecheck exit 0。子代理 ACP 全包 57/57 尚待主代理复跑。均受控，零真实模型。
- 发现并修正真实 unknown 分类：单通道断流不把其他会话标 disconnected；显式提交 unknown 标记穿过 facade，草稿不借用已选会话的运行状态。原 U5b 断言保持，完整集成转绿。
- Pi 新增有界操作记录：仅 live 暴露的 model/thinkingLevel，先检验原生 generation/配置摘要/idle，再执行上游，再独立读回；同操作标识不重复作用，不明确结果保留 unknown。标准 prompt/setter 共用非等待锁，owner-only RPC 不允许 client relay调用。
- Node 资产 builder/Pi 操作/查询/入口共 40/40。正在重建开发资产做真实 Pi 无模型探针；本轮原生记录尚未绑定 C4 target/manifest，不能叫 Profile applied receipt。
- C4 显式 action-only grant/executor 分支正在独立子代理实现，默认 action/secret 拒绝与文件物化保护不变。完整生产 permit、canonical 注册与 Chat 发送前应用仍未完成。

### 本轮检查点与需要用户协助的安装（2026-09-30）

- 会话 acquisition scope 已完成受控集成：项目选择零启动，新会话独立通道，同 scope 并发只启动一次；终态 scope 不允许重新启动。独立审阅发现 launch/注册窗口退出可遗留死连接，主代理已统一清除映射并补两条反例，产品多绑定测试 11/11。独立审阅对配置 RPC 与 Pi executor 未发现其他阻断。
- 主代理复跑：ACP workspace 57/57、独立集成 81/81、会话门面 42/42、模型解析及边界 25/25、owner/readback 45/45、C4/action/file/journal/owner/executor 187/187、Pi 原生操作与安装策略 Node 门禁 69/69。不同集合有重叠，不将它们加总为全仓测试数。
- C4 仅通过显式 action grant/executor 分支支持精确授权的 session action；默认无授权仍拒绝，混合 file/secret/action 拒绝。原生操作记录绑定完整 target/manifest，普通 ACK 无法成为回执，Confirmed 仍要求独立 runtime.observe。生产 permit、canonical 会话注册及 Chat next-submit 尚未组合，固定待办不勾为完成。
- 重建真实开发增强 Pi 后，owner-only 操作、原生 target/manifest 绑定记录、幂等 replay 与独立查询全部无模型通过；session/new=1、prompt=0、仅 synthetic fixture key、独立 settings 写入、模拟全局 sentinel 未变、关闭后拒绝、进程退出 0。此探针 ledger/身份注册仍受控，不冒充完整产品 Profile 应用。
- 待安装资产：`/tmp/ordessa-pi-operations-AEq2eiKX/pi-profile-runtime-bound`，15462 entries、64925886 bytes、tree digest `sha256:968135e988c1507358764deaf9825c005177829fd9b9044c0970572eb61a6cad`。source lock 与上一构建相同。安装目标仅新增 `/opt/ordessa/harnesses/artifacts/pi-profile-runtime`，不覆盖三套旧资产、不改登录/全局配置、不调用模型。
- 用户协助点：在真实宿主终端执行 `bash /tmp/ordessa-install-pi-profile-verified.sh` 完成 sudo。脚本已语法检查，复制后先钉住上述摘要、完整校验 root 可信来源，再无覆盖落位并复验；尚未执行。安装后继续真实可信启动路线，再推进 canonical/permit/Chat 接线，不需要重新裁定架构。
- 全仓 `npm test` 本轮实测 **30/39 suite green**，不是全绿：Server bridge 默认解释器缺 `ordessa_profile`；产品 Node 精确清单遗漏已经提交的 ModelProvider Profile editor；七项 Electron 门禁涉及 bundled python/bin 缺失及 preview 退休 fixture/IPC。前两类环境与 Electron 缺口仍记录，不据此下账。产品清单断言补上真实 editor 选择，继续保持完整精确比较，不删断言；定向重跑结果另记下方。完整日志 `/tmp/ordessa-closeout-current-npm-test.log`。
- 全仓测试产生 `docs/ui-preview/01-empty.png` 输出变化，仅验证副产物，不纳入本轮源码检查点，不删除。main 不切换、不合并、不 push；未改 Server/Pacthold/前端 host。
- 清单反例修正后产品 UI Node 单文件门禁 3/3、root typecheck exit 0、diff 检查通过。此前完整 build 18 扩展通过、lock 由 build 刷新；没有据定向结果把完整 39 套件改写为全绿。

### 系统安装后实测与待讨论决策（2026-09-30）

- 用户已成功执行增强 Pi 安装脚本。主代理在真实宿主上下文复验系统资产：owner RPC、完整 target/manifest 原生操作记录、幂等查询与独立读回均通过；session/new=1、prompt=0，仅 synthetic fixture key，无真实登录或凭据。此单资产探针的 ledger 仍为夹具，不能作为完整产品应用证明。
- 新增可复跑 `products/server/scripts/probe-installed-pi-profile.py`：由真实 `nativeServerPlan` 校验系统资产，经实际产品 composition、wire 项目/通道建立与真实 access-entry 启动两个同项目 Pi 实例。真实 ledger owners/execution 各两个、实例目录各自私有；A 通过原生 setter 修改推理选项后，独立 query 确认 A 已改变且 B 全部配置不变；释放 A 后 B 仍正常。最终全部通道 OS 确认释放、runtime.stop，临时根清理。session/new=2、prompt=0、Profile application confirmed=false，exit 0。探针只处理自己建立的实例，不触碰用户服务。首次基本路线与补强隔离路线均通过。
- 固定待办第 2 项现可勾选；其余 5 项不变。没有把隔离/原生 setter 通过登记成生产 Profile receipt、Skills 应用或 Codex/Claude 切换通过。
- 确认中等规模接缝缺失，已按用户要求提出讨论而非默认授权：Profile wire 目前只声明管理/目录/preview，没有生产 session 注册、select/apply；C4 的 PermitVerifier 仅协议/受控测试，现有 Permissions ACP authorizer 面向消息/工具，不能直接充当配置计划授权。模型 session-local 编译还产生 SetField，需正确变成该原生 action，不能拿文件物化伪装 live 应用。
- 上轮提出将配置计划授权交给 Permissions 的建议已撤回：用户明确普通配置应用只涉及 Profile 与 Harness。权限配置项才消费对应权限规则，不能把普通模型应用等同工具审批；这个误判不是用户设计缺口。
- 后续顺序按最新裁定改为 Harness 自有计划应用→canonical 注册/生命周期→模型 action 映射及独立观察→Chat 首发 session/new 后、prompt 前和后续 submit 应用；凭据/provider restart-resume/Skills 保持各自独立验收，未知或不支持仍明确拒绝，不降低总验收标准。需要影响产品语义/安全边界的真正决策仍及时问，不以怕询问为由继续错误实现。

### 纠正多余审批依赖，继续 Profile→Harness（2026-09-30）

- 已实现显式的 Harness owner-plan 应用路径，生产组合可选，不从 wire 接收模式开关；直接应用该服务自己生成的计划，不依赖 Permissions 或产品层签发凭证。原外部 permit 接口保留原拒绝行为与既有调用兼容，不自动切换模式，也不允许通过新入口绕过已有外部模式。
- 新路径仍保留全部 adapter 身份/字段范围、会话 target/generation、版本/摘要、expiry、journal 先落账、幂等 replay、native receipt、独立 readback/Match 检查；“无外部凭证”不等于任意原生动作默认放行。配置能力范围由 Harness 的已注册适配器和精确 action grant 确定，不授予模型工具权限。
- 先补七条 Harness 反例，现状全部红，修复后 action 全文件 45/45；Profile 对真实 Harness service 的额外消费反例先红后绿，连同原 carrier/真实服务门禁 28/28。证明 Profile 配置应用可在没有外部 permit provider 的情况下获得真实服务的确认结果；这里的 native runtime 仍受控，未冒充产品 canonical 绑定或真实 Pi Profile 应用已完成。
- 当前继续 canonical/产品组合与模型 live-action 接线，固定待办第 3–7 项仍未完成；main 不动、不发布、不调用真实模型。
- 主代理追加复跑：Profile 全套 186/186、Harness service/action/journal/owner/native readback/executor 定向 134/134、产品 canonical 组件与原装配回归 24/24，均 exit 0。Profile 存储新增独立 native_session_key（旧调用及旧请求幂等形状保留），拒绝新 UID 覆盖既有存储地址；三个身份反例先红后绿，不迁移或重写用户历史数据。
- 产品 `ProfileNativeSessions` 组件从已确认 registry owner 生成 UUID canonical UID，Profile 用该 UID 存储，native ID 只作原生路由；相同 native ID 的两个通道互不覆盖。旧 owner 替换/结束拒绝，重复注册原 owner 返回原 UID；不是 resume API，不猜测历史会话身份，也不生成 applied receipt。尚未作为默认产品 wire 注册。
- 增强真实 Pi 产品探针再次 exit 0：两实例真实 ledger、canonical 组件注册到真实 Profile SQLite、UID 与原生 owner/target 一致、修改 A 不改 B、释放 A 后 B 存活；Profile receipt 表保持 0。输出明确 productionProfileWire=false、profileApplicationConfirmed=false。临时 realm/本次随机 server incarnation 为探针组合事实，不冒充最终生产身份管理。
- 一个有界子代理只处理 ModelProvider adapters 的 Pi live-action 映射与包内反例；若现有 AdapterContext 不支持真实动作/模型选项事实，须报告接口缺口，不猜 provider/model 字符串、不擅扩公共契约。主代理继续产品接线，子代理不做 Git、不改账本、不再分派。
- 子代理已按要求停在确证的接口缺口，零代码/测试/Git 写入：公共 AdapterContext 只有 targets/installation/entry/scope/capability_evidence_ref；已声明动作存在于 RuntimeSnapshot.authority.actions，独立原生选项存在于 ProfileSessionOwner.config_options，但两者未通过合法 C2 配置上下文交给业务适配器。不能直接把模型存储中的 ID 猜成原生 option value，不能靠旁路访问 Harness 实现私有对象。
- 待讨论的新设计项（与撤回的 Permissions 建议不同）：建议补 Harness 插件族自身 `plugins/harness/api` 的配置运行证据接口，由 Harness 在独立查询后提供已声明动作与精确原生选项/业务标识映射给注册的配置适配器，绑定当前 owner/generation；不是 UI 提供事实、不把业务判断搬到 host，不扩 Server/Pacthold/desktop-platform。缺证据/过期/不支持均拒绝；旧上下文仍保留既有文件配置路径，不自动升成 live。需要先确定此公共接口再补三品牌适配与生产 C4 runtime，当前不擅改该契约、不用 ad-hoc 字典夹带或猜测字符串绕过缺口。

### 品牌差异归 Harness 的裁定与源码研究（2026-09-30）

- 用户已裁定资源业务与原生适配分离：ModelProvider/Skills/MCP 等拥有数据、UI、Profile 贡献；Harness 暴露统一资源能力并内部负责各品牌的支持判定和应用。此前让资源业务适配器消费更多原生事实的提议不再作为默认实施路线，先把已有品牌实现收归 Harness，复用现有注册/应用机制，不新建平行接口。
- 用户要求先研究多 Harness 产品的实际内部组织。本轮读取最新公开 HEAD 的 Codeg、Orca、T3 Code 与 ZCode 源码，固定 SHA 与具体入口见 `docs/design/harness-v2/multi-harness-organization-research.md`；没有运行上游产品或真实模型。当前未搬迁代码、未改 host/main，原测试产物截图仍未动。
- 建议复用当前 Harness 的 pi/codex/claude 目录，在品牌内按配置能力拆模块；共享 application/registry/transport，品牌注册工厂/能力，运行实例保存独立状态，不使用全局可变单例。不为 brands 中间层搬迁全部正常运行代码，不为每个资源建独立进程管理器，也不强迫未支持能力出现空实现。
- 固定待办第 3–7 项仍未完成；本轮源码研究不能记作 Profile 产品接线或真实应用通过。下一实现步需同步修正旧 C2 所有权文档及迁移清单，再保留原实现和 golden tests 迁移品牌模型适配；不删测试、不修改已有注册/账本身份、不留旧 import shim。

### Harness 原生模型适配归位检查点（2026-09-30）

- Pi/Codex/Claude 的模型编译实现移到各品牌 configuration/model.py；共有类型、golden 词汇和 C2 转换移到 Harness configuration/model/。直接复用旧实现，common.py 与原 HEAD 字节一致；品牌仅调整合法内部导入，未顺带改变配置能力语义。
- 每品牌 registration.py 显式提供新适配对象，由 Harness 自有入口汇聚并注册现有 C2 点。旧 Python 源包/pyproject 删除，三个受控调用者同批迁移；保留既有 facet/adapter/贡献 owner 标识，不影响操作账本。没有新注册框架、host 修改或默认产品能力扩张。
- 文档已修正 README/contracts/spec/plan/tasks/migration 并新增 resource-boundary-amendment.md；历史研究保持来源和授权日期，不以旧文档反向覆盖最新用户裁定。
- 品牌注册反例在缺失实现时跑红；新增边界检查无资源业务实现依赖与旧源码入口。开发环境旧 egg-info/bytecode 可存在，不把其当源实现，也不删除其它环境；新 -S 解释器验证旧包不可发现。反例初版曾误把 descriptor 属性当方法、把忽略产物目录的存在当源码残留，已校正为真实接口/源码语义，未改生产代码迎合错误测试。
- 主代理实跑：迁移原测试+ModelProvider 后端+Profile 全套 412/412（随后增加一条新解释器反例）；新解释器反例在内的迁移测试+产品全套 106/106；Harness 应用/journal/Pi executor/owner 定向 69/69，均 exit 0。套件有重叠，不加总。活动源码旧包名引用为零，diff 检查通过；测试产物截图不提交。
- 此检查点只是原生适配所有权迁移，不代表 Pi live model action、其它资源迁移或 Profile 生产 wire 已完成。用户要求无需逐检查点确认，后续直接推进直到实际硬性阻塞；固定 TODO 第 3–7 项保持未完成，main 不动、不发布、不真实模型调用。

### 生产 canonical 注册与 Pi live 模型应用（2026-09-30）

- 原生产品现在注入 `profile.native-sessions` 并声明 `profiles.v2.registerNativeSession`；后端依据真实 ACP owner 创建 canonical UID 和当前 incarnation target，客户端不能传 UID。Profile 域只消费注入接口，不导入 Harness 实现；未注入的管理组合不声明此能力。跨 realm、未知 owner、伪造 UID 在写 session 记录前拒绝，重启 Profile 后使用新 owner/fence，不持有上一轮端口。
- 实际系统安装 Pi 的双实例产品探针 exit 0，现输出 `productionProfileWire:true`：两个真实 ledger owner 分别注册到 Profile SQLite、UID 不重叠，A 改推理选项不影响 B，释放 A 后 B 存活；prompt=0，全部探针实例退出。`profileApplicationConfirmed:false`、receipt 表仍为 0，不能把注册记作配置已生效。
- Harness 内部新增 Pi owner context（不扩公共 API，也不让资源插件传原生事实）与 live 模型编译/执行模块，复用 C2/C4/原生 action executor/journal。业务 ModelChoice 只解析当前目录、协议、endpoint 和 credential reference；新的默认解析不要求业务层声称 provider 已在实例中。已有明确传入事实的受控兼容路径保持拒绝缺失事实，未弱化旧反例。
- Pi 独立 query 只投影唯一真实 native model 的 provider/model/api/baseUrl，不投影密钥/header；带凭据 URL、歧义与残留 reserved metadata 不成为证据。完整业务 payload 必须与实际原生路由完全一致；非空 credentialRef、协议/endpoint 改变、品牌 hints、非空 requestParams 当前明确拒绝，不丢弃这些请求假装切换成功。
- C4 受控 live-runtime 7/7：native receipt + 独立查询才能 Confirmed，重放无第二次效果、无文件物化；请求未支持能力零效果；读回不同为 Unknown；计划后外部更改/贡献卸载拒绝。额外反例钉住 preflight 不得重新抓一个新 digest 从而掩盖 C4 capture 之后的变化。初版测试误取 Sandbox 的 Pi contribution，已按精确 model adapter ID 校正；没有扩大 action grant。
- 增强开发资产构建完成：`/tmp/ordessa-pi-live-model-runtime-20260930`，treeDigest `sha256:6240b9fa6996fe139dd4a75bb2e461d936b07f43d8eefc9b42ba52a6a0a6c67b`，15462 entries / 64927584 bytes，原 source lock digest 不变。最初 source 参数指向开发产品根而非含 npm lock 的源根，builder 诚实拒绝；使用已锁定的 pi-source 后成功，无资产覆写。
- 对这个开发资产运行真实 Pi owner RPC + C2/C4 model probe，exit 0：同一实例 first→second，C4 native model Confirmed、幂等 replay、原生 target/manifest 绑定、全局 sentinel 不变、实例进程 exit 0；session/new=1，prompt=0，仅 synthetic key。这里 Server ledger 是夹具、Profile receipt=false，不能记为生产 Profile 应用。
- 主代理回归：Harness 模型配置 + ModelProvider 后端全套 + Profile 全套 + 产品全套 + C4 action/service/Pi executor/owner 定向 **580/580**，exit 0；Node Pi bridge **56/56**。未重跑 root npm 全量，不改其此前非全绿记录。套件有重叠，不累加成总覆盖量。
- 实际安装硬门：`sudo -n true` 报 interactive authentication required。脚本 `/tmp/ordessa-install-pi-live-model-verified.sh` 已做 shell 语法检查，拟仅新增 `/opt/ordessa/harnesses/profile-live-model/artifacts/pi-profile-runtime`（保留原 artifacts 全部内容），完整摘要锁定、root 管理、拒绝覆写。当前未安装、未将默认桌面切到新资产；已请用户执行该脚本。
- 固定 TODO 第 3–7 项仍未全部完成：第 3 项生产 canonical 注册已落地，但默认 Profile config port 尚需接线；第 4–5 项 Chat submit 与全量覆盖语义仍待实现；第 6 项 Codex/Claude 切换仍未完成；第 7 项完整产品/真实对话验收未完成。不得把原生 C4 模型确认当作这五项全部完成。main/host 未动、未 push、未真实模型调用，原截图产物保留不提交。

### 已安装 Pi 的生产 Profile 应用接通（2026-09-30）

- 用户完成 `ordessa-install-pi-live-model-verified.sh`；真实宿主上下文复验 root 管理完整资产，digest 与上节 `6240b9fa…` 一致。未覆写旧资产、未切换默认桌面路径。
- native 产品现在组合 Harness 自有模型适配器，注入真实 Profile config port。ModelProvider 只解析保存的业务引用与目录 revision，Harness 提供配置品牌协议声明并独立核对 native metadata；产品不造品牌字段。目录不存在、过期、目标/generation 不符均在原生效果前拒绝。
- 新增模型目录反例区分“已配置品牌的协议声明”与“独立原生可用证据”；不把 `declared` 当实际支持。原目录缺失/旧 registry 无协议声明时真实探针曾诚实失败，随后修正产品组合与 Harness 目录投影，未放宽 native 路由匹配。
- Profile native port 首发与每次下一轮都应用有效值；同 Profile 保留会话 override，其它全局项跟随最新 Profile，切到不同 Profile 才清除临时项。首次/后续受控反例先红后绿；追加 unknown→confirmed reconcile 反例揭示旧恢复路径误清 override，修复后保留。这里只证明受控恢复语义，未冒充实际 Pi 断线恢复。
- 后端 wire 新增既有 API 的 `selectForSession`、`inspectSessionConfig`、`beginTurnApplication`。仅 native 注入组合声明；closed SessionRef 必须已后端登记且 owner 仍活跃。选择只做身份核对，不对正在输出的实例 query 或应用；提交应用才独立 query。回执按已有 TS DTO 包含完整 SessionRef，不猜 UI/native ID。受控 wire 反例先因接口缺失红，修复后绿。
- 最新实际探针由真实产品 composition、wire 注册/选择/提交前应用、已安装 Pi、真实 ledger 与 Profile SQLite 组成：两实例各自 first→second、独立读回及 receipt；A 推理修改不影响 B，释放 A 后 B 存活，最终自行清理。exit 0、session/new=2、prompt=0、仅 synthetic key。输出 `productionProfileWire:true`、`productionConfigPortInspected:true`、`profileApplicationConfirmed:true`。探针脚本支持 `--artifact-root /opt/ordessa/harnesses/profile-live-model/artifacts --apply-profile`；不是 Chat UI 验收。
- 回归分开执行以避开两个 suite 顶层 `conftest` 同名的收集冲突：最终 Profile 全套 192/192、Harness 模型+产品全套 138/138，均 exit 0，已包含 reconcile 反例。真实 wire 应用+回执 DTO 探针复跑 exit 0。未重跑 root npm，不把旧非全绿门禁下账。
- 限制仍明确：生产 native config route 当前只接一个 `assets.model-provider/choice` set，并要求实际 Pi 已有精确对应路由；credential/provider endpoint 变化、reset、多 facet、Skills/MCP 等未支持时拒绝，不丢弃请求假装成功。Codex/Claude 同会话切换尚未完成。
- 固定 TODO：第 3 项已具备 Pi 真实生产模型应用子路径，整体资源范围仍未收口；第 4 Chat 首发/续发实际消费尚未完成。现有 Chat guard 在 gateway 前，而 `createAndSend` 内部把 session/new 与 prompt 连发；需要把登记/应用插在这两个原生动作之间，不能绕过 guard 或先发后应用。第 5 完整 unknown/全局并发语义、第 6 两品牌切换、第 7 完整产品/用户真实对话验收继续未完成。无新增阶段，无真实模型调用；根 main、host、用户服务和他属截图不动。

### 会话覆盖 wire 收尾与首发失败语义待裁定

- 检查点 `fbc4572feb` 固化上述真实 Pi 生产 Profile 应用；不是整个 Desktop 完成。追加既有 API `setSessionOverride` / `clearSessionOverride` / `reconcile`，仍只消费已登记且活跃的 SessionRef。临时覆盖不写全局，清除恢复跟随 Profile；未知恢复只查询 journal/runtime，不发送 prompt。session config 的 items/source/state 与 receipt 投影跟已有 TS DTO 对齐，不改 SQLite 身份或落盘格式。
- 受控 wire 反例已覆盖全局值不变、临时覆盖/清除、forged ref 拒绝、Unknown→确认恢复且应用恰一次。首次测试误用 register_provider 的位置参数，校正为现有接口后才钉住 source 字符串不符合 DTO 的红因；实现修正投影而非放宽消费者断言。
- **待用户裁定的中等规模接缝**：原生 session/new 已成功而 Profile 应用失败时，现有 `createAndSend` 把请求身份锁住，不能安全重试又不重复建会话。建议保留“已创建、尚未发送”的实例和原草稿，明确拒绝后修正配置再复用；未知时只 reconcile、不重发。备选是仅明确未应用时释放后重建，未知仍保留。已通过用户输入卡提出两选一；尚未修改 AgentClient/AgentSessions/Chat 公共契约，不以 ad-hoc callback 穿透私有对象绕过。
- 该决定会确定下一步插件层提交前 preparation 生命周期（agent 契约、ACP、会话门面、Profile glue），不需要更改 apps/server、Pacthold 或 desktop host。其它已验证的后端成果保持有效；不先发旧配置 prompt，不把选择成功当应用成功。

### 用户认可首发保留语义，前端 preparation 接线（2026-09-30）

- 用户认可保留已创建但未发送的 native session：明确配置拒绝后保留草稿、Profile 选择及同一创建 attempt；修正后复用。Unknown 下一次显式点击只 reconcile，不自动二次应用或发送；核实后再由用户点击发送。
- Agent 插件契约新增可选 prepareSession/sendPreparedSession/abandonPreparedSession/nativeSessionOwner、门面 prepareSubmission 与显式用户导航 selectionRevision。旧消费者不必实现；旧路径继续严格 snapshot 身份守卫。ACP 返回的是连接器已观察到的路由事实，Profile canonical UID 仍由后端 registerNativeSession 铸造，前端不自造 UID。
- Profile Chat guard 位于 session/new 与 prompt 之间：登记、选择、应用、精确会话回执校验后才允许发送；下一轮继续应用当前有效 Profile。输出中换选择只更新 UI，不调用原生接口。应用等待期间的新选择保留到下次提交，不被旧结果删除。未支持的另一 Harness 选择在 preparation 前拒绝，当前不自动替用户切换连接。
- 独立新增反例暴露并修掉“其它会话已有绑定会导致无 Profile 草稿也提前创建”的缺陷。显式取消草稿可以加入在途 preparation 后释放其独立 channel；失败释放保留既有可观察 ledger/重试入口，不静默重试。导航离开不是释放，仍保留可恢复草稿，但导航 epoch 阻止晚到 guard 发送；取消的晚到 owner 不重新写回草稿。
- 受控验证：Profile Chat 29/29、ACP 59/59、Agent Sessions 44/44、Chat 前端 61/61；Profile 前端此前 20/20。根 typecheck 和 Profile Chat 独立 typecheck exit 0；build 构建 18 扩展，lock 只由构建生成。新增两个缺陷反例已实跑红→绿，其它新覆盖与实现同批落地，不冒称全部先红后绿。尚未运行此轮 Electron 或真实模型。
- **默认产品接线缺口仍在**：桌面 launcher 当前默认使用旧 artifacts 且 Pi bridge 默认关闭；新安装增强 Pi 位于另一个 root，不能把三品牌整体指向仅含 Pi 的目录。下一步需在 Harness launch 接缝支持各绑定独立可信资产根，Codex/Claude 仍用原资产。不能将以上受控前端通过记为默认桌面 Profile 已可用。
- 固定七项待办不增加阶段：第 4 项提交接线有受控证据但默认真实产品尚未验证；第 3/5 全量资源与并发语义、第 6 两品牌切换、第 7 完整产品/用户真实对话仍未完成。main、host、用户服务和截图不动，不 push、不真实模型调用。

### 三品牌可信资产独立落位与全局 revision 修正（2026-09-30）

- 前端 preparation 检查点已提交 `c903cfaa02`。Harness nativeServerPlan 增加每绑定 artifactRoots，先按每品牌原有完整 root 管理策略验证再生成计划；additional binding 可携带 installedArtifactRoot，由既有插件装配逐绑定传给 access-entry，不夹带到 adapter argv。非法/非规范根在数据根建立前拒绝；旧未传参数的计划和受控路径不变。产品 Profile config port 取实际 Pi 绑定根，即使主绑定是 Codex，也不会用错根。
- 默认开发 launcher 在包含 Pi 时启用增强 bridge、使用用户已安装的 profile-live-model 资产；Codex/Claude 保持原 artifacts。显式 `ORDESSA_PI_PROFILE_BRIDGE=0` 可关闭，缺资产或摘要不符拒绝，不回落旧版。没有覆写安装资产，未改 host/Pacthold/用户登录。
- Node 安装策略 17/17；产品全套 48/48（含每绑定根保留及五种非法根反例）。新增 launch/root 反例在缺实现时实跑红，再修复。真实系统上下文复核三套完整资产摘要成功，生成计划实际分开两个根。
- 追加全局 Profile 在 apply 期间更新的反例，钉住旧代码将回执错误标成新版（实测 3 != 2）。修复冻结本次目标 revision：plan 后版本改变时零原生效果拒绝；apply 中更新不冒充已应用，新配置下次提交消费。另钉住 plan 期间更新零 apply/修正后重试；Profile 最终全套 194/194，Harness 模型+产品 144/144，exit 0。
- 无配置环境 `npm run test:electron` 首次仍因没有默认 /opt bundled python/bin 失败（既有环境缺口，没有隐藏）。指定此前独立开发运行根 `/tmp/ordessa-native-dev-runtime-bNpAO6zy` 并明确当前源码 PYTHONPATH 后空宿主 smoke exit 0、ready=true、errors=[]；不是发行包验收。
- 新增可复跑 `products/desktop/probe-native-installed.mjs`：完整启用清单、实际三品牌 launch plan、独立临时 HOME/数据根、测试结束清理。exit 0，rootMounted=true、errors=[]、pages=Chat/Skills/Sessions、renderer 无 Node、prompt=0。初版错误地把 smoke 的 `starting` 当插件状态（实为全部 role=status 文案），已校正输出真实业务状态：读取分配…、尚未选择项目；不据此宣称业务加载全部完成，也不记作完整对话/UI Profile 操作已验收。
- 实际安装 Pi 的 wire Profile 应用双实例探针再次 exit 0：真实 canonical/ledger、模型 first→second、独立 readback、A 不影响 B、释放 A 后 B 存活、prompt=0；自身实例完整清理。
- 下一核查是已锁定 Codex/Claude 适配器真实 API 与原生应用/readback 的复用，不把品牌纯编译器已存在当作生产 Profile 切换已完成。固定第 3/5/6/7 项仍未收口，第 4 有受控提交+实际完整产品挂载，尚缺端到端界面应用验证。

### 两品牌适配器增强的实施边界

- 独立检查实际安装的锁定源码（Claude 0.81.2、Codex 1.1.14），两者已有 provider/model ACP 操作，可以复用，不需要回到旧 Go Claude 桥或自己重写 SDK。
- 但这些资产没有 Pi 增强层目前用于 C4 的 `_ordessa/session/configuration` / application operation 回执契约，产品真实 Profile service 仍只组合 Pi。不能因 `providers/set` 返回成功就伪造 Profile confirmed；特别是 Claude `enqueueProviderUpdate` 会捕获个别会话 resume 失败、报告 session lost 后继续，让 provider 调用正常返回。
- 要完成相同验收标准，需为 Codex/Claude 在 Harness 内增补最小只读会话证据/操作结果层，直接复用已锁 upstream 的 provider/model 操作；会话 lost/readback 不符必须 Unknown/阻断 prompt。增强属于新的第三方适配器资产版本，不就地修改已安装原目录，需新目录 root 安装和完整摘要再验。
- 这是下一步中等规模变化，按用户“无法快速解决应讨论”的要求提出该路线确认；不以普通 ACK 降低标准，不把上一轮原资产安装授权擅自扩为覆写或新增强资产安装授权。已验证成果已提交 `a6138a494f`，待确认期间不动原系统资产。根 main 未切换，工作树剩余他属截图保留。

### Codex/Claude 配置证据层第一检查点（2026-09-30）

- 用户认可上述路线并要求继续。修改限定 Harness packaging：复用 Pi 的有界操作记录、幂等键、generation/digest fence、锁与独立读回逻辑；仅把 live lookup、原生 setter、选项 ID 和证据前缀参数化，Pi 默认行为保持不变。Codex 读取 upstream sessions Map/createSessionConfigOptions/activePrompts；Claude 读取真实 sessions/configOptions/turnQueue/queryClosed/providerUpdate。generation 随实际对象变更，不从用户请求制造。
- 新读回投影只包含公共 ACP selector 字段，丢弃任意 `_meta`/header 等附加信息，限制深度、条目与大小；重复 selector 拒绝。ACK 未改变实际状态、实例消失或替换后，操作仍 Unknown，query 不重执行。原生 prompt/config 和 provider/lifecycle 加锁互斥；并不因此声称已经实现 Profile 的 provider 切换。
- 构建增强采用已安装锁定 upstream 文件的精确 SHA256 + 每个源码锚点恰好一次，保留标准处理器委托，仅加证据请求及边界守卫；源码漂移拒绝。两 builder 的默认构建不启用增强，legacy Claude 禁止增强。增强在新 staging 树内、完整 digest 计算之前完成，不修改 source 或已安装资产。初次构建因 staging 复制的 index.js 本来只读而 EACCES，已仅对新 staging 拷贝暂时开放写位，再由 builder 封只读。
- 新候选资产 `/tmp/ordessa-native-profile-assets-RZnZZq`：Codex treeDigest `sha256:a41531bbdd64ca7db5fae705305fe28685a6ff100406414442b369640c253fa3`；Claude `sha256:be0eedd365fcf09b5fe265e2380649a5d39a38808141cf842588195dea4b51ee`。只是开发候选，不属于 installed allowlist，不能直接作为可信生产 Profile 资产使用。当前 manifest extension 的实例目录要求尚需接 launch enforcement，未安装、未默认采用。
- 主代理实跑 Node 定向 **90/90**（native evidence/互斥/漂移 + Pi query/operation/entry + Codex builder + 七品牌 Python digest 边界），exit 0。新增测试与实现同批落地，不冒称全部先红后绿。首次 relocated-builder 反例因缺少新 JS support module 提前失败，已补全 fixture 的 JS closure，但继续故意缺 Python kernel，以保持原门禁两项断言逐字不变；最终该门禁全绿。
- 真实增强 upstream 进程的无模型注册探针（`native-profile/probe-registration.mjs`）两品牌 initialize 成功，证据请求到达 live reader 并拒绝未创建 session；session/new=0、prompt=0。独立临时 HOME，未读取用户登录，结束清理自身进程组。这是 **registration-only**，不是模型实际切换、Provider resume、Profile receipt 或完整产品验收。候选语法检查通过。
- 新核查发现：Codex 1.1.14 的 providers/set 仅存 gateway 配置，现有 thread 的 provider 不随 setter ACK 自动变化；新建/resume 才传入 modelProvider/config。Claude 会重建 query，但 resume 丢失仍可能 ACK 成功。下一步必须实现/验证现有会话的明确恢复与实际绑定读回，不能仅靠 providers/list 或 setter 返回值确认。这个恢复边界仍在 Harness 内，不需要 host 或资源业务插件替品牌编排。
- 固定七项 TODO 不变：第 6 项仍未完成；第 3/5 全资源与全量语义、第 7 完整验收仍未完成。未重跑 Python 全量，此检查点不更新其计数。main、已安装资产、用户服务、截图均不动，不 push、不真实模型调用。

### 恢复边界待裁定（2026-10-01）

- 上述证据层已提交 `cacdffc676`。继续核查发现一个不能静默绕过的真实接缝：ProfileSessionOwner 在独立查询检测到 native generation 改变时递增应用 target 的 runtime_generation 并拒绝旧 target；NativeProfileConfigPort 缓存的端口也拒绝代次变化；C4 apply 的 native receipt/readback 明确要求仍绑定原 planned.target。当前的同代次模型 action 可以正常确认，原生 query 重建的 provider switch 则不能沿用同一个目标假装通过。
- 建议保持用户可见对话、历史、草稿与 Profile 蓝图不变；仅在后端验证同 native session 的显式 resume 成功后，走受控绑定换代，把本次旧目标操作与新运行代次的证据明确关联。旧 target 永久失效、恢复失败保留 Unknown/阻断 prompt，禁止把后台重建伪装成同代次原子 model action。这需要 Harness 应用/owner 与 Profile port 的显式接缝设计，不能偷偷弱化现有代次拒绝测试。
- 按用户对中大规模复杂决策需及时讨论的要求，停在这一接缝请用户认可后实施；不为通过测试而固定 generation、接受 setter ACK、复活旧目标或要求用户新建会话。新的系统安装尚未申请，先不让用户安装未完成生产恢复链的候选资产。固定 TODO 第 6 项仍未完成。

### 恢复边界获批与首次创建纠偏（2026-10-01，实施中）

- 用户认可同一可见对话的显式运行换代；随后指出空会话不需要恢复。前节“待裁定”状态已结束。首次创建与历史恢复分开：先准备独立适配器的 provider，再创建 native session，利用原生 model setter 与独立读回完成模型选择后才交付准备结果；不先创建默认 provider 会话再 close/resume。模型设置需要 live session，不能把创建参数或 setter ACK 视为已应用。
- Harness 新增受控恢复票据：效果前钉住旧 owner/target；完成只查询保留的 provider-resume 记录并独立读回新 generation，保持 canonical UID 和 ledger owner，永久拒绝旧 target；Unknown 不重执行。产品绑定换代清除旧 plan/port，但恢复证据不是 C4 Profile receipt，之后必须新建配置应用计划。新增 11 个 owner 反例先红后绿；原漂移拒绝与 C4 同代次规则未放宽。
- 首次创建新增 owner-only prepare/query，独立空 adapter 才能准备，保留有界幂等记录，不把凭据写入公开证据；标准 session/new 仍由原调用者发送并由后端关联应答观察。新建后原生模型设置/读回失败保留 Unknown，不再次创建。三条 JS 反例先红后绿；注册表四条初始准备反例先红后绿，拒绝共享/已有 native owner/已结束通道以及 client 直调保留方法。
- 真实增强候选 `.cleanup-evidence/native-initial-l3KElR`：Codex 1.1.14 指定其实际目录提供的 `gpt-5.5`、Claude 0.81.2 指定 `sonnet`，两品牌独立探针 exit 0。均 provider-before-new、model-before-return、独立模型读回、session/new=1、resume=0、prompt=0、inferenceRequests=0；仅本地 synthetic provider，独立 HOME/品牌配置目录，清理自身进程。这是 **native-adapter-initial-model-not-server-profile**，不是默认产品/Profile receipt/Chat UI 验收。先前写死探针模型不匹配实际目录时被原生拒绝，未把拒绝改成成功。
- 失败证据仍保留：旧空会话恢复探针 Codex 在 resume 报 native-history-unavailable，Claude 重建空 query 未确认；空会话不再作为恢复验收样本。已有真实历史的两品牌 provider 切换恢复尚未验证，不能由受控恢复单测替代。错误诊断只使用闭集阶段/原因，不打印 upstream 凭据内容。
- 当前重跑：Harness owner+action+产品测试 **102/102**、Profile 全套 **194/194**（一个既有 Starlette deprecation warning）、Node native/Pi/安装边界 **99/99**，exit 0。补了两个先红后绿守卫：拒绝 Python `True == 1` 对代次字段的类型混淆；缓存 owner 不符时在产品绑定更新前拒绝，避免半更新。root npm/全量 Server 未在本节重跑，不引用旧数字作本轮证明。日志 `.cleanup-evidence/native-initial-node.log`；两品牌实际首次创建探针日志 `.cleanup-evidence/native-initial-real.log`。
- 环境：复制候选到 `/tmp` 遇 EDQUOT（-122），改在已忽略的 `.cleanup-evidence/` 构建；未删他属文件或旧安装资产。root 仍 main，截图 `docs/ui-preview/01-empty.png` 他属修改保留。
- **固定 TODO 第 6 项仍未完成**：以上完成首次 native 配置子路径和受控换代边界；生产 Profile→准备通道→首次创建接线、Codex/Claude 的真实 C4 factory、增强资产实例隔离启动强制与可信安装、已有历史恢复验证仍待收口。第 3/5 全资源与第 7 完整产品验收也未完成，不新增“最后阶段”或冒称产品可交付。

### 首次提交语义校准与两品牌隔离入口（2026-10-01，实施中）

- 用户校准：草稿与配置选择不创建原生对话；首次提交中的 ACP `session/new` 准备运行状态，不生成用户消息。锁定源码 Codex 调用 `thread/start`；Claude 分配 ID、建立输入队列并启动 SDK/CLI，`prompt()` 才入队用户内容。不得把实例初始化等同于已有可恢复历史；不新增“空会话恢复”产品功能。前节旧探针的失败仍保留，但不作为产品需恢复空会话的依据。
- 新发现并修复的真实边界：安装验证忽略 Codex/Claude 增强 manifest 的 `extension`，可能经普通路线误采用增强资产。两个反例在旧实现上均红。新增显式 `native-profile` 路线，只接受各自锁定包/版本、精确 extension 身份、上游源摘要与完整树摘要；普通路线拒绝增强声明，不回退。
- 增强构建现在发布独立 `ordessa-profile.mjs` 入口。入口在动态加载任何上游模块前，强制后端分配的 canonical、当前用户拥有、0700、无符号链接实例目录；设置 HOME/CODEX_HOME/CLAUDE_CONFIG_DIR/XDG_CONFIG_HOME 到该运行实例，不复制用户登录或全局配置，不按 Profile 分配目录。新增四条启动测试（初始红因为入口尚不存在，不能冒称抓住旧运行时缺陷），验证不安全目录拒绝且未执行上游、合法目录在导入前生效。
- Harness 的 AccessEntryTransport 增加显式 native_profile_bridge 启动绑定，只允许 Codex/Claude 已安装路线；独立目录不进入 connect 数据，client 不能覆盖实例目录/品牌 HOME。两个 Python 反例先红（接口未提供）后绿，原 Pi 路线保持。尚未在默认产品启用这条路线。
- 新候选 `.cleanup-evidence/native-isolated-8DULMM` 从锁文件重新构建，两品牌均从隔离入口完成实际 provider-before-new/model-before-return/独立读回探针：session/new=1、resume=0、prompt=0、inferenceRequests=0，scope 仍是 native-adapter-initial-model-not-server-profile。未安装候选、未修改旧系统资产/登录、未启动真实模型调用。
- 本轮实测：Node native/Pi/安装边界 **107/107**，Harness owner/action/安装入口/实例目录/产品测试 **120/120**，exit 0；日志 `.cleanup-evidence/native-isolated-node.log` 与 `.cleanup-evidence/native-isolated-real.log`。未重跑 Profile 全套/root npm/全量 Server，不引用历史数字作本轮证明。
- **固定 TODO 第 6 项继续未完成**：增强资产隔离入口与显式可信验证已完成源码/受控验证；仍缺生产 Profile 首次准备接线、Codex/Claude C4 factory、系统资产安装及真实已有历史恢复验证。未变更 host 核心，root 仍 main，保留他属截图修改。

### 配置执行器品牌解耦（2026-10-01，实施中）

- 将原 Pi 操作绑定校验迁入 Harness 内的 NativeSessionActionExecutor；Pi 保留薄的品牌策略类，现有生产行为不变。Codex/Claude 仅允许 model action，必须匹配当前 channel 品牌和各自原生证据前缀；before digest、target、manifest、operation、generation、原生 owner 与独立读回校验全部保留。
- 新增两个品牌反例，初始红因为公共执行器尚不存在；实现后验证 preflight 零效果、正确品牌操作记录生成 receipt、Pi/外品牌证据拒绝、错误 channel 品牌在效果前拒绝。不能将此视为 C4 factory 或 production Profile 全链已经实现；当前产品 port 仍 Pi-only，不移除其安全拒绝。
- 本轮 Harness owner/action/安装入口/实例目录/产品测试 **122/122**、Profile 全套 **194/194**，exit 0（既有 Starlette deprecation warning 一条）；未重跑 Node/全量 Server/root npm，不冒称完整产品绿。以上是第 6 项生产接线的子步骤，不增加新的顶层阶段。

### 两品牌 C4 配置服务与原生创建路由证据（2026-10-01）

- 将 Pi 的 live runtime/context 抽为 Harness 内的公共实现；Pi、Codex、Claude 保留品牌版本/策略薄层。新增三品牌 factory，核对当前 C2 publication、真实 owner/target、精确 action grant 与安装版本，不增加 permission 放行凭证。产品 port 仅在显式可信品牌资产映射存在时提供对应 factory；默认装配仍只放行 Pi，未提前启用未安装的候选。
- Codex/Claude 同 provider 的 model-only C4 路径已具备受控证据：确认依赖绑定的 native operation receipt 与独立查询，重复 apply 无第二次效果，贡献/owner/配置漂移拒绝，读回不符保持 Unknown。provider endpoint、协议、凭据引用及额外请求参数改变仍拒绝，不能丢弃字段假装成功。目录不按 Profile 分配，live model action 不物化配置文件。
- Codex providers/list 是可变进程配置，不足以证明某个 thread 的实际创建路由。锁定增强代码现在在 thread/start/resume 提交前捕获非秘密配置，并与原生响应接受的 provider 身份绑定到该 thread；Claude 使用 SDK query 创建处捕获的路由。只投影安全 provider/api/endpoint/model，禁止 header、带凭据 URL、任意上游 metadata 成为公开证据。它证明原生构建接受的路由，不冒充实际模型 HTTP 请求已路由成功。
- 首次创建确认同步收紧：model 读回正确但路由缺失或不同，结果保持 Unknown；不得依据 setter ACK 或 mutable provider-list 记 observed。补 provenance、伪造 metadata、非法 endpoint、缺失/错误路由、嵌套模型目录和畸形目录反例。新测试多数与实现同批落地；不统一冒称抓住旧缺陷的先红后绿。调试时两条纯编译测试遗漏 IntentSource，及一条 route 夹具 setter 写到旧 session 对象，已修夹具使其钉住正确分支，未放宽目标断言。
- 最终重跑 **Python 417/417**（configuration_model + products/server + Profile 全套 + owner + action executor），**Node 112/112**（native/Pi/安装边界），exit 0；只有既有 Starlette deprecation warning。日志 `.cleanup-evidence/native-routing-python.log`、`native-routing-all-node.log`。一次 Python 命令误指 tests/server_acp 子目录，未运行测试，不计作门禁证据；随后按实际路径完整重跑。
- 新候选 `.cleanup-evidence/native-routing-verified-RYfWBb` 重新从锁定源构建；两品牌实际无模型首次创建均通过：provider-before-new、model-before-return、独立读回、nativeConstructionRouteBound=true、session/new=1、resume=0、prompt=0、inferenceRequests=0。日志 `.cleanup-evidence/native-routing-real.log`。仍是 native-adapter-initial-model-not-server-profile，不是 Profile receipt 或 Desktop UI 全链验收；候选尚未系统安装。
- 下一项具体缺口：首次提交准备接缝目前不携带后端 Profile 配置意图；须在独立 channel 的 session/new 之前由后端解析 Profile/provider/credential，并调用 Harness owner-only prepare。现有后置 register/apply 无法代替这一前置动作。后续凭据引用还须与可信后端注入事实绑定，不能直接删除 credentialRef 通过 model-only 校验。已有历史跨 provider 恢复、最终可信安装及完整产品验收也仍未完成。没有新增顶层阶段；main、host、旧系统资产、用户服务与他属截图不动，未 push、未真实模型调用。

### 授权真实聊天诊断与两项适配修复（2026-10-01）

- 用户授权 Codex 使用现有官方登录，Pi/Claude 使用其指定的本地 DeepSeek Key。Key 文件保持 ignored、不进提交、不输出内容；仅在内存读取并为探针导入专用系统密钥环条目，结束删除该条目。授权不等于聊天成功。
- 已验证真实 DeepSeek `/models` 返回 `deepseek-flash`、`deepseek-v4-pro`。本机代理将域名解析为 198.18.0.4，产品 endpoint SSRF 门禁拒绝；未放宽门禁或改变系统代理。诊断使用显式、临时、固定上游 HTTPS 的 loopback relay；此证据不证明直接 endpoint 的产品可用性。
- Pi 旧资产在 first prompt 前拒绝，relay HTTP=0。合成无真实凭据的请求探针定位到 extension 模型定义缺 input 等请求字段；Pi 0.84.2 的 extension 注册不使用 models.json 的默认值。新增反例先红后绿；调用方补其 generic text-model 默认字段，不宣称供应商价格/多模态/推理能力。Pi Node 测试 61/61，修正候选真实双实例创建探针通过（prompt=0、HTTP=0、凭据持久化=0）。合成请求由 undefined.includes 变成预期不可连接的 loopback 错误。
- Claude 旧资产真实请求返回 401，诊断仅输出凭据是否匹配和占位 token 布尔值；实际发出的 Authorization 是 acp-proxy，非授权 Key。一次大小写修正无效，已完整撤销，不留下试验补丁。增强构建中修正原生 provider 环境的私有 auth token 注入，固定源摘要校验不变；合成本地 `/v1/messages` 请求实证收到正确测试凭据，外网调用=0。Native Node 测试 37/37。此测试曾误把 /api/hello HEAD 当模型请求，校准后只检查 messages 请求；不把首版失败当生产缺陷。
- 两候选从原锁定源重建，旧系统资产完全不动：Pi digest `865ebdfc807f65c91bc8f674fddd57354da523cc0e6aab69f948b69f51a58ec3`（15463 entries / 64936226 bytes）；Claude digest `3ac86b9b17cbf062c7d2b7ff1e71106d7e6dd104da6f1d1f203d25b5ca3f36fb`（3443 entries / 251161770 bytes）。/tmp 构建两次遇配额错误，改用本树 gitignored `.cleanup-evidence/` 后成功，未删除用户数据。
- 新增有界、必须 `--allow-model-calls` 的后端产品探针 `products/server/scripts/probe-authorized-chat.py`，两次短消息检验同会话上下文及 Profile 下轮 model 应用；认证拒绝后立即终止并清理，不自动重放 Unknown。`--fixed-assets` 仅采用即将安装的新可信资产。它不是 Desktop UI 验收。
- **当前仍未完成真实聊天**：Pi 修正候选待 root 安装后验证；Claude 修正候选同样待安装，之前超时/401 不作通过证据。Codex 官方登录还需核对独立实例的认证接入：增强首次创建当前只支持 custom gateway，不能静默复制全局 auth/config 或冒称官方 Profile 路线可用。跨 provider 已有历史恢复、完整 UI 验收仍未完成。
- 用户下一动作：`bash /tmp/ordessa-install-chat-fixes-verified.sh`，新增 `/opt/ordessa/harnesses/profile-chat-fixes`，预先锁定完整摘要并验证 root 所有权，拒绝覆盖。之后继续真实聊天与 Codex 官方认证路线。未 push、未合并，根仍 main，他属截图保持不动。

### 修复资产安装后真实产品聊天通过（2026-10-01）

- 用户已执行安装脚本并提交两品牌完整校验输出。使用 `--fixed-assets --local-relay` 的实际产品探针 exit 0：Pi 两轮 HTTP 200、第一轮有文本回复，第二轮准确回忆随机标记；生产 Profile 初始/下轮 C4 receipt 均确认，模型 `deepseek-flash` → `deepseek-v4-pro`。Claude 两轮有文本及准确上下文回忆，Profile C4 与原生 `haiku` → `sonnet` 读回确认。Claude 上游另有一次并行请求，总共 5 次 HTTP 200。凭据匹配=true、placeholder=false；自有通道、测试密钥环条目与 runtime 已清理。
- 证据摘要保存为 `evidence/real-profile-chat-20261001.json`。**限制**：这是后端真实 wire/Profile/适配器链，不是 Desktop UI 操作；经临时固定上游 relay，不证明真实公共 endpoint 在 Fake-IP 环境可直接配置。Claude 原生两个别名可能同映射 DeepSeek Flash，未证明不同实际 DeepSeek 模型。未重复运行来补日志，不保存 Key、提示文本或会话凭据。
- 默认 Desktop launcher 与 mount 探针改用已安装的新 Pi/Claude 资产，Codex 仍用旧可信增强资产；保留显式环境覆盖。实际完整 Desktop 挂载复跑 exit 0：ready=true、rootMounted=true、errors=[]、Chat/Skills/Sessions、renderer 无 Node、prompt=0；仍只记 mount-only。
- Codex 认证核查依据官方 `https://learn.chatgpt.com/docs/app-server`：外部 ChatGPT tokens 接口存在，但实验性且要求 host 管理认证生命周期。当前增强独立实例未继承全局登录，首次 Profile 配置只接受 custom gateway，不能用 API-Key 路线冒充官方订阅。用户已裁定 **Ordessa 自己独立登录一次**，不采用只读复用现有全局登录。下一步的账号认证属 Harness 的 Ordessa 专用账号，不属 Profile；会话配置目录继续每实例独立，账号持久凭据须与目录分开，不做每个 Profile 一个完整 HOME、不复制用户现有登录、不引入假 gateway 模式。官方登录、刷新/登出、原生 provider 路由与 Profile 模型接线仍待实施验证，不能仅启动浏览器就记完成。
- 固定 TODO：第 7 项真实聊天部分现在有 Pi/Claude 的生产证据；第 4 UI→生产完整链、第 5 实际覆盖/Unknown/失败草稿场景、第 6 Codex 官方及已有历史跨 provider 恢复、全仓回归与用户验收仍未完成。不新增顶层阶段、不把两品牌后台验收当完整产品已完成。根 main 不动、未 push，保留他属截图。

### Codex 独立登录等待用户浏览器授权（2026-10-01）

- 用户选择独立登录后，已启动可信已安装 Codex CLI 0.147.0 的 `login --device-auth`，CODEX_HOME 明确为用户级 `~/.ordessa/accounts/codex`（0700），配置强制 `cli_auth_credentials_store="keyring"`，清除 API Key/访问 token 环境变量；不读取/复制现有 `.codex` 登录，不调用模型。
- 登录进程已给出官方设备登录 URL 与 15 分钟一次性码，等待用户在浏览器确认；码只向用户显示，不写文档或证据。**目前尚未登录成功**，密钥环落地、专属账号状态、独立实例认证及官方 Profile 模型路线仍待验证。不能把这个 CLI 登录操作记作产品已具备登录按钮或 Profile 官方认证能力。
- 本轮额外 typecheck exit 0；一次 Node 定向命令误指不存在的 native-server-plan.test.mjs，未执行，不记门禁通过。完整 Desktop 挂载为前节实际探针证据，不用缺席测试代替验证。

### Codex 独立浏览器登录已确认（2026-10-01）

- 用户选择浏览器登录替代设备码；结束自身设备码进程，使用同一 Ordessa 专用 CODEX_HOME 与强制 keyring 配置调用可信 Codex CLI 的普通 login。用户要求重新打开后，取消自身上一条登录，再启动新授权；未修改用户原有全局登录。
- 用户完成授权后，登录进程退出码 0，输出 Successfully logged in；独立的新进程 login status 退出码 0，输出 Logged in using ChatGPT。凭据内容未读取或输出，未调用模型。认证由强制系统密钥环配置管理。
- 这只确认 Ordessa 专用账号登录及跨进程读取成功；尚不证明每会话独立适配器已接入该账号、自动刷新/登出已完成，或 Codex 官方 Profile 路线与真实聊天已通过。固定 TODO 第 6 项继续未完成；下一接缝为专用账号认证向独立运行实例的受控接入，不复制全局 .codex、不把账户目录用作会话配置目录。

### Codex 专用原生账号读取通过，独立实例认证接缝待裁定（2026-10-01）

- 使用可信已安装 CLI 0.147.0 在 Ordessa 专用账户目录启动自有 app-server，initialize 后请求 account/read(refreshToken=true)。探针 exit 0：authenticated=true、requiresOpenaiAuth=true、modelCalls=0；退出自有进程。仅输出布尔值，未输出 email、账号 ID 或凭据；requiresOpenaiAuth 表示原生提供者需要官方认证，不是未登录。
- 核对最新官方文档 https://developers.openai.com/codex/app-server/ 与锁定原生 schema：chatgptAuthTokens 接口为实验性外部认证，明确由 host 提供 accessToken/chatgptAccountId 并响应 account/chatgptAuthTokens/refresh；在外部模式 account/read(refreshToken=true) 不负责刷新。当前增强实例的 CODEX_HOME 为独立运行目录，首次准备仅 custom-gateway，不可将专用账户登录成功当作这些实例已有认证。
- 建议 Harness 内增加集中账号认证服务：原生管理进程使用专用账号与 keyring 维护登录/刷新；只有此服务私下读取自身专用密钥环认证并向独立会话的原生外部认证接口交付短期 token，刷新请求串行处理。禁止复制全局登录、复制 refresh token 到会话目录、把账号目录作为会话 HOME、把凭据放入 Profile/公开 wire/UI/证据。认证失效拒绝新发送并请求重新登录，不自动重放 Unknown。
- 这是认证生命周期的中等规模接缝，遵照用户要求先报告设计决策再实施。尚未读取 token 或调用外部 token 登录接口，未实现账号代理/刷新协议；固定 TODO 第 6 项仍未完成。Profile 官方模型路由及三品牌产品验收仍须后续实证，不改变顶层 TODO 数量。

### 单官方账号 + 独立 API 进程混合实测通过（2026-10-01）

- 用户裁定：暂不支持多官方账号，同时维护一个官方账号即可；每进程配置独立，且允许另一个进程不用登录而采用第三方 API。请求“测试可行即通过”，本节据真实结果收口该架构决策，不再重复索取相同审批。
- 新增可重跑探针 `plugins/harness/packaging/native-profile/probe-codex-mixed-auth.mjs`。实际安装的 Codex 0.147.0 原生 app-server（官方账号）与 Codex ACP 1.1.14 增强入口（API 实例）同时运行；原生进程显式 keyring 配置，API 实例在独立 HOME/CODEX_HOME 中以合成凭据配置拒绝推理的本地服务。不输出账号身份或凭据，不读全局登录。
- 混合探针 exit 0：官方 account/read 为 chatgpt；API 设置前为 unauthenticated，设置后为 gateway。创建两个探针原生 thread，官方 thread/start/read provider=openai，API 独立配置读回的 construction provider=custom-gateway、endpoint 与合成对端精确匹配。官方 reasoning=low、API=high；API 改为 medium 后同 generation 读回确认，官方 config/read 仍 low，官方 thread provider 仍 openai；最终官方账号元数据逐值不变。API 私有目录扫描无合成凭据落盘。
- 方法白名单禁止 prompt/turn 与任何账号登录、登出；modelCalls=0、providerHttpRequests=0。官方 thread 使用 ephemeral，结束仅 unsubscribe 自己创建的 thread；API session/close，两个自有进程组与本次临时目录清理。不会退出或修改用户既有会话。结果摘要 `evidence/codex-mixed-auth-20261001.json`。
- **边界**：这验证原生官方认证 + 已安装 ACP gateway 的混合可行性，不是两个完整 Desktop/Profile 会话的生产证明；第三方对端为合成服务，未证明供应商 Responses API 实际兼容或真实聊天，未测试 token 过期并发或全部 Skills/MCP/资源文件隔离。故固定 TODO 第 6 项仍未勾选。
- 新发现并明确的接线要求：缺省 Codex login status（未指定 credentials store）报 Not logged in，而显式 keyring 的原生账号查询成功，属于存储配置不一致，非登录丢失。官方 ACP 启动必须显式使用 keyring；当前安装的 startCodexConnection 未注入该启动参数，增强入口也强制实例 CODEX_HOME。生产接线需在 Harness 内新增官方账号作用域与显式 keyring 启动分支，API 分支原隔离不变；不使用内部 token 接口、不修改 host、不复制登录、不在共享账号目录调用 API 登录或登出。
