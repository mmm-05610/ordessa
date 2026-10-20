# 已退役 Kernel 的历史资料

此目录只保存退役时实际读取的历史测试、README、发行/版本/标记文件与SHA收据，不是活动源码、运行时依赖或兼容层。禁止通过这里重新导入、安装或恢复旧Kernel调用链。

`packages/execution/kernel` 已物理退出。原持久SQL、identity、namespace、operation/Usage/unknown保证分别由原Units store/records/generation及Infra/Server机制承接；没有迁移真实用户数据库。

有价值的 Domain、Usage、writer-close 三份原测试已迁入 `packages/execution/units/tests/persistence/` 并实际验证；剩余旧通用Object/关系/扩展CLI/Kernel发行测试在 `historical-tests/` 保存为历史，不参与首版资格。收据反映本次真实历史文件，不伪造早期迁前原件。

当前资格与边界见 [Kernel退出交接](../../implementation/execution-unit-environment-20261011/evidence/codex-takeover/kernel-retirement/next-slice/KERNEL-EXIT-HANDOFF.md)。
