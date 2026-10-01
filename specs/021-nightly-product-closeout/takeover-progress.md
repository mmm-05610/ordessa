# 2026-09-30 接手检查点：启动接缝与 Profile 管理

状态：部分实现，**不是完整 Harness Desktop 验收通过**。
所有改动在 `nightly/021-ordessa-product-closeout`，根工作树保持 main。
未合并、未 push、未启停用户服务、未调用真实模型、未重建 deb。

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
- [ ] 后端 canonical Profile 会话注册与真实 owner/generation 完整生产绑定。
- [ ] Chat 首次/后续发送前应用接线，不打断正在输出的 Agent。
- [ ] 实际应用链验证全局预设/逐项临时覆盖/失败草稿/未知结果语义。
- [ ] Codex、Claude 实际切换与跨 provider restart/resume、多会话隔离。
- [ ] 产品完整回归及用户授权的真实聊天、配置切换验收。

### 支持矩阵实测（源码审计，不冒充原生应用证据）

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
