# MPX · api-requests 回填(AR-1/AR-6 消费面)

状态:2026-09-29 夜批。主台账 `specs/016-overnight-batch/api-requests.md` 的
model-provider 侧回填;主台账合并归集成收口,内容以此文件为准。

## 1. requestParams 冻结形状(payload `model-provider.choice.v1` 增量,可选)

| 键 | 类型 | 语义 / 校验 |
| --- | --- | --- |
| reasoningEffort | string \| 缺省 | 推理强度;codex 词表 {low,medium,high,xhigh,max}(deepseek 族 {low,high,max})在 compile 钉死 |
| maxTokens | integer ≥1 \| 缺省 | 预算;pi 投影为 models.json 模型条目 `maxTokens`(黄金对象重写) |
| timeoutMs | integer ≥1 \| 缺省 | 超时;**当前无品牌可投影**(唯一 first-hand 在 harness 部署描述符),三品牌皆类型化拒绝 |
| retry | 闭形对象 \| 缺省 | `{enabled: bool, maxRetries: int≥0, provider: {maxRetries: int≥0, maxRetryDelayMs: int≥0}}`(deploy/pi/settings.json 原样);仅 pi 声明投影 |

未知键、类型伪装(bool 冒充 int、≤0 值)一律 `ValueError`(载荷 schema 层同形拒绝);
缺省 ⇒ 与 MPX 前行为逐字节相同(回归钉在案)。

## 2. 声明面增量( descriptor claims )

- pi:+`FieldClaim("file", "pi.settings.json", ("retry",))`;codex:
  +`FieldClaim("file", "codex.config.toml", ("model_reasoning_effort",))`。
- **宿主请求(AR-6)**:pi 的 settings target 需目标权威实际签发
  `pi.settings.json`;未签发时 adapter 以 `CAPABILITY_UNSUPPORTED` 拒绝(不写形似
  句柄)。timeoutMs 是否开 facet 授权面归 harness 域裁定。

## 3. 消费纪律(core 侧)

1. `requestParams` 是"请求级"参数面(014 裁定归 model-provider);会话/运行级
   偏好归 015-A runtime-preferences,不得把同一键双收两边。
2. 拒绝(`AdapterRefusal.code=CAPABILITY_UNSUPPORTED`)是投影结果,不是错误:
   reason 字段自带钉源理由与升级路径。
3. 三态表与逐格拒绝理由见 `reports/MPX-report.md` §2/§3。
