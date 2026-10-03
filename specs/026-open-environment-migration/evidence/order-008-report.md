# 008 证据 — 前端包组与 Workbench 组织权威（收口）

2026-10-04。前序：007@b37a5711ce。R7/M14 期间接收（7fe33bcd70）。
委派账：切片X/Y/Z 通道故障（provider-not-found 整夜），S2–S6 与迁移全部由主代理自建；
test-author 通道正常（U/W 切片）。主代理独占：合同冻结、裁决、Git、守卫钉维护。

## 任务对照（S/I 全过；U 显式待验）
- **T008-01** ✅ frontend 10 包物理迁移（4ff0e3859c）+ loader+host 合并 extension-runtime
  （9b36143924+1869918d13，薄壳保 npm 身份，identity 门 2 测试）。
- **T008-02** ✅ workbench 迁 frontend/workbench（N4 分组保持）。
- **T008-03** ✅ 呈现注册接缝（b846874c63：forScope 组合面注册、缺席诚实回退）+ 快照 uSES 安全化；
  DOM 级呈现互换属 T008-07 U 面。
- **T008-04** ⏳ Agent 域载体分离+Token 身份已由既有门覆盖；HarnessAvailability 物理拆分
  **硬决策待用户**（decision-pending-harness-carrier.md，建议 A：harness-contracts 载体）。
- **T008-05** ✅ workspace/lock/exports/import-map/tsconfig/build/发现全同步（迁移中逐项验证）。
- **T008-06** ✅ 连接器公共契约化（751552c398，AgentNativeBridge 入 native-bridge 公共面）。
- **T008-07** 🔶 typecheck 0 错、build 全绿、workbench/ui/ui-components 套件绿、空产品 smoke（
  electron 本地 staging 4/6）；overlay 定位/Esc/焦点/输入验证=**U 待验**（需真实 GUI 授权）。
- **T008-08** ✅ F2 preflight 同门（87e44493df，6 反例）。
- **T008-09** ✅ 逻辑 manifest+校验器+门（85d4fde2c1，10 manifests PASS）。
- **T008-10** ✅ commands registry/execute 迁 runtime+薄 forward（b147e8ae94）。
- **T008-11..20（R7 F5）** ✅ 全链：oe-f5/1 冻结、状态库/选择、查询/任务/投影、编辑/UI 存储、
  Workbench 交互/上下文/i18n、A96–A103/A109 证据映射、双 fixture 入聚合（44 套件）。

## 门对照
- G008-1：S/I 全过 + U 显式待验（T008-07 GUI 面、A108/A110/A111）→ codeReady 但非 fullDone。
- G008-2 前序 SHA 链完整。G008-3 红集对照全程执行（唯一红=pi 钉，全程逐 ID 一致）。
  G008-4 无凭据/真实数据/未授权操作 ✓。

## 验证终态
runtime 111、workbench 77、ui 30、ui-components 77、apps/desktop 144、connectors 67+48、
products/desktop 40/41、合同 node 10、fixture 5+3、typecheck 0、聚合 44 套件。

## 移交
1. T008-04 HarnessAvailability 载体三选项 → 用户批复。
2. T008-07 GUI 面（overlay/Esc/焦点/IME）→ 真实 GUI 授权后（011/012 U 面一并）。
3. 薄壳（extension-loader/extension-host）退役评估 → 012。
