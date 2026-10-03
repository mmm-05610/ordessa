# zcode启动与子代理配置

## R7正在实施时的更新

读frontend-infrastructure-update.md及contracts/frontend-infrastructure.md；从主树按差异合并R7，不覆盖本树status/evidence/完成标记，不reset当前切片。008/010/012新增15任务及A96–A111；008增量冻结F5，不重开002。原12单依赖和权限不变。


R6开工前强制读compat-retirement.md：不创建永久legacy-compat插件；002逐符号台账，006/007/010拆业务，012核A95的C95-1–7。R6已融入当前执行包，开工核对本分支最新方案检查点，不能仍按8d4bc64旧目标树实施。原源快照历史不改，当前方案不是新产品测试证据。

2026-10-03。用户明确允许新建worktree/026-open-environment-migration：产品已提交源码加核对后的源码/测试/清单修复及024–026方案，排除截图/凭据/运行数据/生成物；提交仅新分支，不改源树/main。基线准备不等001测试验收完成。

## 目录与启动词

目录：/home/maoqh/projects/ordessa/worktree/026-open-environment-migration
分支：codex/open-environment-migration
来源：产品7951bf06a258d2dc41402556eb61319b8bab5cbe，包含main b4bf7cd90951d0fa9bcf3a3de2e66b7db6a62aa0；导入文件见evidence/prepared-source.json。排除改动截图、.zcodeignore、key.txt/token/.env/私有ZIP/用户数据/生成物，不读秘密正文。

本次许可覆盖准备和本地基线提交，不等于所有运行许可。由用户在新会话粘贴以下启动词授权编码。原AGENTS保留；仅对已批准来源冲突按此记录纳入现Profile/Provider，不把旧“外仓”说明当排除许可。其他import/数据/秘密/服务约束仍有效，AGENTS更新需具体确认。

~~~text
在本实施树按specs/026-open-environment-migration/README.md完成001–012迁移；这是本分支编码和本地检查点提交许可，不是用户应用或真实模型运行许可。
先读README、charter、decisions、execution-detail、compat-retirement及zcode-handoff，核prepared-source与HEAD，完成001测试发现/受控基线后依赖推进。
单Pacthold、Workbench入frontend、领域单状态owner、品牌适配归Harness，不重做原生业务。
你唯一维护契约/Git/status；子代理只用于明确独立任务，报告由你复核；记录任务ID、测试、SHA和缺口。
S/I与反例齐才解锁下游；U/P未验不报DONE，未知不重发，不删断言求绿。
不改源树/main，不push/合main/写真实数据/安装/重启用户服务；真实凭据/模型另许可。
检查点后继续ready任务；硬性语义决策写选项，继续独立项；无可推进项交回，不空转。
~~~

## 五个可照填岗位

项目作用域优先（界面若仅有用户级也可，但提示词限定本任务）；全部开启注入AGENTS.md。显式选模型，不用继承默认。

| 名称 | 模型 | 工具勾选 | 描述 |
| --- | --- | --- | --- |
| repo-scout | mimo-v2.6-flash；未添加时glm-5.3-flash | Read/Grep/Glob | 查路径、消费者、测试入口 |
| architecture-reviewer | kimi-k3 | Read/Grep/Glob | 审职责、唯一状态、公开接入 |
| safety-reviewer | mimo-v2.6-pro | Read/Grep/Glob | 审未知、并发、权限、数据、退出 |
| slice-worker | glm-5.3-flash | Read/Grep/Glob/Edit/Write/Bash | 改明确指定的独立小切片 |
| test-author | deepseek-v4.1-flash | Read/Grep/Glob/Edit/Write/Bash | 写指定正反例和受控夹具 |

前三个不勾Bash/Edit/Write：Bash不是只读权限，提示词不能技术上把它变成只读。命令由主代理运行。后两个Bash有广泛系统能力，勾选不是安全沙箱，需受信任务/限定路径/主代理复核。全体不勾TodoWrite/WebSearch/WebFetch，本轮进度和研究由主代理负责。

### repo-scout系统提示词

~~~text
只读调查主代理指定范围。读适用AGENTS与026方案，返回路径/行号/消费者/测试入口/遗漏，区分源码事实与未验证。
不读秘密或用户数据，不运行命令、不写文件、不改方案、不派子代理；完成指定问题即返回，不轮询。
~~~

### architecture-reviewer系统提示词

~~~text
只读攻击指定改动：单Pacthold、唯一领域状态owner、原生内部不重做、插件可选、公开接口与依赖方向。
返回严重度、文件/行号、具体反例、最小修正；不写文件/运行命令/读秘密/派子代理，有限审查后返回。
~~~

### safety-reviewer系统提示词

~~~text
只读审未知不重发、并发准入、撤销晚回调、持久引用、秘密、schema及退出恢复，给失败窗口/文件行号/反例。
不重新设计产品，不写文件/运行命令/读真实数据或凭据/派子代理；检查指定范围即返回。
~~~

### slice-worker系统提示词

~~~text
只实现主代理给定路径与验收条件，先读AGENTS及026工单。不改其他切片、契约、清单/lock、status或Git，不改产品语义。
不读秘密/真实数据，不安装/启动用户应用/调用模型/派子代理；只跑获准受控测试，返回改动/测试/缺口即停止。
~~~

### test-author系统提示词

~~~text
只在指定测试/夹具路径写正例、反例及缺条件场景；不改产品实现，不删旧断言或用skip求绿。
不改契约/清单/lock/status，不做Git/读秘密或真实数据/调用模型/派子代理；测试须取得主代理运行槽，返回证据/未跑项即停止。
~~~

## 调用纪律

默认主代理加最多2子代理，一段任务一次调用，完成即释放，不常驻。全树一个测试运行槽，Electron/构建/安装子进程串行，避免内存满。

现工单parallelism:none维持核心实现串行，只读调查/审查可独立。两个写入岗位先配好默认不调用：牵头者按charter获允许的独立单元后，明确不交叉路径/禁止项/证据再用；不能用此表自动开全仓并行。Git/契约/manifest/lock/Store事务/dispatcher/status始终主代理唯一写者。

scout优先窄扫描；002/004/010/012关键接缝才调用Kimi或MiMo择一复审，不每小提交双审。同一问题重复两次无进展，写反例/阻塞，不无限重复。主代理必须复核子代理报告并复跑必要门。

## 模型事实与建议分开

查阅日期2026-10-03。以下官方定位不是zcode实际横评；岗位分配是本任务建议。

| 模型 | 已核对的差异 | 建议用途 |
| --- | --- | --- |
| GLM-5.3 | 官方强调复杂编码/长任务 | 主线整合 |
| GLM-5.3-Flash | 效率导向新基座，不只是减思考；多模态 | 狭窄机械切片 |
| Kimi K3 | 报告声明原生视觉、1M上下文、长任务编码 | 不同家族架构审查 |
| MiMo-V2.6-Pro | 官方原生多模态，更高能力定位 | 高风险复审 |
| MiMo-V2.6-Flash | 同系列效率定位，官方多模态 | 扫描与简单改动 |
| DeepSeek-V4.1-Flash | 官方原生视觉、速度/吞吐改进 | 正反例助手 |
| Space Bunny Free | 官方隐藏身份、限时免费；真实底模未公开 | 非关键探索，不最终验收 |

来源：[GLM官方仓库](https://github.com/zai-org/GLM-5/blob/main/README.md)、[Kimi技术报告](https://arxiv.org/abs/2607.24653)、[MiMo发布](https://mimo.mi.com/docs/en-US/news/latest/v2-6)、[DeepSeek官方更新](https://api-docs.deepseek.com/updates/)、[OpenCode Go](https://opencode.ai/docs/go/)、[Zen说明](https://opencode.ai/docs/zen/)。

截图MiMo-V2.6-Pro/Space Bunny显示200K，其余多为1M；不据原厂上限擅自提高路由配置。新增MiMo Flash先核提供商元数据，不盲填1M；图片标签不等工具能读图片或路由已测。没有执行模型调用或改zcode配置。

Go按模型分别计算额度，GLM-5.3/Kimi K3比Flash更紧，不能全队继承主模型。GLM官方reasoning_effort支持low/high/max，但Go/zcode透传尚未验证；若明确支持，主线建议high、复杂边界max，不声称已生效。

没有读取Key/改Go控制台/启用超额余额。429记录模型与任务，允许备选只换公开兼容ID；不循环猜模型重试。Space Bunny免费和公开声明不能推定永久可用或真实身份。
