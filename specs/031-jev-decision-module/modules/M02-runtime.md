# M02 · 图运行、预算与生命周期

## 采用方式
直接依赖原版 pydantic-graph，调用公开异步执行接口。保留图结构检查，不 fork、不抽调度器，
不写“调下个节点”的 while，不设计自己的流程 DSL。
运行器不知道任务粒度、Harness品牌、配置字段或单元选择偏好。
可信 flows 可以直接依赖上游图构建接口；public DTO 与产品传输接口不暴露这些类型。

## 内部组成
runner/context/limits/calls/steps/errors/compatibility。
runner 管初始化/终态；context 每次独立；calls 是唯一模型网关；
steps 是轻量入口装饰，不替代执行器；compatibility 用真实上游库测试 API 和行为。

## 单次生命周期
1. 校验 request/flow/policy/limits；显式图名称，不运行时推导修改共享定义。
2. 保存 run.started；保存失败不调用外部模型。
3. 初始化独立 state、预算、截止时间、证据序号。
4. 在已有事件循环内 await 图执行；不调用 run_sync/asyncio.run 嵌套循环。
5. 每个受控业务节点入口检查maxNodeEntries（不是上游内部边数），模型网关原子预留网络attempt。
6. 校验业务终态并持久记录；只有成功保存完成证据才返回可信结果。
7. 外部协程取消仅在有界shield中记录和清理，然后继续传播cancellation；未能确认记录时查询unknown，不保证一定有cancelled；不吞BaseException。
8. 清理异常作为 secondary error；未确认清理不能声称全部资源已释放。

## 预算
默认 maxModelAttempts=12、maxNodeEntries=40、maxRepairRounds=2、maxInflightModelCalls=1、
wallTimeoutSeconds=60。它们是保守配置，可由调用方收紧；变更宿主上限另行审阅。
每次网络尝试发前预留，失败不返还。明确“模型轮次”和“网络尝试”两种计数。
SDK 自动重试显式关闭；不能看到一次 decide 就声称只有一次收费。
货币/token 消费只记录提供者真实回执；没有价格或实时用量证据就不能承诺硬货币上限。
ModelCallContext/单次permit的创建和消费顺序以公开接口为准；SDK原始client不得暴露给flow。
完成和取消以证据单终态提交为顺序点，先completed后取消不得改写为cancelled。
flowDigest须绑定实际审查代码与策略资源，而非仅hash名称/版本字符串。
call.intent 在网络前保存，表示“可能已发出”，不靠 dispatch 日志写入时序保证已/未发送。
请求一旦跨入口且未知，默认不自动重试；查询供应商是否接受只在真实支持情况下提供。

## 并行与信任
同 run 共享 state，不是上游自动隔离；主链串行。
并行只读查询返回各自不可变值，在固定 join 处合并；网关计数器用原子协调。
不同 run state/gateway/预算/序号隔离；共享连接池不得携带上次任务/候选。
可信 Python 节点可绕网关，所以必须审查代码和导入；不宣称沙箱安全、硬杀同步阻塞节点或零成本取消。
宿主强退后只读证据，不恢复图，不自动再调用模型。

## 验收
T03/T04/T05/T06/T11/T12/T13/T14/T15/T16/T19/T20/T23/T24/T25/T28/T29/T30。
必须使用真实 pydantic-graph + 假模型，不用 fake 图替代候选库验证。
需要真实包验证时先获得安装/执行授权并锁发布版本；研究 commit 不等于可安装版本。
