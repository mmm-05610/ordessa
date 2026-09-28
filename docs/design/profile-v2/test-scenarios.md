# Test Scenarios：先钉反例，再实现

每行同时对应服务断言和必要 UI 断言；生命周期用同一 registry/runtime/UI 实例，不重建后假装卸载有效。所有等待有上限，超时失败，不用任意 sleep 当成功证据。

| 场景 | 操作 | 必须观察 | 对应 |
| --- | --- | --- | --- |
| 输出中多次切换 | 输出 latch 未结束，A→B→C | apply/abort/restart 计数均 0；输出释放后仍 0；用户提交才 apply(C) 一次、send 一次 | G09/G20 |
| 逐项覆盖 | S1 覆盖模型；全局改模型和 reasoning | S1 模型不变、reasoning 更新，S2 全跟随，Profile 无反向写 | G06 |
| 正常选择 UI | 选择 B | 按钮立即 B；无 pending/override 常驻徽标；不把选择回执当应用成功 | G20 |
| 应用拒绝 | adapter 拒绝 B 的 reset | 消息 0、覆盖未删、输入保留；无静默回退 A | G07/G08 |
| 外部成功本地失败 | receipt commit 注入失败 | send 0；journal 可恢复；reconcile 不再发模型消息 | G10/G11 |
| 第三提供者 | 动态注册测试域 facet/editor/settings | Profile 核心 diff 0；编辑和设置保存互不串域；卸载消失、存值保留 | G01/G16/G19 |
| 晚到请求 | 设置页读 A，切 Server B，A 返回 | B 不被写入；旧 generation action 拒绝 | G02/G19 |
| 双重配置写键 | 两 facet 编译同 native key | plan 前冲突，native 写入 0，错误点名两个字段且不泄密 | G16 |
| 缺提供者 | A 含字段、卸载该 provider 后切 B | 不因 UI 隐藏就遗漏 A 的 reset；不能证明则阻发送 | G08/G13 |
| 会话身份重名 | 两 Server 相同 native ID | 覆盖/切换/receipt 各自独立 | G02/G12 |
| 权限上限 | Profile 声明越权行为 | 运行授权拒绝，不用提示词伪装 enforcement | G14 |
| 迁移 | 旧库复制、迁移两次 | 原修订不变、ID 保留、歧义 session 不自动合并 | G17 |
| 界面卸载 | 卸载 Chat glue/关闭管理器 | 取消 UI 订阅，不删除绑定、不 abort 当前输出 | G13/G18 |

需要模拟失败时注入应用端口/持久化接缝，不 mock 掉被验收的服务链。每个“计数 0”必须计数于真实调用入口；无资源/未收集/测试夹具抛错均不算满足。
