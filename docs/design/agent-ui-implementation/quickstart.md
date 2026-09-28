# Quickstart / 验收协议

以下为实施必须提供的**目标脚本接口**，当前尚不存在，不能把本文当作已经运行的证据：

```bash
npm ci
npm run --workspace plugins/agent-ui test
npm run --workspace plugins/agent-ui test:contracts
npm run --workspace plugins/agent-ui test:integration
npm run --workspace plugins/agent-ui test:browser
npm run typecheck
npm run build
```

插件脚本必须真实运行对应测试，不能 alias 到一个不相关的既有 smoke。现有桌面回归、C7、产品 smoke 按集成基线实际命令执行，保存命令/版本/退出码/完整日志。继承红按 ID 和原因比对，不能只比较计数。

## Gallery 与浏览器矩阵

`npm run --workspace plugins/agent-ui dev:gallery`：仅本地 loopback、独立临时数据、受控 provider/consumer，输出实际 URL；不默认打开真实桌面用户数据。渲染组件需经真实 C7 服务。Playwright/现有浏览器工具运行：

1. 12 个组件分别正常、空/缺席、失败/未知、禁用；深浅主题与 360/768/1280px 容器截图。
2. 连续追加消息时在底部跟随，向上滚动后不抢；代码展开不跳到错误消息；显式回底恢复。
3. IME composition Enter 不发；Shift+Enter 换行；建议列表 Enter 只选建议；双击不双发；草稿不自行清空。
4. modal 内 selector 的 Tab/Escape/焦点回归；不使用 document.body 默认 Portal 绕开宿主容器/inert；无鼠标完成审批/问答。
5. 替换 Tool 提供者，Conversation/Composer不重置；卸载时保留描述，旧动作同步失效；恢复新代次后旧回调仍失效。
6. 注入危险 HTML/URL/Markdown 图片，浏览器记录外部 request 为零、无脚本执行。用户显式打开链接只触发 recorder，不实际导航。
7. 200 条混合消息、最后一条累计 50 次流式更新、一个超过 800 行 diff：交互不白屏、截断明示；记录设备、耗时与 DOM 规模，不凭主观“顺滑”宣称性能通过。
8. `.aui-root` 外放原生 button/table/pre 对照；加载/卸载插件前后 computed styles 不变。reduced-motion 不产生持续 shimmer。

## 证据产物

报告存 `plugins/agent-ui/reports/` 或批准的 spec报告目录：BASE/C7/HEAD SHA、任务矩阵、上游移植映射、所有命令退出码、测试 ID、浏览器截图索引、bundle/API 单例检查、已知未验项。完整大日志/浏览器产物放忽略目录并给恢复/重跑命令；关键结论和来源记录入 git。

这里只证明 UI 与受控消费链；不证明真实 Harness、model/profile 配置或工作系统已接入。
