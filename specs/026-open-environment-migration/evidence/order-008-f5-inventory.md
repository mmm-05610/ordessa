# F5 既有实现盘点归档（008-S2 输入，repo-scout 2026-10-04，主代理采纳摘要）

完整清单见子代理报告（22 处 useSyncExternalStore、10+ 手写容器逐条）。采纳结论：

## 合并路线（F5 十模块，依据 §8"先合并局部已有实现"）
- **state/selectors**：以 ui-components BindingImpl/ServiceCore（变化比较+批量+抛错隔离+同源
  React 绑定）为唯一底层语义基准合并；三形态快照（对象/revision 计数/字符串）必须指定收敛方向
  清单，否则双权威成立。参照：sessions 记忆化派生、chat Values idle 回收、Contributions。
- **projection**：E3 readAndSubscribe 全仓 0 命中 [事实]——TS 侧无现成实现。裁定：008-S3 只
  冻结接口+fixture，标注"复用点=Environment 端（003/004 已交付）+待桥接"，不得假装复用。
- **query**：自建 createQueryCache；先例=chat registry queryKey/epoch 屏障、wire-port 三态不重发。
  默认显式关闭重试/刷新/持久化。
- **tasks**：自建；先例=guardRevision/isCurrent、workspace inFlight 去重、cancelWait 措辞。
- **editing**：自建工具 + 四 owner（ProfileDraftStore/DraftStore/模型表单/SandboxDraft）登记为
  010 迁移清单，S2 不接管（禁第二 DraftOwner）。SecretRef 载体沿用 open-environment/types。
- **uiStorage**：合同自建 + 薄适配 settings-store（缺分区/条件写→扩展宿主适配；跨窗口无现存
  实现→缺适配即 session-only 不许诺恢复）。
- **interactions**：合并进 Workbench overlay 栈+statusbar（addOverlay 既有）；Notification/Progress/
  句柄 API 全仓 0 命中=净新增；宿主三浮层与 update 进度是待合并重复机制。
- **errors**：F5Error 新族，与 wire 三态/ContractValidationError 划界，不重解释。
- **tokens**：一文件一构造点惯例，落 open-environment/f5/。

## 候选库现状（与冻结裁决互证）
- zustand 5.0.15 仅作 @assistant-ui 传递 dev 依赖存在于 lock，产品代码零 import [事实]——
  自建裁决成立，不新增依赖（若未来引入须补许可/版本核验记录）。
- @tanstack 完全无痕迹 [事实]。

## S2 硬约束（防双权威）
1. 新 store 工厂必须吸收 ui-components ServiceCore 或声明其为底层，禁止平行 wrapper。
2. 两套 settings 注册（SettingsContributionToken vs Workbench addSettingsSection）已被
   layering.test.ts 钉死为两套——T008-03 收口对象。
3. f5-counter/f5-react-panel 两 fixture 目录从零建（examples/external-samples/）。
