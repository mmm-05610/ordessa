# 待批准：真实 Codex 协议隔离烟测

纯读接入及其原图／真实Jev验收已完成，证据见 evidence/codex-pure-read-20261005。用户原请求明确真实Harness调用另行授权；AGENTS.md第8/9条也禁止未经授权触碰用户服务及真实模型范围。下列测试尚未运行。

非执行盘点：本机 command -v codex 指向 /usr/lib/chatgpt/resources/codex；/usr/local/bin/codex 不存在。只查看路径，尚未运行--version，也没有确认与owner固定0.157.1契约兼容。不能拿本次源码/脚本peer通过冒充原生二进制可用。

拟议有限范围：最多2个本测试子进程（1次--version，至多1个app-server），总120秒，version10秒、协议90秒、清理最多20秒；没有重试或其他二进制fallback。版本/接口不兼容则记录拒绝／unknown，不能改pin填绿。

使用本树 .decision-tmp 下新的私有临时CODEX_HOME/工作目录；由现有LaunchSpec/ProcessChannel隔离env，不继承用户登录、配置、token、原用户数据或免费Zen key。不重启／杀用户现有服务，只关闭本测试自己创建的子进程。临时文件仅本测试目录，不迁移资料。

只允许一次 initialize、thread/start、thread/read(includeTurns=false)、config/read；不得turn/start／模型消息、native config写入／batchWrite、工具操作／apply、prepare现有用户单元或connect用户会话。模型请求上限0，无凭据注入／付费fallback，实际费用仍UNKNOWN，未观察的启动网络行为不冒称无风险。若新原生入口默认收费或要求登录，拒绝继续。

验收：真实client匹配响应ID及新thread ID，未知结果不重发；本测试进程有明确清理回执，失败代码及捕获内容经过脱敏；原owner配置pure接口仍不调用该进程。此步骤只证明实际二进制/协议边界，不证明完整部署UnitRecords原生apply链。后续实际应用必须另行规划原authority/DirectoryBinding/operation/projection接线和授权，不能用受控projection替代实际owner账本。
