# 今晚有限任务提案 — 待用户确认

只收口 Pi/Codex/Claude + 可选 Profile，不扩新 Harness，不重新跑旧无限目标。
复用当前工作树。建议一个 ZCode 执行者；Codex 不常驻值守。完成指定条目即
交报告停写；需要 sudo/账号交互/产品语义裁决则记录该项阻塞，转做无依赖项。
不自动建树、发会话或设定自动化。

## 任务顺序与验收

### N1：定位并修复 Profile 逆向切换 unknown（最高优先级）

1. 用合成凭证和隔离数据复现：Profile A 模型→单独模型 B→再次选 A→发送前准备。
2. 分段核对 native registration RPC、operation record、owner、generation、
   input digest、configuration digest、credential binding；指出第一个失配条件。
   诊断仅输出白名单条件码，绝不写原始 RPC/凭证/认证摘要到公开日志。
3. 修复仅限我们的接线/状态/适配扩展；品牌差异留在 Harness，Profile 不成为
   必选依赖，model-provider 不解释品牌内部实现。
4. 同一测试修复前失败、修复后成功：既有 owner/session 上可按上述顺序准备；
   模型及上下文身份不被偷偷替换。原始凭证不持久化。
5. 反例：foreign owner、generation 改变、错误摘要、原生拒绝、reply 丢失，
   均不得产生 confirmed/发送许可；unknown 不重放配置操作或 prompt。
6. 若需新系统资产：锁定依赖离线构建、完整摘要、真实适配器零推理探针；
   准备追加安装脚本，保留旧目录。缺 sudo 停在 INSTALL_REQUIRED，不能用可写
   开发资产绕过信任。不改用户 recovery，也不把未来修复视为旧操作成功。

写权：Harness configuration/model 与 Pi 包装、model-provider server、Profile
应用接缝、products/server 薄装配及对应测试；不改内核/平台或上游 Agent 内部。
终态：IMPLEMENTATION_REVIEW_READY / INSTALL_REQUIRED / PARTIAL_BLOCKED。

### N2：独立补齐模型/Profile 交互回归（可与 N1 分文件并行）

1. Profile→模型、模型→Profile、只有 prompt 的 Profile 不改模型，逐项后操作覆盖。
2. 模拟 running 时选择：不 cancel、不 interrupt、不启动第二次 prompt；下一次
   明确发送才应用。普通打字/光标移动不得 query/reconcile/apply/submit。
3. 两个会话交替选择与迟到响应：只更新原目标，另一个的配置/草稿不变。
4. unknown/refused 保留草稿；编辑不导致告警闪烁、重复发送、队列清空；真实运行
   completed 仍触发必要核对。读回失败不把历史回执当当前事实。
5. 增加复现型反例测试并跑 model contribution、Profile Chat、Chat 回归；必要
   时用隔离 Electron 截图，标 fixture，不伪称用户数据或模型端到端。

写权：model-provider Chat contribution、Profile Chat integration、Chat 前端及
对应测试。与 N1 后端写权分离；共同报告只由主执行者写。
终态：CONTROLLED_UI_VERIFIED / PARTIAL_BLOCKED。

### N3：三品牌装配回归与明早报告（依赖 N1/N2 交付）

1. 验三品牌系统资产，默认产品 18 扩展构建、typecheck、边界与受影响套件；
   按测试 ID 对比新增失败，不通过 skip/删断言/伪造 readback 得到绿。
2. 使用隔离数据验证 Profile 缺席仍可普通聊天准备/模型选择，实际 route 不依赖
   Profile ledger；明确不存在自动建全局 Profile 的旁路。
3. 汇总逐条状态、命令/退出码/测试数量、检查点 SHA、待安装脚本及明早用户步骤。
   若未真实调用模型则明写“真实聊天未验收”；不发布“产品全部通过”。

## 边界和费用

- 默认零真实模型调用；旧 key.txt 不读、不提交。需要真实调用另请用户定数量上限。
- 不碰用户 ~/.ordessa、登录、密钥环和全局 Harness 配置；隔离临时数据用完登记。
- 不启停当前用户窗口，不 push、merge main、清工作树、改其他分支。
- 建议最多一个执行者 + 两个互不写同文件的子代理，禁止递归派生。
- 不追加新功能、其他 Harness、协作、通用引擎或整夜无限巡检。完成 N1–N3
  或全部剩余项需用户协助时交付停写，不为填满一晚制造任务。
- 本文件是范围提案，不是已授权派单。最终执行者/并行度/真实调用授权待确认。
