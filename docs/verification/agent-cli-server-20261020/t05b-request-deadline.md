# T05b：请求 deadline 从硬编码改为可配置（2026-10-21）

## 问题

`apps/server/src/ordessa_server/composition/registry_runtime.py` 把每次 `operations.call` 的
RequestContext 截止时间硬编码为 `now + 30s`，慢模型/长操作会被截断，且无法枚举验证。

## 改动

- `RegistryRuntime(..., deadline_seconds=30.0)`：校验 1..300 秒，`operations.call` 使用该值。
- `build_product_registry_runtime(..., deadline_seconds=30.0)` 透传到两个构造路径（注入装配 / 配置装配）。
- 服务配置 `access.requestDeadlineSeconds`（**可选**，数字 1..300，默认 30）：
  - `configuration_from_document` 放宽 access 段的可选键并校验；
  - `ServiceAccess.request_deadline_seconds`；
  - 配置装配路径把该值传给 runtime。
- 零配置不动（默认 30）。

## 验证

```
load_service_configuration(未写 requestDeadlineSeconds) → 30.0
load_service_configuration(requestDeadlineSeconds=300)  → 300.0
requestDeadlineSeconds=0 / 301 / "x" → ServiceConfigurationError: must be a number in 1..300
pytest 指定集合（config providers 31 + cli 92 + full-stack + http entrypoint）→ 127 passed / 0 skipped
```

尚未用真实慢回合触发（需要另一次真实调用，预算内可做）；本次只证明"可配置 + 校验 + 装配"。
