# 离线检查

运行：`python3 specs/025-open-frontend-environment/checks/model_checks.py`。仅标准库、内存参考模型，不导入生产模块、不连接服务、不写用户数据；stdout结果可保存到本目录evidence/offline-results.json。

证据L仅覆盖结果列出的序列。该脚本不是V4完整状态机实现，不提供真实持久化、线程原子性、完整证据校验、DOM/IME、IPC队列或OS沙箱。authority/native alias检查、授权commit、budget都是抽象契约模型；实际实现尚待设计审核后的受控验证。

反例包括按文本相等清ABA草稿、contract major造成双权威、错误target/generation/opId、晚native patch、缺current成功、partial/unknown、跨await撤销、组合缓冲发送、重名surface及预算超限。每个guard同时构造可接受正例和可拒绝反例；不以资源不存在为通过。

2026-10-03主验收修订：新增同revision冲突重复观察不能解锁、完整快照清覆盖增量但保未来缺口两项，当前30项。新增反例可抓恢复旧错误行为的两个内存变异；见evidence/acceptance-repair-checks.json。原offline-results.json和delivery-check.json的28项结果保留历史，不代表当前检查快照。
