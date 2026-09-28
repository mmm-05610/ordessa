# 015 · api-requests（消费台账）

格式：AR 项 = 所有者 / 调用方 / 消费面 / 实测可用性 / 失败反例。可用性以"main 实测 /
分支实现（SHA）/ 缺失"三档标注；执行者实测后回填，不改判不打折。

## 实测可用性总表

| AR | 所有者 → 调用方 | 消费面 | 可用性（写包时） |
| --- | --- | --- | --- |
| AR-1 | harness → P-A/P-B | C2 注册（contributions.py:21）+ C4 apply（configuration_service.py:150）+ permits | **main 实测可用**（011/014 已走通同链） |
| AR-2 | model-provider → P-B | provider 解析（凭据引用/model/base_url） | 分支实现（codex/plugin-model-provider；014-B 加工中） |
| AR-3 | agent 域（contracts/conversation/sessions）→ P-B | 会话轮次完成/会话结束事件 | **未知**（main 有契约文件，事件面未实测） |
| AR-4 | prompts 域 → P-B | instruction 槽多来源 facet 合并（顺序/转义） | 分支实现中（八家 EXT） |
| AR-5 | P-A → P-B | memory 四键（开关/预算/抽取模型引用/绑定品牌集）的 facet 契约 | 本批新建（契约在两包 spec 定死，P-B 只依赖契约不依赖代码） |

## 逐项

- **AR-1**：C2/C4。失败反例：重复 adapter_id/facet 冲突必须被注册处拒绝（014 已有
  同类用例），不得静默覆盖。
- **AR-2**：P-B 只消费"解析后的 provider 定义"。失败反例：用户只配了自定义 OpenAI
  兼容端点（非 bundled 三家）时，P-B 必须报"当前无可用 bundled provider"并保持关闭，
  不得拿自定义端点硬塞 OPENAI_API_KEY 冒充 openai。
- **AR-3**：执行者第一步实测 `plugins/agent/contracts` 的会话/对话事件形态；若 main
  无公开事件面，登记"缺失+需要的最小事件形状"报回主会话，不改 agent 域代码。失败
  反例：事件丢失时捕获停止但注入仍可用（读旧记忆），不因捕获失败阻断会话。
- **AR-4**：与 prompts 域 facet 的合并顺序（指令在前、记忆块在后）、转义（记忆正文
  不得破坏指令结构）。失败反例：prompts facet 缺席时记忆块仍可独立注入；两者都缺席
  时 instruction 槽不产生空壳内容。
- **AR-5**：键名与语义在 P-A facet schema 中定死（`assets.runtime-preferences` 的
  memory item）；P-B 读同义键渲染自己的设置面。失败反例：P-A 未安装时 P-B 的记忆
  开关回落到自身 facet 默认值，不报错。
