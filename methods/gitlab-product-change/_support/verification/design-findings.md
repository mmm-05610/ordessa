# 方法编写实际发现：完整流程 unsupported

共同核心索引：`c825c329a83775685bd048c144068ca31e0a5369d68e317bee3d95f0f79b40f5`。完整外部规格及逐阶段覆盖见根 PROCESS.md、COVERAGE.md。

| 完整 GitLab 语义 | 当前缺口类型 | 对应限制 |
| --- | --- | --- |
| Validation/Build独立轨道的重叠、并行、汇合及按工作类型skip | 并行/汇合语义本版未定义；业务skip决定owner未绑定 | 无fork/join；单cursor/单next；报告两轨字段不建立两个运行token |
| 问题/方案验证反复进行、开发评审返工、Block后返回原阶段 | 循环契约未定义；Work来源机制已有而外部来源未绑定 | DAG cycle拒绝；wait恢复需要current owner guard而非label/report声称 |
| MR merge→部署验证→结果评估→继续/迭代/回滚/重启验证 | 外部状态/版本/决定的真实契约和来源缺失；循环语义缺失 | 没有GitLab部署/measurement/决定descriptor；命令完成不是上线；改善回路不能在图里执行 |

## 关键问题与事实分类

1. **业务条件怎样进入路由？** 分支不是完全缺失。v1 operation 的 outcome map 已能表示有限分支，但 outcome 集合必须与实际 descriptor 严格相同。报告正文中的 `spec_required`、批准、跳过、延期等字段仅为 method-content value，不会成为流程条件。现有 artifact 命令只报告事务 `completed/rejected`，不能用它判定业务批准。本次 catalog 没有外部流程决定的 owner operation/check；这是实际业务契约与生产绑定缺失。此外当前运行桥接不是“注册任意 descriptor 就能运行”：MethodBridge.operation_inputs 只查 command_capabilities() 的有限命令，record_command_step 只消费原 journal 的 completed/rejected。待设计问题是由明确的决定 owner 返回闭合业务 outcomes，还是给可信决定事实定义通用路由契约；本任务没有批准或实施这项选择。
2. **反复返工和双轨怎样表示？** validation/workflow.py 明确拒绝回边；v1 只有 operation/wait/stop，没有 loop/retry、condition、parallel/fork/join 结构。有限 DAG 可展开一次返工或绕过节点，不能表达不定次数的审阅—修改—重审，也不能把两个独立轨道并行及汇合当成既有语义。新会话/新 epoch 或有限展开是外部协议的替代方案，只有明确裁定后才能视为允许的映射，不能悄悄当作原流程等价实现。当前完整方法所需的一般迭代/并行契约在本版中未定义，属于表达层设计缺口，不只是未完成一个 provider。
3. **等待、恢复与版本绑定哪些已有契约？** WorkConditionSource.guard_start/guard_condition/guard_step_completion、WorkSeed/WorkWaitSelection、原 run CAS 和精确方法/registry 绑定已有契约及部分实现。CurrentMethodWorkBindings.guard_wait 只接收 WAIT_EVENT=`engineering.work.current_condition`，下一节点固定为 WaitNode.next；start 要求入口为该 wait 且 resume_contract=`ordessa.engineering.current-work/1`。本次生产外部 source/catalog/role/status 的绑定未建立，published_wait_descriptors=[]；缺少 source/registry 会真实拒绝。这一部分应区分“机制已定/有实现，但业务来源和装配未完成”与“外部流程业务契约尚未定义”。两个 smoke 的入口直接是 operation、没有该 resume_contract，故也不能直接作为当前 Work 启动；本任务只编译和检验输入，没有冒充运行。

## 精确证据

以下行号属于本次捕获源码，文件哈希在 core-snapshot.json；源码全文以非运行文本保存在 Nova 的 core-sources.json，编译两包均用同一字节索引。

| 层 | 源码/描述 | 事实 |
| --- | --- | --- |
| schema | packages/engineering/src/ordessa_engineering/methods/definitions/schemas/v1.py:65、:74 | node schemas 仅 operation/wait/stop；没有独立 condition/loop/fork/join |
| validator | packages/engineering/src/ordessa_engineering/methods/validation/workflow.py:76、:128 | exact outcomes；UNHANDLED_OUTCOME 与 UNSUPPORTED_FLOW_CYCLE |
| registry 描述 | docs/implementation/packages-convergence-20261012/engineering/CAPABILITIES.json | 18 commands / 2 checks；published_wait_descriptors 为空；is_production_catalog=false；无 Nova/GitLab 业务决定、外部状态/部署 descriptor |
| compiler-vs-runtime operation | packages/engineering/src/ordessa_engineering/application/orchestration/method_bridge.py:79、:89 | command_capabilities 的有限真实命令匹配；config 不转换成输入数据 |
| runtime 命令完成 | packages/engineering/src/ordessa_engineering/application/usecases/queries/method_work.py:152、:213、:216 | 只消费 original journal completed/rejected；直接 transition.wait 拒绝 WORK_TRANSITION_UNAVAILABLE，可 next 到真实 wait node |
| runtime wait/start | 同一 method_work.py:47、:54、:73、:245、:261 | 精确 resume contract；固定通用 WAIT_EVENT；单 cursor/单 next；entry 必须是该 WaitNode |
| 已定义 source 协议 | packages/engineering/src/ordessa_engineering/application/contracts/method_work.py:11、:65 | 三个真实 owner guard，调用者不能拿 ready=True/自述 actor/报告内容替代权威 |

results.json 是实际无网络校验。baseline=0 仅证明 smoke 投影和报告值；未知 operation、伪业务 outcomes、parallel node、cycle、digest mismatch 的实际子进程均 exit=1。GitLab cycle 的 compiler 第一错误是 UNREACHABLE_STEP，同时 validator 返回 UNSUPPORTED_FLOW_CYCLE；没有把第一错误改写成不存在的执行错误。runtime 行为限制是对同一源码字节的静态审核，未构造替身 ports 或实际运行 MethodRun 来伪证生产支持。

## 为何只交单次报告投影

用户禁止为样例修改 packages，要求只调用已有真实操作。唯一选定且语义合适的已有动作是记录方法绑定 artifact；其输入和结果不承担业务决定。若把整个上游流程塞进该报告并把 completed 当成上游完成，会把“报告保存”错误等同于“流程执行”。因此根目录保留完整外部规格、阶段/角色/批准/返工/延期/取消/结束/反馈；projection/ 单独命名 report-smoke，完整流程明确 unsupported。等待与决定保留为外部规范，不能藏进报告后声称 Ordessa 在执行它们。

## 方法兼容项（单列）

GitLab metric 样例的小数最初被报告 schema 接受，但 MethodContent.from_value 的 canonical_bytes 拒绝 float；首轮 baseline exit=2 已保留。方法 schema 和样例改为整数、精确十进制字符串或 null，数值含义保留。证据：packages/infrastructure/src/ordessa_infrastructure/encoding/canonical_json.py，packages/engineering/src/ordessa_engineering/domain/artifacts/models.py::MethodContent.from_value，attempt-01-results.json。它是本次报告表示与当前 codec 的兼容问题，不是循环/并行/业务决定的架构缺口，也未改核心。
