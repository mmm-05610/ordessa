# 019 · tasks

- [ ] CP-1 白名单改摘要制：access-entry.mjs 条目 {file} → {sha256}（保留 file 仅
      作诊断输出），读取候选文件算摘要比对；摘要清单的生成方式（构建期钉进模块
      常量）与更新流程写进 README。
- [ ] CP-2 注入端口：harness 声明「controlled-peer allowlist」配置面（环境/配置
      注入，默认=内置摘要表）；装配注入归 AR-1（core），注入优先于内置。
- [ ] CP-3 三测试跟随：access_entry_staging / access_launch_route /
      server-acp 两测试改为摘要断言（含负例：内容篡改→拒、路径搬家→过）。
- [ ] CP-4 边界守卫（本侧版）：plugins/harness/tests 加"src 不得引用 tests/ 路径
      常量"扫描（regex 用 core 建议的任意形态模式
      `tests[/\"'.  ]*(acp_orchestration|acp-connector|integration)`）。
- [ ] CP-5 report：行为等价证据 + AR-1 注入面对接说明。
