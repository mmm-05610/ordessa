# 阶段、写权与产品验收

## 本轮已经做什么

隔离工作树、专属分支、Python3.12虚拟环境和基础模块检查；目录/架构/命令/Skill职责设计。没有产品源码占位、服务启动、安装全局Skill或用户配置变更。

采用incremental-work-order的契约先行/证据分账方法；本轮未派执行者，因此不初始化另一全局队列、不commit或写运行数据。复用028设计权威的引用，不在子树复制一套可独立改的核心合同。现有准备树baseline不是最新实现基线。

## 实现前的第一道门

固定已接受的026整合SHA，以及028核心修订实际消费版本。确认该SHA的公开Agent/Environment/持久输入/目录接口和真实调用者；若核心模块尚未落地，先按028实现最小装配纵向链，不让CLI走旧Profile协调器或runtime-compat ledger。

更新本分支基线需要明确记录所消费提交与授权，保留原准备点。不能直接checkout正在移动的026 branch、复制其dirty代码或绕过review合并主树。

## 有序交付

| 阶段 | 实际交付 | 可验收窗口 |
| --- | --- | --- |
| P0 | 设计与隔离环境（本轮） | 目录、服务依赖、CLI/Skill边界可审阅 |
| P1 | 固定基线，核心最小Agent模块与公开API | 非Chat消费者用Profile准备真实节点，query/stop能核实 |
| P2 | 独立产品目录与CLI只读/配置命令；可选配套服务装配 | 源码统一在products/agent-tools，无插件注册依赖；doctor、能力发现、Profile版本CRUD/preview，无模型调用 |
| P3 | CLI节点prepare/configure/stop/recover | 唯一配置owner、真实target排他、重启节点身份不变 |
| P4 | 一家族原生客户端＋持久任务关联 | 使用外置Agent完成小任务；未知不重发、进程退出边界明确 |
| P5 | 三Skill＋工具包分发 | 人和脚本可直接调用CLI；支持Skill的Agent可按说明使用同一命令，不依赖调用者品牌；验证任务隔离和配置/应用分离 |
| P6 | 第二消费者MCP薄入口（另阶段） | 与CLI同node/operation权威，没有第二状态账 |

P1若缺核心端口，P2客户端可以完成参数与失败反例，但不得宣布产品可用。不能mock一个local核心或CLI daemon作为临时实现绕过缺口。P4真实模型与服务重启需单独范围/费用授权；缺席时记录untested/blocked，仍可做离线和真实进程协议测试。

建议一个牵头者负责合同、Git、验证与账本。契约/核心步骤先串行；公开接口固定后Skill资产、CLI只读格式测试与独立原生客户端协议测试可按不交叉文件切片。正式派单时才声明每个并行单元，不因本页写了“可并行”自动开代理实现。

## 最小产品门

| 门 | 正向 | 反例 | 缺席行为 |
| --- | --- | --- | --- |
| A：消费公开API | CLI只依赖wire/公开协议，不import服务内部 | 插入私有Harness/core实例化依赖，检查命中 | 路径/检查不能读取则失败 |
| B：单核心 | 每条命令查询同Environment node/operation | 同node CLI/MCP两账、profile编辑旧写入口仍可写 | 冲突拒绝，不fallback |
| C：定义与应用分离 | 修改Profile只产manifest版本；apply明确目标 | rename改变配方、Skill编辑后自动apply | revision冲突拒绝 |
| D：节点与配置 | 两节点材料/target隔离或明确共享拒绝 | 同home两个node当独立配置 | 无隔离证据拒绝第二写者 |
| E：原生使用 | 帧与callback正确，lease/fence受控 | raw入口过授、超时抢写、自动审批 | 未授权/无法fence拒绝 |
| F：持久输入 | prepare/session/create/input分别关联，同key不重发 | native接受后回执前崩溃，CLI重启再run | unknown保留，强保证不足拒绝 |
| G：detach诚实 | 有真实常驻持有者才返回可detach | CLI进程结束callback无人持有却称托管中 | 只支持wait或明确能力不足 |
| H：历史恢复 | 重启查询同node/native/project，不重新装配latest | 新同名session冒充旧历史 | 历史保留、恢复不足拒绝 |
| I：分发Skill | 全部Skill命令属于实际版本，安装scope明确 | 三Skill互抢任务，命令不存在或静默装全局 | 验证失败，不修改用户设置 |
| J：可见证据 | 给出SHA、资产、exit、反例、费用/清理 | 仅mock/材料校验称“产品完成” | 明确部分/未测，不报DONE |

## 不在第一版

桌面UI、插件市场、完整安装更新产品、外部环境编排、DAG、自动团队、所有Harness支持、多托管session共享unit、自动安全审批。MCP接口可先设计，第二阶段才实现并验收。

当前版本只基础环境verified；上述A–J产品门与028的42项产品门均未执行。
