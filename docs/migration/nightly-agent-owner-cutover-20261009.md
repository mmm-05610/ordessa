# 夜间 Agent owner 源码切换 · 2026-10-09

源检查点cf1da900d2；本轮仅操作独立集成树，未打开或迁移用户数据库。唯一实现整体迁入execution/agents、Codex协议退出公共包、Ordessa只读Decision facade迁Server适配器。来源和逐文件SHA见[W06映射](../implementation/nightly/evidence/W06/source-cutover-map.json)及[基线摘要](../implementation/nightly/evidence/W06/baseline-agent-sha256.json)。

发行ordessa-execution-agents==0.1.0，公开入口ordessa_execution_agents.public；现行调用方和显式Server agents/decision extras引用此包。原pacthold.agents Python namespace无shim/fallback。reserved owner pacthold.agents、Profile三namespace、ACL、fingerprint作用域、wire /3、Environment/store/issuer/verifier/records及持久identity保持；不是格式或数据ID重命名。

AgentTools工厂接Host现有RootOwnershipPort和issued OwnedRootBinding，原store仍是root/state/core.sqlite，原journal仍是root/plugins/profile/native-configuration.sqlite，marker/journal_key不变。不得使用另一产品state/agent-owner/operations.sqlite代替。用户数据无隐式adoption、删除或schema升级。

publication失败只在Registry锁内证实未发布后丢弃；partial/committed残留保留在原batch，未知owner禁止新generation、换ID和可调用port；缺真实reconcile继续拒绝。此unknown hold限当前进程，durable hold/cold reopen reconciliation未完成。build_runtime acquire前只读DB预检仍待处理；本修复不声称零副作用预检或OS级ABA关闭。

共享Harness contracts/records整体迁移、完整包/产品闭包、真实Pi Skill/附件与原生恢复及W06完整验收仍PARTIAL。34个原docs活跃test源迁新owner测试目录，historical .md/json/log不改；入链清单与逐文件来源均保留。

## records后续整体迁移

主体检查点09ea93732b后，原records三源码原字节迁入execution-agents/harness/records；旧发行与import root退出，消费者和metadata同步切换，CLI运行闭包仍不含SDK。来源/归档见W06/records-cutover-map.json。两产品原DB路径和全部表/身份字节保持，没有用户库迁移。Codex专属codec分离、只读历史打开及完整恢复尚未完成；原冷读路径不能因源码搬迁变成受支持。旧C2聚合fixture27项setup拒绝仍待实际独立admission切换，不恢复退休插件。
