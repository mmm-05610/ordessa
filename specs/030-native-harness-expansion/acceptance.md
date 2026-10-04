# 夜间验收：数量不代替证据

## 验证层次

| 层 | 证明什么 | 不能证明什么 |
| --- | --- | --- |
| L0 资料 | 确认官方通道、源码入口、许可、固定版本 | 可执行、可配置、任务成功 |
| L1 合同/fixture | framing、相关id、状态/配置反例、未知扩展 | 真上游进程兼容 |
| L2 实际进程 | 隔离home、真实握手/原生会话/退出/可无模型配置 | 已授权账号、模型或任务成功 |
| L3 隔离闭环 | 实际已安装CLI→核心→驱动→真实上游；上游支持的loopback provider可验证任务 | 真实商业模型质量、认证/计费 |
| L4 真实模型 | 用户后续明确授权的家族/配置/任务/成本下完整使用 | 其他版本、平台与所有功能 |

层是覆盖维度，不是简单累计等级：只启动握手不宣称L2会话/恢复全覆盖。fixture与本地假LLM必须明确标签，不把fake native server当L2。L3可使用上游正常支持的本地模型接口，不修改上游源码模拟“已成功”；缺此模式就未测。

## 每家矩阵的列

familyId、chosenChannel、upstreamRelease/SHA、artifactDigest、protocolVersion、driverPath、clientPath、nativeSessionBinding、configOwner、profileKinds、skill/prompt/model/MCP/internalSandbox实际适用性、approvalCallback、resume、cancel、extensions、transportFence、requestReconciliation、installScope、L0-L4证据、限制、下一步。

能力不存在写unsupported并给证据，不需每家都内置sandbox或model热切换；未核实写unknown。Profile请求某必需配置但家族不支持时prepare发前拒，不静默忽略。候选登记不得runtimeReady=true。

## 共同门及反例

| 门 | 断言 | 反例 | 缺席/未知时 |
| --- | --- | --- | --- |
| G1 版本与身份 | 所选artifact与家族/协议匹配 | PATH同名不同程序、版本超范围 | 拒绝发布ready |
| G2 权威 | 同Environment、唯一configOwner | 第二currentModel/session表、CLI私改文件 | 阻塞运行接入 |
| G3 Profile适用性 | 实际参数由家族编译并核实 | unsupported配置被吞、模板冒当前状态 | 发前拒；未观察项unknown |
| G4 双向原生通道 | 保留未知扩展、正确callback/id | unknown事件丢弃、自动批审、假observe | 收窄声明或拒绝使用 |
| G5 framing | stdout协议/stderr诊断隔离，背压与限制 | UTF8拆帧、U+2028误换行、超大帧 | typed failure，不继续误解析 |
| G6 生命周期 | 单session绑定、退出/取消有证据 | 重启自动新建/重发、退出等于completed | unknown，不重试 |
| G7 并发与隔离 | 不同node隔离，公共scope冲突受控 | nodeA事件到B、两客户端同时改同home | 拒绝写或串行，不假隔离 |
| G8 清理 | 清理仅owned实例和临时目录 | borrowed被kill、PID复用/名字匹配 | 不删不kill，登记未清理 |
| G9 授权 | 准确原生副作用范围与epoch | 原生terminal越目录、旧lease继续写 | 拒绝effect |
| G10 分发 | fresh client可装且不导入宿主内部 | wheel缺schema、要全仓editable才能跑 | 分发未完成 |
| G11 失回执 | 恰一次managed派发，核实不发新turn | newkey换session逃unknown、SDK自动retry | 保留unknown |
| G12 成本/凭据 | 本夜无真实模型、无用户认证变更 | SDK继承GH_TOKEN/用户home、启动hook联网 | 拦截启动/网络并登记 |

测试不能硬编码不存在的命令为成功。N001先定真实测试入口；N012实际安装后使用已有且实现的新命令，未交付的nodes/tasks标缺失。

## 家族终态

- RESEARCHED：L0有证据，仅资料。
- CODE_READY：已实现有测试，实际原生运行尚缺。
- NATIVE_VERIFIED：具体L2/L3已观察，不等于模型验收。
- PRODUCT_VERIFIED：规定产品门及获准真实使用验证完成。
- PARTIAL/BLOCKED：明确已完成内容、依赖、未测项。

工单_DONE表示该单明确范围的验收通过，必须带上述产品分账；不得将10个CODE_READY累计为10个PRODUCT_VERIFIED。原生任务未授权时本夜批次整体PARTIAL，明晨优先报告能试的入口和授权清单。

