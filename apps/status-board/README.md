# Ordessa 工作侧窗

独立窄幅状态界面，复用现有 Electron 40 宿主的安全基线、preload、ServerBridge 和生命周期。完整工作台仍按原命令启动；`--status-board` 选择单独侧窗，不先创建工作台窗口。宽度 390px，可调至 360–420px；标题栏可拖动，边缘可调整大小，支持收起/恢复和可选置顶。

从仓库根目录运行：

```sh
npm run build
npm run start:status-board
```

`start:status-board` 直接启动 Electron，没有 `--no-sandbox` 或其他安全绕过。与工作台共享原单实例规则：若已有 Desktop 实例运行，二次启动聚焦既有窗口；本轮没有增加跨模式多窗口调度。构建前可用 `npm install --ignore-scripts --offline` 接入新增本地 workspace（本轮已执行）。产品 Server 仍需现有桌面支持的运行时与数据根配置；不自动连接/重启其他会话的服务。

仅查看浏览器界面：

```sh
npm run dev:status-board
```

打开 Vite 输出的本机地址。浏览器没有宿主 WirePort，明确显示未连接；不会自行读取令牌、连接猜测端口或扫描数据库。页面为单列布局，适合 390px 宽。此命令验证界面，不代表后台接通。

检查：

```sh
npm run --workspace apps/status-board typecheck
npm run --workspace apps/status-board test
npm run --workspace apps/status-board build
npm run --workspace apps/desktop typecheck
npm run --workspace apps/desktop test -- tests/status-board-window.test.ts tests/host-main.test.ts
```

## 已接入和缺口

- 真实服务发现：通过现有主进程 WirePort 调用 `server.hello`，参数 `clientVersions: ["wire/1"]`、`clientPresentationSupports: []`。只展示实际返回的实例和能力数量。身份、令牌和 HTTP 请求留在主进程。
- Work 工作汇总、已记录目标结构、Work 详情及可信确认：当前公开 owner 查询/确认未接通。正常启动显示数量未知和明确不可用，不用空数组伪装读取成功，不内置夜间文档或任务样例。
- `BoardSource` 是显示投影的显式注入接缝，不建立另一套工程权威。生产 `composition.ts` 没有绑定 Work 源；Engineering 精确原记录查询使用独立读取接缝，不代替它。详见 [owner 接口请求](owner-interface-requests.md)。步骤从每条记录的绑定方法读取，不固定 DID/spec-kit。
- 断连保留最后成功读取和时间，标记过期，不把断连当任务失败。刷新不并发重复；变更操作不自动重试。确认先刷新比对版本/范围/快照，最终原子比对必须由可信后端执行。无该后端时按钮禁用。
- 详情打开时保留所读版本；返回保留各视图滚动和结构展开。执行结束、审核、批准及验收状态分开呈现。

## 本轮验证边界

2026-10-11：界面 9 项测试、类型检查与独立构建通过；桌面侧窗/宿主 55 项测试通过；原 server-bridge 测试组 135 项通过；完整桌面类型检查与产品构建通过。测试 fixtures 只在测试文件中存在，不进入正常入口和构建。

实际浏览器已检查 390px 概览、结构、工作及收起恢复。截图在忽略目录 `.nightly-cache/status-board/evidence/`；详细记录见 `docs/implementation/nightly/evidence/W13/local-side-window-20261011.md`。本机 Electron 以独立临时数据根、沙箱开启启动，15 秒观察期间没有启动致命错误；观察结束仅停止本次新建进程。工具没有原生桌面访问能力，未验证真实 Electron 拖动/边缘调整/置顶交互，也没有取得真实 Server 返回或工程工作数据。不能据此宣称整产品或可信确认验收通过。

共享根配置只新增两个 workspace 和两个启动脚本；新增三个本地 workspace 由离线 npm 接入。lockfile 同步当前树已经迁移的 workspace 元数据，保留既有依赖版本，不涉及 Python 安装环境。现有工作树改动保留，没有 commit/push/merge/reset/clean。


## Engineering 精确查询接入（2026-10-11 后续检查点）

“工作”视图现在提供 `engineering.capabilities` 和六项精确查询：artifacts.get / references.resolve / proposals.get / proposals.get_control / changes.get / commands.get。填写实际 Realm/Project，选择查询并输入已知 ID 或完整引用 JSON。引用对象完全来自实际 owner，不在界面填默认引用或示例记录。材料/提案详情按原字段显示，保留原返回 envelope；提案的审核要求不是审核结果，命令的 Accepted/status 不被推导为完成或验收。

客户端验证 `engineering-wire/1`、返回 scope、query 与 record_type；commands.get 保留原 request_id/authority_id/operation_id/status/result/status_query。拒绝、不存在和未知不是空成功。后续失败保留最后成功读取时间与原数据并标记过期。

默认 Server 不一定配置 Engineering grants。连接已有局部 Server 时，由可信启动器同时提供：

- `ORDESSA_STATUS_BOARD_SERVER_ORIGIN`：实际 listening 握手给出的 loopback HTTP origin，不能携带用户名、密码、路径、query 或 hash。
- `ORDESSA_STATUS_BOARD_SERVER_DATA_ROOT`：该 Server 的绝对数据根，主进程按原共享布局只读其机器 token。
- `ORDESSA_DATA_ROOT` 与 `MODULAR_USER_DATA`：侧窗自己的独立目录，不能与 Server 数据根相同。

以上配置进入进程环境，不写 `.env`，不把 token 给 renderer。不提供配置时沿原桌面 ServerBridge 启动路径；提供不完整或无效配置时拒绝，没有其他服务器回退。显式连接模式不会启动/停止所连 Server，也不会修改它的数据库、身份或 grants。侧窗主进程 wire IPC 只允许上述七项 Engineering 读取和 server.hello；写操作在侧窗模式拒绝，完整工作台保持原权限入口。

新增检查：界面/适配 20 项、侧窗连接/原宿主 63 项通过；类型与完整产品构建通过。浏览器实际验证了精确查询表单和没有宿主时的 port-absent/Unknown。本轮未获实际局部 Server 地址、data-root、scope 与具体原记录引用，没有冒称获得真实记录截图；完整真实数据库往返待父任务集成验证。详见 `docs/implementation/nightly/evidence/W13/engineering-exact-queries-20261011.md`。


## 真实只读联调检查点（2026-10-11）

接入新增 owner 查询 notices.get、approvals.get / get_control / get_intent / get_challenge / list_pending。它们显示权威原 envelope；待确认记录不转换为 Work。list_pending 输入分页 JSON（limit 为 1–100，after_challenge_id 为字符串或 null）。没有新增确认、批准、撤销或执行入口。

可信启动器可额外设置 `ORDESSA_STATUS_BOARD_TOKEN_LOCATOR`，仅主进程读取该绝对文件，位置必须在显式 Server data-root 内；不设置时使用已有共享 token 布局。此配置用于已有机器身份，不能证明真人授权。

真实 SQLite→HTTP→共享 TS client 联调读回九个成功查询（能力、两种引用、新增六项），不存在的 Artifact 返回 Refused。实际 390 CSS px 浏览器浮窗 renderer 通过隔离只读验证宿主读到 ConversationNotice / ApprovalGrant，并返回保留输入。宿主只代理实际 HttpWirePort，未制造返回；页面明确标记 seeded read fixture、无真人批准、非产品验收。该宿主位于忽略目录，不进入正常启动。证据见 `docs/implementation/nightly/evidence/W13/real-sqlite-query-20261011.md`。

最新应用测试 26 项、桌面相关测试 67 项、两侧类型检查及完整产品构建通过。此前检查点的“未得到真实 Server”说明是历史状态；本次 seeded 查询成功仍不构成真实工作数据或真人批准验收。

## 原审核请求读取（2026-10-12）

新增 `engineering.reviews.get_request`，参数为原 `review_id`，外层继续使用明确 realm/project scope。原返回 `ReviewRequest` 的 `data.request` 与 `data.plan` 分别显示；保留原 state/version/fence、plan_digest 与完整 CheckKey，不创建第二份 pending 状态。默认 machine 身份没有自动新增读取 grant，部署须显式选择；Refused/Unknown 不当作成功。

JEV Artifact 与 ManualReviewCapture pending Q&A Artifact 都不等于完整 formal ReviewRecord 或 Grant；dispatch completed 仅是 ACP 完成，quarantine 不是 accepted。查询入口与详情均显示此限制。实际待审核步骤由 owner 的 `docs/implementation/ordessa-v1/pending-review-flow.md` 交接，不在前端实现审核或批准判定。

本次应用 31 项、桌面相关 68 项测试，两侧 typecheck 与完整 build 通过；浏览器核验了新入口及 port-absent 状态。本轮未提供有效的新增只读权限服务交接，未声称已在 UI 读回真实 Zen review。详细证据 `docs/implementation/nightly/evidence/W13/review-request-read-20261012.md`。

后续真实检查（2026-10-12）：已沿现有 desktop HttpWirePort 读回同原 Zen request，requested/version0/fence1/full3keys 与原 owner projection 逐 JSON 相等，原库 SHA 不变。实际窄幅同窗 renderer 已显示原 request/plan并验证返回输入，安全 Electron 附着启动通过。浏览器验证宿主明确标记非 Electron IPC；工具 apps inventory 为空，原生 preload/IPC详情操作仍未验收。详见 `docs/implementation/nightly/evidence/W13/original-zen-review-display-20261012.md`；先前“缺有效服务交接”为历史状态。
