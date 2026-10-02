# ZCode 本批独立复审（2026-10-02）

范围：`zcode-profile-model-closeout.md` 的 Profile 稀疏覆盖、独立模型应用、产品/前端合成与证据。只读实现审查与受控复验；未修改生产代码，未调用真实模型、安装资产、提交或合并。

结论：**REQUEST_CHANGES**。已有实质可保留成果；下列两项产品接线缺陷修复前，不认可 T04 与完整 P/M/C 全 PASS。另有一项 T05 证据未完成，不应改写为通过。

## 复验记录

- Python 相关全集：`products/server/tests plugins/profile/tests plugins/assets/model-provider/server/tests plugins/harness/tests/configuration_model`，沙箱内 871 passed / 12 failed，28.51 秒。失败均在新增三品牌文件，系统资产真实所有权在沙箱映射后无法验证。
- 真实所有权环境重跑 `products/server/tests/test_native_model_turn_three_brand.py`：15 passed，10.62 秒，exit 0。没有修改 trust policy。两次结果合起来覆盖原 883 条，但不是同一环境整套 883 的独立运行。
- Profile Chat：60 passed，exit 0。
- model-provider Chat：67 passed，exit 0。
- `npm run typecheck`：exit 0。
- `git diff --check`：exit 0。
- build/root gate 本轮未独立复跑；ZCode 报告值仅属引用证据。

## F1 [P1] 点击时间与登记时间不同，最后用户操作优先失效

位置：Profile `integrations/chat/src/glue.ts:203`、`selection.ts:102`；model-provider `chat-contribution/src/next-turn-client.ts:163`；产品 `turn_application.py:420`。

实际链路：

1. 已绑定会话，用户先选含 m1 的 Profile：仅 `store.select`，没有后端选择事实。
2. 用户后选 m2：立即 `chooseForSession`，sink 立即写入 overlay 并分配后端 action_seq。
3. 用户发送：Profile guard 此时才 `selectForSession`，取得更晚 action_seq，压掉用户实际上更晚选择的 m2。

用现有 `_bound_runtime` / `_begin` 产品受控夹具按上述实际 wire 顺序复现：期望 `acme/m2`，实际 `acme/m1`。原 M03 产品测试是在 Profile 已经应用之后再选择模型，不覆盖同次发送前两种控件的点击顺序；前端测试也没有将两套真实 glue 同时组合。

修复要求：用户选择动作进入共同的、有版本的意图顺序，再在发送时一次应用。不要用提交时的 Profile 注册时间替代点击时间；选择不得触发原生 apply/restart。可通过选择时按会话登记意图，或统一冻结待提交动作序列实现，但必须处理异步乱序和失败，不以固定 guard 顺序猜先后。

验收：真实 Profile glue 与 model-provider guard 组合，覆盖 Profile(m1)→模型(m2)、模型(m2)→Profile(m1)、模型(m2)→不含模型的 Profile、两条请求乱序、应用中后续选择；核对实际最终模型、其他项保留、每次发送恰一次原生副作用、零全局写回。

## F2 [P1] 绑定会话的意图转交失败后，发送仍可按旧模型放行

位置：产品 `turn_application.py:424`、model-provider 后端 `choices.py:245`、前端 `chat-api-entry.tsx:285`。

sink 将写 overlay 的任何异常折叠为 False；模型队列继续保留意图并返回 pending-next-turn。前端只凭 Profile binding 即跳过模型关卡，没有检查这次意图是否确实被转交及应用。

受控复现：同一已绑定产品 runtime，令 `core.sessions.set_overlay` 抛错，选择 m2 仍得到 pending-next-turn；Profile 下一轮仍成功得到 receipt，但原生应用值为旧 `acme/m1`。现有 bound model guard 会无条件 ready，无法阻止 prompt。

修复要求：区分“确实未绑定（走独立路线）”与“已绑定但转交拒绝/未知”。后者必须保留意图并阻止发送，不能静默降级。发送关卡核对当前 intent 的序号与确认/拒绝/未知事实，不能将 UI 配置项的存在等同于本次模型意图已应用。保持单次 application，不另加第二次 apply。

验收：转交明确失败、转交结果未知、Profile 注册/卸载变化、迟到的转交结果；失败/未知均零 prompt、保留草稿及新选择；成功只消费匹配序号；正常绑定发送仍恰一次 apply。

## F3 [验收缺口] T05 三品牌真实无模型进程检查尚未完成

原任务要求已安装资产的三品牌无模型 native 端口检查。当前新增测试确实经过生产组合、方言编译、journal 与真实资产校验，但 native ACP 进程仍为 double。ZCode 报告自己注明“真实三品牌无模型进程验证属用户验收”，却把 T05 标 PASS；这是将原任务内要求后移，不能用该标记收口。

修复要求：保留受控测试成果与 trust 证据，但 T05 标为 PARTIAL，或补实际 Pi/Codex/Claude adapter 进程 initialize/session/new、配置查询及关闭的无模型证据。禁止发 prompt/读取测试 key/登录/安装。资产不能支持时，列出准确阻塞及最小安装请求，其他已通过项不回退。

实际模型聊天、完整安装包、Claude 再分发与既有上游密文恢复限制继续单列，不要求本轮修上游或扩展 host。

## 一次性修复边界

只修上述 Profile / model-provider / 产品胶水与对应组合反例；不得改 host、发明第二个会话/应用账本、降低 trust、修 Harness 内部缺陷。修复后复跑文档既定相关全集、两前端 workspace、typecheck/build/root gate，逐条更新 M03/M06/M08/M11/M12 与 T05 的证据等级，集中交付一次。

## 修复轮复审（2026-10-02，17 时）

原 F1/F2 的直接缺陷已有实质修复：点击登记串行化、转交失败三态与发送阻断；新增后端 8 条组合反例及真实双 glue 前端反例。独立复跑后端定向 64 passed，Profile Chat 68 passed，model-provider Chat 84 passed，typecheck / diff-check exit 0。前端存在 React act 警告，未导致失败。本轮未独立复跑 build/root gate/891 条全集，其报告值仍为引用证据。

F3 已提供真实安装资产进程的 initialize/session/new/配置查询/关闭证据：Pi、Claude 裸无模型通过；Codex 在本地拒绝端点的测试 provider 前置配置后通过，裸 session/new 的 Authentication required 明确登记。认可这属于真实无模型进程证据，**不等于官方登录、真实聊天或配置应用验证**；无需为满足检查而解决上游认证要求。

### 剩余一个阻塞族：点击到发送之间的绑定变化不能静默丢意图

执行者报告 §8 将“独立意图 + 绑定在点击后出现”追认为正确语义，并在 `intent-route.test.tsx` 写测试要求放行。该判断不符合用户已定规则：不含 model 的 Profile 不得覆盖/忽略先选的模型；模型意图未应用不能允许 prompt。

当前前端 `chat-api-entry.tsx:332` 对 bound + independent 意图仍 ready；后端首次注册 Profile 不把该独立队列意图纳入 Profile 本轮。用真实产品受控夹具复现：

1. 原生会话未绑定 Profile，选择 m2，wire 返回 `intentRoute=independent`。
2. 随后选择一个不含 model 的 Profile，发送时注册该 Profile 会话。
3. Profile beginTurnApplication 拒绝 `This native route requires one supported model choice`，原生操作 0 次；用户 m2 已选择，却没有进入这次配置目标。

这既证明正常路径仍会卡住，也解释了前端直接放行测试为何不足：测试用一个假的 Profile binding，没有证明 Profile application 真正消费/覆盖了该模型意图。

修复要求：首次绑定时将已有独立模型意图与 Profile 声明 mask 按点击顺序原子归约，然后只应用一次；model 缺席的 Profile 保留此前模型，model 存在且后选的 Profile 覆盖此前模型。未完成归约/交接时明确拒绝或未知，不可仅凭 binding ready。不能要求用户重选模型来替代正常功能。

同一交接协议应覆盖反向变化：routed 后 Profile 卸载，后端不得以 no-intent 冒充已应用；至少返回明确拒绝并保留意图，前端重挂/客户端缺席时亦不能绕过。该项已在原 F2 验收里要求“Profile 注册/卸载变化”，不是新增业务范围。

集中补组合反例：unbound M2→首次绑定无 model Profile 保留 M2；unbound M2→首次绑定含 M1 Profile 得 M1；绑定发生时请求乱序；routed→卸载→前端重挂无缓存仍零 prompt；每次成功仅一份 application。移除/改强上述“绑定出现即放行”测试，不能把未应用称为正确语义。

本轮结论：**原修复成果保留，F3 证据接受；REQUEST_CHANGES 仅限绑定变化的意图交接收口。未合并，未调用真实模型。**

## Codex 实施收口（用户授权“你来修”）

首次登记现在在公开 Profile binding 前，将已有独立模型意图通过注入回调
转入 Profile 临时配置层；model-provider 校验目录版本、唯一目标与序号，
保留同一队列，转交不执行原生操作。后续 Profile 显式选择仍按 mask/
action_seq 覆盖，未包含模型时保留模型。既有会话的首次 Profile 点击也
即时登记并进入共享 FIFO，避免首次绑定再次以发送时间代替点击时间。

模型 guard 在绑定出现后查询新交接状态；未交接/查询未知不放行；没有
前端缓存时仍查询后端。routed 提交由后端复查 binding 的 owner 存活，
卸载或替换时 refused/HANDOVER_UNRESOLVED，意图不丢。

证据：新增后端 3 例修复前 3F/8P，修复后 11P；全集 894P（真实资产所有权
环境，39.99 秒，exit 0）；Profile Chat 68P；模型 Chat 87P（新增首次登记
FIFO、交接新观察和无缓存阻断反例）。typecheck/diff-check exit 0；build
19 扩展 exit 0。改强了旧“独立意图遇到绑定即放行”的断言，未删覆盖/skip。

根聚合 npm test 41/41 套件通过、exit 0；末次源码变更后重新构建
19 个扩展、typecheck/diff-check 均 exit 0。详细进度记入 takeover-progress.md。
本次没有真实模型调用、安装、
host 修改或提交/合并；交接缺陷实现已收口，真实三品牌 Desktop 使用验收
仍单列，不用受控测试代替。
