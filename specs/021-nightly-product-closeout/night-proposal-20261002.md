# 今晚有限任务 — 范围已确认，启动交接见末节

主任务收口 Pi/Codex/Claude + 可选 Profile、核心职责盘点及内部整理；
全通过后可推进已有资源插件接线。不扩新 Harness，不重新跑旧无限目标。
复用当前工作树。建议一个 ZCode 执行者；Codex 不常驻值守。完成指定条目即
交报告停写；需要 sudo/账号交互/产品语义裁决则记录该项阻塞，转做无依赖项。
不自动建树、发会话或设定自动化。

## 任务顺序与验收

### N1：定位并修复 Profile 逆向切换 unknown（最高优先级）

1. 用合成凭证和隔离数据复现：Profile A 模型→单独模型 B→再次选 A→发送前准备。
2. 分段核对 native registration RPC、operation record、owner、generation、
   input digest、configuration digest、credential binding；指出第一个失配条件。
   诊断仅输出白名单条件码，绝不写原始 RPC/凭证/认证摘要到公开日志。
3. 修复仅限我们的接线/状态/适配扩展；品牌差异留在 Harness，Profile 不成为
   必选依赖，model-provider 不解释品牌内部实现。
4. 同一测试修复前失败、修复后成功：既有 owner/session 上可按上述顺序准备；
   模型及上下文身份不被偷偷替换。原始凭证不持久化。
5. 反例：foreign owner、generation 改变、错误摘要、原生拒绝、reply 丢失，
   均不得产生 confirmed/发送许可；unknown 不重放配置操作或 prompt。
6. 若需新系统资产：锁定依赖离线构建、完整摘要、真实适配器零推理探针；
   准备追加安装脚本，保留旧目录。缺 sudo 停在 INSTALL_REQUIRED，不能用可写
   开发资产绕过信任。不改用户 recovery，也不把未来修复视为旧操作成功。

写权：Harness configuration/model 与 Pi 包装、model-provider server、Profile
应用接缝、products/server 薄装配及对应测试；不改内核/平台或上游 Agent 内部。
终态：IMPLEMENTATION_REVIEW_READY / INSTALL_REQUIRED / PARTIAL_BLOCKED。

### N2：独立补齐模型/Profile 交互回归（可与 N1 分文件并行）

1. Profile→模型、模型→Profile、只有 prompt 的 Profile 不改模型，逐项后操作覆盖。
2. 模拟 running 时选择：不 cancel、不 interrupt、不启动第二次 prompt；下一次
   明确发送才应用。普通打字/光标移动不得 query/reconcile/apply/submit。
3. 两个会话交替选择与迟到响应：只更新原目标，另一个的配置/草稿不变。
4. unknown/refused 保留草稿；编辑不导致告警闪烁、重复发送、队列清空；真实运行
   completed 仍触发必要核对。读回失败不把历史回执当当前事实。
5. 增加复现型反例测试并跑 model contribution、Profile Chat、Chat 回归；必要
   时用隔离 Electron 截图，标 fixture，不伪称用户数据或模型端到端。

写权：model-provider Chat contribution、Profile Chat integration、Chat 前端及
对应测试。与 N1 后端写权分离；共同报告只由主执行者写。
终态：CONTROLLED_UI_VERIFIED / PARTIAL_BLOCKED。

### N3：三品牌装配回归与明早报告（依赖 N1/N2 交付）

1. 验三品牌系统资产，默认产品 18 扩展构建、typecheck、边界与受影响套件；
   按测试 ID 对比新增失败，不通过 skip/删断言/伪造 readback 得到绿。
2. 使用隔离数据验证 Profile 缺席仍可普通聊天准备/模型选择，实际 route 不依赖
   Profile ledger；明确不存在自动建全局 Profile 的旁路。
3. 汇总逐条状态、命令/退出码/测试数量、检查点 SHA、待安装脚本及明早用户步骤。
   若未真实调用模型则明写“真实聊天未验收”；不发布“产品全部通过”。

## 边界和费用

- 默认零真实模型调用；旧 key.txt 不读、不提交。需要真实调用另请用户定数量上限。
- 不碰用户 ~/.ordessa、登录、密钥环和全局 Harness 配置；隔离临时数据用完登记。
- 不启停当前用户窗口，不 push、merge main、清工作树、改其他分支。
- 建议最多一个执行者 + 两个互不写同文件的子代理，禁止递归派生。
- 不追加其他 Harness、协作、通用引擎或整夜无限巡检。完成下列限定队列，
  或全部剩余项需用户协助时交付停写，不为填满一晚制造任务。
- 用户已确认 N1–N3、N4，N5 为前置全部通过后可推进的补充范围。
  建议单执行者最多两个分文件子代理，真实模型调用尚未授权。

## N4：核心盘点→内部整理（用户批准，接口迁移不在内）

先完成 core-boundaries-small-refactor.md 的 R1，再做 R2：

1. 列 platform/workbench/server/pacthold 的公开入口、实际消费者、注册 owner；
   更新架构事实，分开职责图与依赖/装载图。两套 Settings 入口是否指向同一
   实例须有源码证据，不能据名字直接合并。
2. 报告现有边界问题及具体路径，新增跨层错误引用的反例；合法 Server 使用
   Pacthold 不算违规。无需人为消除使用依赖来追求图上平级。
3. 仅 Workbench 内部按已有稳定责任整理布局/导航/浮层/设置模块；保留所有
   公共 API、Token 单实例、extension id、加载与释放行为，导航/关闭/焦点/设置
   草稿行为回归通过。无法证明行为等价则只交盘点，不强行拆分。
4. 不迁移公共契约，不重命名包/目录，不合并两套后端宿主，不引入新注册表或
   兼容链，不改数据格式。R3/R4 仅列建议，留用户审核。

R1 可与 N1/N2 只读并行；R2 在 N2 同路径修复完成后串行。涉及上述只读范围
的 AGENTS 已批准；读各局部指令，不把整理扩大为核心行为重构。
终态 CORE_INVENTORY_AND_INTERNAL_CLEANUP_REVIEW_READY，或 PARTIAL_BLOCKED。

## N5：全部前置通过后，已有资源插件接线（可选补充）

门槛：N1–N4 实现/受控证据均就绪，且没有 INSTALL_REQUIRED 或硬性阻塞。
不要求冒称明早真实验收已通过。前置未满足，禁止转做本项逃避主问题。

按 Skills→MCP→Prompts 顺序，每个先读已批准 spec、当前插件与 Harness facet：

1. 列资源插件注册/存储/Profile 配置贡献/解析/实际 Harness adapter/产品启用
   链路，指出一个真实断点；已经接通的不重做。其他资源仅盘点，不自动扩展。
2. 只接现存批准契约与现成 facet。没有 adapter、协议或支持规则未定的品牌
   明记 unsupported/blocked，不让资源插件自己实现品牌差异。
3. 单个资源闭环：插件登记定义→稀疏 Profile 选择→正确解析→Harness 可用
   facet 收到预期内容/服务引用；无 Profile 时原生配置仍可用。只靠控件可见、
   文件存在或模拟调用不能宣称真实生效。
4. 合成资源/隔离目录下验证项目级与系统级选择、未启用不注入、A/B 会话
   隔离、清理/卸载、失败不进入 confirmed；MCP 仅受控本地服务，不连外部
   MCP、不发模型请求、不读用户仓库内容或更改其文件。
5. 仅在定义明确时修薄装配/生命周期接线，不新增资源管理框架、扩设计或
   上游功能。每个独立回归并留检查点，无法接的列精准缺口继续下一个。

终态逐资源 CONTROLLED_WIRING_VERIFIED / UNSUPPORTED / PARTIAL_BLOCKED。
需要新 root 资产仍只准备安装，不绕过校验。最多处理上述三个资源，不进入
memory/hooks/subagents 等新一轮实现。

## 交接与唯一报告

- 开工核对当前分支、HEAD 与未提交文档；基础检查点 865f3ab45f。
  `.zcodeignore`、docs/ui-preview/01-empty.png 是保留的他属改动，不碰。
- 主执行者是唯一提交者/报告作者。允许仅提交本轮明确源码/测试/文档；
  不 add -A，不提交凭据、运行数据、构建产物。子代理不做 Git 写操作。
- 每项报告具体执行命令、退出码、反例、已验证与未验证范围；未知原因须写
  首个失配阶段，不写笼统“整体验收通过”。费用无法读取时写 unavailable。
- 更新 takeover-progress.md，最终新增 night-report-20261002.md：N1–N5 逐项
  终态、检查点 SHA、待安装项、明早用户最短操作清单。没有可做项即交付停写。
- 此为本夜最新合同，覆盖旧文档的无限推进/新 Harness/禁止本轮提交口径。
  不覆盖用户数据保护、凭证保护、真实模型授权或主干合并门。
