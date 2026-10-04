# 013 生命周期和恢复检查点

接收 UI01 时 HEAD 为 29f00be68500cdeb5fc7558de34e20f9f0d6dfe7；接收提交 88d05d696db21f0efd9691aad22fa995544486bc。UI-T01–08 / UI-A01–12 保持独立 QUEUED / NOT_RUN，未替代原验收。

- Host 预检重复方法/流/HTTP/贡献，再以可信 descriptor 调用可选 owner 生命周期钩子。同一 Environment 显式安装启用；精确 activation 退休前保留 token、active、enablement；rollback 只撤销本轮 enablement。新增红首 2 failed / 3 passed，修复后 5 passed。
- 装配使用中性 ServerPluginSelection，保留原 build_runtime 五参数和裸序列语义，保持 state/core.sqlite 标识；旧执行 tombstone 存在时拒绝新写者，不迁移真实数据。
- 真实附件效果消费捕获字节；恢复查询无原生端口或 fingerprint 时仍返回已持久化事实，新的可靠 submit 明确拒绝。恢复/附件组合 57 passed，见 recovery-and-attachment-rerun.txt。
- 新生命周期、T016、装配故障回收、CoreBinding、旧 tombstone 防护组合 23 passed / 0 skipped，见 host-neutral-composition-verified.txt；门禁与产品提交/五个 SIGKILL 组合 63 passed / 0 skipped，见 host-gate-recovery-verified.txt。此为不同范围组合，不能相加作唯一场景数。

保留失败证据：host-neutral-composition-rerun.txt 为缺数据库提供者抛 AttributeError 的 1 failed / 17 passed；修复为 StorageProviderMissingError 后上述 23 passed。TrackedBinding 测试输入补 kwargs 转发，原断言不动。host-gate-regression.txt 命令含不存在测试文件，无测试执行，不能算绿。

Server 全量检查点仍是 84 failed / 1205 passed / 9 skipped / 2 errors；baseline unique red IDs 78，当前 86，新增 17 个，详见 server-red-comparison.txt。后续窄验证仅修复其中装配签名、T016 两项与故障测试输入，不推断其他红项消失。旧 CoreRuntime/store/sidecar 断言的合同碰撞保留；实际原生 first-send 不可用是生产缺口，不能归作已修。

剩余 ready：前端共同权威持续观察、Chat 可靠提交及原键恢复接线、固定源提交的干净发行与 F5 独立消费者。未跑发行、真实 GUI/IME、真实模型、安装、真实数据迁移均不宣称通过。原任务账 107/129，未因本检查点勾选端到端任务。
