# Agent 模型：职责与对象
## 单一核心
Profile、Provider、Node、Unit不是四套状态机。核心沿用Environment/CoreRegistry/OperationStore/ParticipantInstanceRef/InvocationContext和既有使用关系。
AgentRuntimeProvider通过AgentContributionSet注册；不再实现registerHarnessProvider独立字典。宿主赋予激活身份和代次，插件不能自行声明可信owner。
注册阶段只发布契约，不启动模型或实例。stage/commit/rollback/drain/retire按现有语义处理。

## 对象
Profile：固定manifest及材料引用，由核心保存版本；现有harnessDefinitionRef/declarations结构不变。
Provider：插件提交的准备与恢复能力，包含固定descriptor、配置结构和通道要求。
Unit：实际工作单元的受控句柄，由插件持有原生进程、配置目标、session绑定和协议。
Node：核心公共身份，绑定providerRef/unitRef/profileSnapshotRef/preparationContextRef和操作证据；不是另一份native实例。
进程、原生session、Unit、Node身份不能混用；一家一个进程多会话也必须明确单位与独占配置范围。插件激活generation不分配Node generation。

## Provider生命周期
describeDefinition/inspectInstallation/assessConfiguration/planPreparation是描述和规划；prepare/start受授权且通过原操作step claim。
queryStep只核实原操作，不能触发再次启动；recover核实持久绑定后接管，不自动建替代或重发。
各方法支持度逐项声明，方法存在不代表能力可用；不支持recover必须显式拒绝，不能stub成功。
核心解析固定Profile和资源材料，检查required/optional后协调Provider。配置schema与原生落地属于对应提供者，不在核心出现品牌枚举。

## Unit逻辑外形
identity：unitRef/providerRef，引用格式复用现有体系。
usage：describe/connect，使用授权租约打开双向入口。
management：describeConfiguration/inspectConfiguration/applyConfiguration/queryChange。
lifecycle：inspect/stop/release。逻辑外形不强制新建大Python对象；可以公开引用+现有端口实现。
核心只保存身份、关系、配置来源、操作和观察证据，不维护可自行变化的运行状态。
历史Node可读不意味着native在线；准备结果未知不可发布可用入口。

## 使用通道
保留原生payload、request id、未知事件和原生错误，不统一为sendMessage或核心品牌方法。
消费者不编写各家启动/配置/审批/完成事件解释器。品牌专用协议处理移入提供者或其公开适配组件；产品客户端只消费平台服务和通用授权连接。
若通道使用需要品牌SDK，只能封装在提供者侧，或由产品明确装配插件提供的组件；不将副作用客户端隐藏在CLI里。
核心可对每次发送进行授权与既有InputAttempt接纳，但不解释品牌语义。一个原生方法可能有多个副作用；不能按“看起来像只读”判断权限。
完整原生入口只授予覆盖其全部副作用的权限。不能保证只读限制就拒绝只读入口。
撤销、过期、drain和旧generation必须拦住后续写入。transport断开不会报告任务已停止；反向请求无人接收时pending/refused，不autoapprove。

## 状态所有权
Harness配置事实唯一源是提供者对native的确认。核心与UI缓存是带来源与时间的只读观察；不能将数据库缓存当最新事实。
多个消费者修改同一scope由现有操作及提供者配置owner序列化。原生外部写入可导致快照过期，不宣称跨外部修改者的强CAS。
desired Profile/请求与actual snapshot分开；应用新Profile不自动更改catalog，实例修改不自动保存Profile。

## 不扩张
不创建第二执行引擎、管理daemon、全局provider单例或另一套恢复库。
不扩展外置环境编排。安装更新机制不纳入本轮；只检查已有指定安装。
