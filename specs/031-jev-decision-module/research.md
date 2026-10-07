# 复用研究与证据

## 已选路线
原版pydantic-graph负责图执行；官方typesafe-sdk负责Jev调用；我们实现可信业务图、
端口映射、预算、协议校验和安全运行记录。这些是业务/边界代码，不称为上游已有功能。
没有源码复制、fork或私有调度器补丁；MIT依赖仍记录来源与版本。

## pydantic-graph
研究提交：721c78d6014f197c595a9c2a83789aa4dbf6d008。
- [公开执行与清理](https://github.com/pydantic/pydantic-ai/blob/721c78d6014f197c595a9c2a83789aa4dbf6d008/pydantic_graph/pydantic_graph/graph_builder.py#L240)：run/iter、异步任务与取消。
- [共享状态](https://github.com/pydantic/pydantic-ai/blob/721c78d6014f197c595a9c2a83789aa4dbf6d008/pydantic_graph/pydantic_graph/graph_builder.py#L895)：并行节点得到同一state/deps，不能宣称自动隔离。
- [依赖](https://github.com/pydantic/pydantic-ai/blob/721c78d6014f197c595a9c2a83789aa4dbf6d008/pydantic_graph/pyproject.toml)：Python>=3.10、AnyIO>=4.7、Pydantic>=2.12、logfire-api、typing-inspection；不需要整套Pydantic AI Agent。
- [取消测试](https://github.com/pydantic/pydantic-ai/blob/721c78d6014f197c595a9c2a83789aa4dbf6d008/tests/graph/builder/test_graph_execution.py#L667)：阅读断言，不表示已跑通过。
源码观察支持可信图直接依赖+薄包装。未验证发布包、升级兼容、并发取消和目标集成。

## Jev/TypeSafe
官方文档：[API](https://docs.typesafe.ai/api)、[模型](https://docs.typesafe.ai/models)、
[置信度语义](https://docs.typesafe.ai/confidence)、[已知限制](https://docs.typesafe.ai/model-jaggedness/jev-1.13)。
官方SDK研究提交：f078f1e208a0d885154dc758344ae4fce77ac168，pyproject版本0.7.2。
- [SDK依赖](https://github.com/typesafe-ai/typesafe-sdk-python/blob/f078f1e208a0d885154dc758344ae4fce77ac168/pyproject.toml)：Python>=3.10、httpx2（不是httpx）、Pydantic/core、Tenacity、typing-extensions。
- [默认重试](https://github.com/typesafe-ai/typesafe-sdk-python/blob/f078f1e208a0d885154dc758344ae4fce77ac168/src/typesafe_sdk/_core/retry.py)：max_retries=2，本版明确改settings为0，不改上游。
- [答案处理](https://github.com/typesafe-ai/typesafe-sdk-python/blob/f078f1e208a0d885154dc758344ae4fce77ac168/src/typesafe_sdk/_core/response_types.py)：仍需本地检查答案集合一致性。
- [问题](https://github.com/typesafe-ai/typesafe-sdk-python/blob/f078f1e208a0d885154dc758344ae4fce77ac168/src/typesafe_sdk/_core/questions.py)：Choice/Score/Noul，不是自由生成接口。
官方HTTP为POST https://api.typesafe.ai/v1/systemone。拟议固定模型jev-1.13.0；
确切发布可用性与账户能力实施前核实，不自行使用移动alias降级。
Score可小数，Noul仅p，confidence不等于正确概率；中文质量/顺序偏差/真实费用未测。

## 当前Ordessa事实
只读参考树：/home/maoqh/.codex/worktrees/agent-tools-product/ordessa。
观察提交9e1a6db19bd54df5d6508eaa71098ca96b59bcd9；正在实施，后续HEAD可变化，
承重判断按固定git show核对，不混用实时文件与旧SHA。
- agents/public.py：AgentServices和单Environment组合。
- agents/configuration.py：ConfigurationDescription、ConfigurationSnapshot、未知字段与sourceRevision。
- agents/profiles.py:295：preview返回unresolved/providerUnavailable，不能当产品校验已完成。
- agents/providers.py：描述是admitted provider投影，不等于安装或ready证据。
- agents/management.py：describe/inspect/apply/query；读配置和实际修改分开。

这些提交是否可在远端查看未核实，因此不伪造GitHub源码链接；实施前保存来源摘要/完整SHA与差异清单。
本包不是该树AU005验收报告，也不宣称Agent产品已完成。

## 上游采用闸门
安装/执行需另授权。实施时选择真实发布版本，核对源码/API、wheel哈希、传递锁；
最低Python>=3.10且目标验证用3.12。Pacthold的Python支持下限不因可选decision依赖自动上调。
依赖更新独立跑兼容/取消/重试套件；无法支持所需行为时PARTIAL，不能静默改用自建循环。

