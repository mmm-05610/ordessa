# 030 · 原生 Harness 扩展夜间实施包

目标：在现有Agent Tools产品上扩展约10个主流Harness家族，接入足够完整的原生使用通道及管理接缝。不是新增10个命令名称，也不是把10个产品翻译成同一个聊天接口。

## 材料与执行入口

- [架构和边界](design.md)
- [候选与官方资料](candidates.md)
- [逐项验收](acceptance.md)
- [夜间工单队列](../../docs/implementation/agent-tools/night-harness-expansion/work-orders/)
- [夜间运行规则](../../docs/implementation/agent-tools/night-harness-expansion/README.md)
- [夜间状态](../../docs/implementation/agent-tools/night-harness-expansion/status.md)

继续使用既有实施会话，工作目录为 `/home/maoqh/.codex/worktrees/agent-tools-product/ordessa`。不另开仓库、工作树或新的常驻服务。新包不改变029/028已定语义；原队列未完成的节点/输入前置需核查、串行承接，不重复实现。

## 实测起点 · 2026-10-04

本次只读观察HEAD：adce734db21945181bf93da9720158d05e957654，源码有未提交实施改动。它不是包含这些改动的交付SHA，必须由原执行者收口后记录夜间精确源码快照。

实际客户端目前是 `products/agent-tools/src/ordessa_agent_tools/{cli.py,client.py,initialization.py}`；预想的native_clients目录尚不存在。核心public入口目前主要是ProfileCatalog。最新原status报告AT-013完成PATH发现、整体PARTIAL，节点/任务命令未交付，模型0；该报告是引用，不作为本包重新验收成绩。

现有Harness命令目录8家族：claude-code/codex/dsh/hermes/kilo/opencode/pi/qwen。只发现可执行文件不代表具备原生运行接纳。不得删除原8家族、改历史身份来迎合新10家族清单。

## 夜间交付分账

1. 10家族通道决策与固定版本证据。
2. 在前置具备时尽量实现实际接入代码、隔离实例配置、公开贡献与消费者协议客户端。
3. 实际上游进程的无模型握手/会话/配置证据，能测多少写多少。
4. 明晨已安装CLI的验收入口及剩余登录/付费测试清单。

不承诺一晚完成10家族真实任务。没有模型授权时模型验证保持未测，不报告全部产品DONE。某家受阻不阻其他家研究/协议测试，不能用mock或替换家族凑数。文档与安装依赖可进行公开资料研究；用户运行资源和认证不在本夜授权内。

