# 当前服务适配事实与缺口

2026-09-27 只读依据：platform-frontend 的 `plugins/agent/contracts/src/agent.ts`、`plugins/agent/sessions/src/model.ts`、conversation view/interaction-card、Workbench API、C7 api。活动树会继续变化，实施时必须绑定最终 SHA。根 main 的契约路径与 C 树不同，不把本文件当成根 main 已迁移完成的证明。

## 1. 可直接适配

| 当前公开数据/操作 | Chat用途 | 不允许的推断 |
| --- | --- | --- |
| AgentMessage id/role/text/reasoning/tools/status | 正文、思考、工具展示快照 | 没有 event sequence，不能恢复文本/思考/工具的精确交错顺序 |
| AgentToolCall id/name/arguments/result/status | 通用工具摘要/详情；安全文本格式化 | name 不证明品牌/命令语法；completed 不由 permission approved 推导 |
| runs 的 starting/running/stop-requested/completed/cancelled/failed/unknown | 标题状态、发送/停止可用性 | stop Promise resolve 不等于 cancelled；断连不等于结束 |
| interactions pending/responding/resolved/expired/unknown | 既有审批/输入 UI；状态锁定 | resolved 不证明工具执行成功；不知道的答案类型不能自己拼 |
| options value/values/availability + setOption | 既有模式/模型选项呈现 | 不等于完整 provider/model 双维配置；不自造供应商目录 |
| sessions/sessionList/openSession/refreshSessions | 已有列表、加载/部分/错误、明确恢复动作 | 接口存在不等于每个 connector 支持，仍看 capabilities 和结果 |
| workspaces + draft + start/discard/selectWorkspace | 项目门、草稿目标、发送约束 | 未验证项目不允许创建通道；缺身份不复用其他 Server 的项目 |
| send/stop/respond | 沿用真实业务动作 | 不通过 UI timeout 标成功、不自动重试未知结果 |

消息 key 至少按 connection/server/session 范围与 message/tool ID 组合；调用业务时保留其原始身份，不用拼接显示 key 当后端 ID。实际多通道 ref 若在最终服务 API 中存在必须直接使用，不能降回 nativeSessionId 单字段。

## 2. 现有缺口与 v2 补齐责任

v2 已将命令面板和附件完整链路纳入目标；下表“诚实呈现”仅描述接缝补齐前的行为，不是整批完成条件。S1 必须补齐或将整批标为 PARTIAL，不能以缺服务为由永久只做禁用按钮。新观察的 platform-frontend `3411401795` 仍有 send(text)/send(sessionId,text)，未因此推断其所有传输能力。

| 缺口 | 这一批的诚实呈现 | 后续所有者 |
| --- | --- | --- |
| 无统一消息块序列；reasoning 是字符串 | 保留既有消息内分区顺序，称为快照展示而非原始时间线；不复制 ZCode V4 grouping 去猜 | 会话/协议投影服务 |
| 无 reasoning 独立状态/精确耗时 | 没有证据时 unknown/无耗时；仅父消息状态不能证明思考刚结束；本地“正在输出”与执行终态分开 | 会话服务 |
| 无完整 command catalog/调用面 | `/` 可作为普通文本输入；不显示伪原生命令菜单 | Harness/会话服务 |
| 当前 send 只收 text，无附件发送契约 | 不启用拖入/上传按钮；已存在可显示资源另按授权 | 会话/资源插件 |
| fields 只提供有限 choice/text 信息，缺完整多题输入 schema | 保留已支持 choice/confirm/input/editor 的现有语义；不预设必填/多选能力 | 交互协议服务 |
| 无权威 harnessId/provider 目录 | 标识缺席就缺席；不从名称猜，不显示貌似可用的切换器 | Harness/model-provider |
| 无结构化命令/diff 元数据 | 所有工具先 generic；仅已验证结构化字段启用 CommandTool/Diff | 协议投影/领域插件 |

这些不是让 UI 批次停工的理由：先做好显示 DTO、独立 fixture 和现有能力适配。真实联调不具备的增强能力列为未接入；不能 mock 通过后在产品中宣称已经实现。

## 3. 发送与陈旧目标

当前 AgentSessions 有选中会话隐式路由；send Promise 不是新设计的 acceptance 三态协议。展示层沿现有服务语义保持失败/未知草稿，不把历史报告中的另一版 seam 接口臆造成现有 API。

UI 捕获 draft/session 身份与内容版本；异步成功回来只清理对应的已发送版本，不清掉用户后来输入的文本，不影响已切换的新会话。submit 在捕获目标后到调用前若目标已变，拒绝旧动作；不能替插件把选中会话切回去执行。

旧审批仍须由服务校验归属；Chat 按非 pending 禁用只是额外 UI 防线。公开配置贡献需要目标化服务时列服务缺口，不创建能越权操作全局配置的万能回调。

## 4. 旧代码/测试迁移纪律

展示复用与物理合包分开：先列旧 conversation/sessions 文件和测试的最终所有者，服务模型不得因为在 sessions 目录就搬进 Chat UI。保留原 plugin/view ID、用户数据和动作语义；需要改变时按命名/迁移规则独立裁决。

先从已审 C 平台版本识别已迁出的测试，不能再把主树旧路径复制回来。关闭旧组件链前运行原 ID 反例及新浏览器证据；原实现不与新实现同时注册同一视图。正常安装不自动启用新插件，产品装配显式选择。
