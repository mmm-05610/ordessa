# 夜间产物独立验收 — 2026-10-03

验收快照：`7951bf06a258d2dc41402556eb61319b8bab5cbe`。
对照：`night-proposal-20261002.md` 与 `night-report-20261002.md`。

结论：**部分通过，不作为整个夜间批次或 Desktop 产品已完成的证明。**
本轮没有修改实现、合并、推送、重启用户服务或调用真实模型。

## 逐项结论

| 项目 | 结论 | 已验证范围 / 未完成范围 |
| --- | --- | --- |
| N1 Pi Profile A → model B → Profile A | 不予完整验收 | 已安装 v2 资产的规范逆向切换零推理探针通过；新增诊断与拒绝分类有实现。用户实际 endpoint/credential 漂移根因仍未确认，实际聊天逆向切换未重验；拒绝分类还存在下述归属检查缺陷。 |
| N2 配置顺序、稀疏覆盖、隔离与输入回归 | 受控测试通过 | Model contribution、Profile chat、Chat suites 独立复跑通过；不能等同 Electron + Server + ACP 真实操作通过。 |
| N3 装配与回归 | 受影响范围构建通过，整体部分验收 | 独立 typecheck、18 extensions build、定向 Python 与 Workbench 回归通过。没有独立复跑全部后端历史红项，也没有三品牌真实聊天验收。 |
| N4 核心盘点、内部整理 | 通过约定的小范围验收 | 两套 Settings 注册机制、平台/Workbench 边界等已有盘点；Workbench 归组是文件移动和 import 调整，未擅自迁移公共接口或改内核行为。不是一次全面架构重构。 |
| N5 资源接线 | 部分完成 | Skills 新增 5 个隔离闭环测试，验证现有服务和投影契约；该提交仅增加测试文件，没有新增生产接线。实际原生 Skill 加载与默认产品装配尚未证明；MCP、Prompts 未启动。 |

## 必须修复的发现

### 拒绝返回路径漏掉注册表归属复核

位置：`plugins/harness/src/ordessa_harness/server_acp/registry.py`，
`query_native_operation_state()` 的 `except NativeConfigurationRefused`。

普通成功返回路径会检查 `self.get(connection_id) is channel`、channel ended、
native owner；`-32602` 拒绝分支直接返回 `refused`，绕过同一检查。
底层 `_configuration_rpc` 能检查旧 channel 内部的 owner，不能证明 registry
仍绑定该 channel。上层 `_proven_refusal()` 也只有查询前复核，没有查询后复核。

独立受控反例：复用 `test_native_operation_state.py` 的真实 registry fixture，
在调用 channel RPC 时先从 `_by_id` 移除 channel，再抛
`NativeConfigurationRefused(-32602)`。实际结果：

```text
owner_still_registered: false
classification: refused
```

期望：归属已失效时保持 unavailable/unknown，不将旧实例证据升级为当前
实例的 terminal refusal。修复应仅补齐拒绝路径的归属复核及反例，不放宽
unknown，不重发效果，不侵入 Harness 原生业务。

后续修复记录（用户授权后）：已将成功/拒绝结果统一经过最终归属复核，
补 8 个变更归属反例；受影响 Python 加 ACP 边界回归 79 项通过，
已安装 Pi v2 零推理 A → B → A 探针再次通过。该代码发现已修复，
用户实际三轮聊天及原失败根因仍不能据此标记通过。

随后用户授权启动及最多三条短消息，真实 Electron 新会话已完成：
flash Profile 首轮 ONE_OK → 单独 v4-pro 次轮 TWO_OK → 清除/重新选
flash Profile 第三轮 THREE_OK 松果73。后两轮草稿清空、无告警，最终模型
flash。实际切回链在这次测试通过；旧失败的 endpoint/credential 漂移根因
仍未确认，不清历史 recovery。不把清除/重选两步算成同一 Profile 一步重应用
已通过；此 select 同值不触发问题需改。截图与启动现场见 takeover-progress。

### 关于超时反例的限制

另外构造过「原始注册请求 timeout，后续查询返回 refused」的 service fixture，
结果会成为 terminal refused。但这单独**不证明实际 Pi 发生误判**：已安装
Pi `registration.apply` 在首次 await 和原生效果前写入保留操作记录，记录不删除。
是否可把 absence 当作拒绝还依赖消息处理顺序、同一实例和该查询的专属协议。
应补此协议依据及跨请求顺序反例；本轮不把纯 mock 组合宣称为实机根因。

## 独立复跑

以下全部退出码为 0：

| 套件 | 结果 |
| --- | --- |
| Python：Pi registration、native operation state、product native config port、Skills N5 | 60 passed |
| model-provider/chat-contribution | 114 passed |
| profile/integrations/chat | 77 passed |
| chat/frontend | 78 passed |
| workbench | 70 passed + 7 node guard tests passed |
| 合计上述测试 | 406 passed |
| root typecheck | 通过 |
| root build | 18 extensions，通过 |
| git diff --check | 通过 |

真实已安装资产零推理探针：

```bash
.venv/bin/python plugins/harness/packaging/pi-profile/probe-reverse-switch.py /opt/ordessa/harnesses/profile-pi-startup-admission-v2/artifacts/pi-profile-runtime
```

结果：startup `ordessa-start/first` → forward `ordessa-next/third` →
reverse registration `observed` → reverse `ordessa-start/first`；
`modelPrompts=0`、`processExit=0`。使用隔离临时实例，不使用用户凭据或全局配置。
这是适配器链证据，不是生产 Profile 发送全过程验收。

执行者报告仍登记 Server/Harness/model-provider 后端历史红项；本轮没有把
受影响范围绿转换成全仓绿，也没有将执行者报告的历史计数写成独立实测。

## 后续顺序

1. 修复拒绝路径归属复核，补新增失败反例并复跑定向套件。
2. 在产品中复验 Pi：Profile A 首轮 → model B 次轮 → Profile A 第三轮；
   验证实际 model 显示、草稿保留、发送结果和输入不闪烁。需另外确认服务重启/真实调用授权。
3. 产品中逐一验收 Codex 官方登录、Claude API 的首轮、后续轮和配置切换，
   再测试两个同时会话隔离。未执行前保持未验。
4. 资源工作另列：先确认 Skills 默认装配与真实 Harness 应用，再做 MCP，
   然后盘点 Prompts 已有接线；不以 5 个投影测试代替资源产品功能交付。

原有 `docs/ui-preview/01-empty.png` 改动和 `.zcodeignore` 未处理；不属于本次验收。
