# Agent核心控制与Harness原生端口边界

2026-10-06用户补充：单元不能把全部能力下放Harness；Harness应暴露控制能力，由Agent模块掌握实际控制。本说明覆盖此前材料交付提案中可能被理解为转让流程控制的措辞；材料读取批准仍有效。以028 contracts §3/§7/§9为依据，不修改外树设计。

## 谁决定，谁执行

Agent核心决定并固定Profile来源、逐声明required/optional、配置路由、顺序、材料选择与原Usage、目标/作用范围/版本前提、目录与管理epoch、Operation/Step/恢复correlation。核心负责授权claim后调用、验证原生回执、原账CAS、发布/未知状态以及查询/停止/释放的时机。领域输出不能擅改核心冻结事实。

ConfigurationProvider解释schema，提出显式依赖及覆盖结果，并作无外部副作用的有界评估/编译。Harness/RuntimeProvider暴露原生控制与查询端口，执行已经由核心批准登记的动作，重核真实目标/字段冲突/版本/权限，给出证据。私有native子步骤/journal仍归Harness，核心不复制其执行日志、不懂品牌codec，不自创新的通用命令翻译器。内部子步骤不得变更批准的效果范围、追加Agent步骤、自行推进下一Agent动作。

固定准备材料引用只解决数据交付，不转移调度权。其安全形状及消费授权必须另行冻结，不能将任意payload或可执行脚本塞入原调用。原生配置实际状态仍唯一归运行配置owner；核心期望与操作事实不成为第二份actual配置账。

## 当前源码核查（只读，非新增验证）

management由核心判必需/可选、固定effectiveDeclarations/目标/source revision/Step/binding，作用前重核，再由原issuer签发，调用owner并校验记录结果。020纯descriptor/reference DTO不授执行权。

assembly._plan当前从原provider取plan，仅持久planDigest；reserve固定prepare/start两步，作用前重算比摘要，再将plan交给prepare。这个机制防漂移，但尚不能在核心记录中重建/逐项校验精确效果范围。不能当作完整控制接缝，也不能直接复制成配置协调模板。保留当前fail-closed资源限制与原未知记录；不以迁移名义放宽或复活旧链。

## 下一控制工单应有的判据

先材料核实，再由领域返回候选计划。核心核对候选与本次声明摘要/选定provider pins/精确材料refs、target/scope、before revision/DirectoryBinding/epoch完全关联；以原staged operation原子冻结具名效果步骤与调用binding。动作id、输入摘要、原材料关系、依赖顺序和恢复关联不能在派发后改变。先登记和唯一claim才调用，旧授权在phase封存后失效。原生私有子步骤允许，但其范围必须落在批准的效果意图内。

必备反例：候选换目标/版本/声明/材料；计划插入未批准动作或倒序；provider退役或授权变化；query旧观察竞争；原生成功但原账持久失败；unknown试图跨步/新key/释放旧材料。资源缺席即typed拒或保unknown，不能借材料引用自证已执行。具体DTO尚待下一工单冻结，本说明不是该作用路径已实现的声明。
