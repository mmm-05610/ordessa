# 协调者交接

## 本包实现内容

- `projection/method.yaml` 声明有限的 `ordessa.methods/v1` report capture smoke 投影、资源哈希、`phase-report` schema/template、以及唯一真实 operation 的 contract digest；metadata 明确 `full_flow_support: unsupported`。
- `projection/workflows/report-intake.yaml` 只有一次真实 `engineering.artifacts.create`；通过 context slots 取得 artifact kind、精确 method refs 和完整 interface-2 `initial` envelope。它只登记一个报告，不承载任何 Nova 阶段动作。
- 一次成功报告以 `completed` 停止；artifact 业务拒绝以 `rejected` 停止。两者都不表示 Nova 业务决定。
- `PROCESS.md` 是完整外部流程契约；`COVERAGE.md` 区分规格与 smoke 投影；`_support/design-traces` 是非运行设计材料。

## 待统一验证

请由协调者对照当前 host capability catalog/loader 执行统一加载、编译和 schema/manifest 校验，把命令、版本、返回值及失败诊断记到 `_support/verification/`。执行前核对 descriptor digest 仍与 `projection/method.yaml` 相同。不要以本交接说明或文件存在作为编译/运行证据；通过编译也只证明 report capture smoke 投影有效，不代表 Nova 完整流程受支持。

不要将该方法包接入产品装配、注册真实 Nova 外部来源、启动会话、触发 artifact 写操作或宣称完整 Nova 过程执行。若协调者发现 context slot 或 MethodPayload payload-shape 与当前实际 contracts 不同，回报精确字段，不改源 owner 或公共契约。


## 协调者最终实测

上述待验证事项现已按同一固定核心字节快照完成。详情与退出码见 [_support/verification/README.md](_support/verification/README.md)。没有发布或runtime运行；smoke直接operation入口也不满足当前Work start契约。后续设计讨论请读 [_support/verification/design-findings.md](_support/verification/design-findings.md)，小数兼容项单列，不能当全局架构缺口。
