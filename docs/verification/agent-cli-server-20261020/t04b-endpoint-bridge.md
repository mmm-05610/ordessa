# T04-B：endpoint 适配器上提为 agents owner 共享桥接（2026-10-21）

## 改动

- 新增 `packages/execution/agents/src/ordessa_agents/bridges/environment_endpoints.py`
  （由 CLI `composition/endpoints.py` 迁移），注入式：
  `EnvironmentEndpointResolver(endpoints, *, invocation_resolver, process_request_factory, refusal=EndpointBridgeRefused, process_observation_factory=None)`；
  所有拒绝改为 `raise <refusal>(...)`，`launch` 的 except 也捕获注入的 refusal 类。
- `EndpointBridgeRefused(RuntimeError).code='ENDPOINT_REFUSED'`（消息形状 `CODE: detail`）。
- `apps/cli/src/ordessa_cli/composition/endpoints.py` **删除，无 shim**；CLI 从新模块导入，
  传 `process_request_factory=ProcessRequest.build, refusal=EnvironmentRefused`（异常类型与消息与迁移前一致）。
- `packages/execution/agents/pyproject.toml` 登记 `ordessa_agents.bridges` 显式包；README 补桥接契约。

## 主控独立复核（不是子任务自述）

```
grep -rn "ordessa_environments" packages/execution/agents/src   → 无输出（exit 1）
ls apps/cli/src/ordessa_cli/composition/endpoints.py            → No such file
grep "composition.endpoints" apps tests                         → 无输出（无转发层）
python_workspace.py --install                                   → exit 0
python -c "from ordessa_agents.bridges.environment_endpoints import …" → ok（code=ENDPOINT_REFUSED）
pytest apps/cli/tests                                           → 92 passed
pytest pkgconv 5 文件（entrypoint/registry/default-agent/authority/full-stack） → 12 passed, GREEN_NO_SKIPS
pytest test_agent_endpoint_adapter + test_agent_lifecycle_credentials           → 4 passed
```

## 依赖方向

`agents → environments` 依赖边**未新增**（源码 grep 为空）；CLI 与 Server 共用同一份桥接，
环境类型由调用方注入。下一步：preparation 解析器按同法上提（进行中），然后接 instances/native。
