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
- 建议裁定：配置计划授权归 Permissions 插件，产品模块只组合真实 canonical owner、Profile 配置端口、模型解析器、C4 与权限提供者；不在 product 私造第二套 default-allow 权限。普通 provider/model 配置以已认证用户的显式选择和提交为意图，不新增审批弹窗；涉及权限扩张仍受平台上限约束，绝不由 Profile 选择自动赋权。这个新配置授权接缝尚未实现，待用户确认；无需改 Server/Pacthold/前端 host。
- 若按建议执行，后续有序切片为配置授权→canonical 注册/生命周期→模型 action 映射及独立观察→Chat 首发 session/new 后、prompt 前和后续 submit 应用；凭据/provider restart-resume/Skills 保持各自独立验收，未知或不支持仍明确拒绝，不降低总验收标准。当前暂停在这个设计裁定处，不声称整批完成。
