# 009 证据 — 桥/交互面（收口）

2026-10-04。前序：008@b7d722a5c5。委派账：test-author 三轮（IME 9 绿、样例#3 30 绿、连接/桥
20 绿）、主代理自建（SDK 出口、dialog 四步、SurfaceAPI、执行域门、诊断门、预算门、lease 重核）。

## 任务对照（S/I 全过）
- **T009-01** ✅ SurfaceAPI 实现（4a17fa9297）：registerSurface/attach/write(ticket)/observe、
  target/epoch/lease、只读面拒控制、raw-only 拒 reliable 不降级、预算/gap/scope-unknown；
  DRIFT-1（全仓无实现）闭合，T 的缺席钉按其指示改为结构断言。
- **T009-02** ✅ 连接生命周期 9 绿（句柄身份/代次/settlement 形状/late 释放/CloseOutcome 真枚举——
  DRIFT：'released' 是 Lease 词表不是连接枚举，钉真实）。
- **T009-03** ✅ 桥三态 11 绿 + **call lease await 重核实现**（2642603c7f）：mid-flight revoke
  → typed Refused('lease-revoked-after-await')，stale generation 同理，永不抛（守 C-03 §2）。
- **T009-04** ✅ 执行域门 3 绿（可信内建白名单/禁第三方 main 变量动态 import/隔离姿态钉）。
- **T009-05** ✅ 预算/gap 门 2 绿（未知帧捕获有界合并 scope-unknown+gap；超预算帧只留摘要）。
- **T009-06** ✅ IME/输入 ticket 9 绿（composition 尾 Enter 不发/单发/晚 ack 不覆盖/焦点回归/
  Esc 单层）。
- **T009-07** ✅ 样例#3 非 Chat terminal/document（30 绿，三样例集齐——E2 完整）。
- **T009-08** ✅ dialog 能力四步（OS 能力/Workbench dialog 控制器/Profile window.confirm 退役×2/
  12+7 测试）。
- **T009-09** ✅ 诊断复用门 5 绿（observe-once/超时 honest unknown/脱敏/日志非 Receipt 主账）。

## 门对照
G009-1 依赖/结果：全部 S/I 有真实测试与命令证据；U（真实 GUI/IME/多窗口）保持待验不报 DONE。
G009-2 前序 SHA 链完整。G009-3 红集对照（rig 86/87=U1 登记红；products 43/44=pi 钉红）。
G009-4 无凭据/真实数据/未授权操作。

## 验证终态
runtime 116、workbench 84、native-bridge 13、connections 29、server-bridge 83、chat 84、
profile 21、rig 86/87、products 43/44、样例 10+6+5+3+30、typecheck 0。

## 移交
1. U 面：真实窗口 IME/焦点/多窗口 dialog → 011/012（授权后）。
2. T009-06 的 onTriggerDisappear 命名语义、Chat lease 原语 = UNKNOWN（010/012 定夺）。
3. 薄壳与 T008-04 载体决策照旧待批。
