# S-09 证据：默认安装闭包不含上层装配，且门是灵敏的（2026-10-21）

结论：**通过**（非 editable 安装层）。证据由两项可重复测试 + 手工对照构成。

## 1. 可重复测试

```
.venv-w1/bin/python -m pytest -q tests/integration/packages_convergence/test_server_lower_closure.py
→ 2 passed, 0 failed, 0 skip   (VERDICT=GREEN_NO_SKIPS)
```

测试内做的事（`build_installed_server` 从 `python-workspace.json` 递归解析 `ordessa-server` 的**声明依赖**，
外加三个"选择项"：CLI、默认产品部署、Kilo 品牌 wheel）：

1. 闭包内 `pip list` 不含 `ordessa-units` / `ordessa-engineering` / `ordessa-system-access-bindings`；`pip check` 返回 0。
2. 安装版 `ordessa-server` 零配置启动（自动生成 0600 token、handshake），安装版 `ordessa` 用显式 client 配置
   读到 `completed` 的 `agents.profiles.list`。
3. 退役链负例：闭包内 `import ordessa_server.composition.runtime` 失败且错误为 `ModuleNotFoundError: ordessa_units`。

## 2. 闭包构成（15 个 wheel，实测）

decision-runtime、ordessa-agent-tools、ordessa-decision-rules-cel、ordessa-environments、
ordessa-environments-local、ordessa-execution-agents、ordessa-harness-kilo、ordessa-harness-pi、
ordessa-infrastructure、ordessa-interfaces、ordessa-interfaces-contracts、ordessa-server、
ordessa-server-plugin-api、ordessa-server-product、ordessa-system-access-client。

`pip check`：`No broken requirements found.`（先前由 `jsonschema==4.19.2` 与缺 `cel-python` 造成的 3 条冲突，
已通过修正 `tooling/workspace/nightly-python-requirements.txt` 解决）。

## 3. 门的灵敏度（植入反例）

| 步骤 | `import ordessa_server.composition.runtime` |
| --- | --- |
| 纯默认闭包 | `ModuleNotFoundError: No module named 'ordessa_units'` |
| 用 `--no-deps` 手工装入 units/engineering/bindings 三个上层 wheel 后 | **成功**（打印模块名） |
| 卸载后再试 | 再次 `ModuleNotFoundError` |

即：这个负例不是"静态搜 0 引用"，装上旧依赖就会翻绿，因此它能真实发现旧链复活。

## 4. 边界（不宣称）

- 闭包只含 Kilo/Pi 两个品牌（`ordessa-server` 直接依赖 pi，测试额外选装 kilo）；六品牌矩阵属 W6。
- 未验证 `ordessa-environments-openshell`、`ordessa-decision-jev` 进入闭包后的行为（它们不是默认依赖）。
- 非 editable 安装来自本工作树源码构建；未验证从发布索引安装。
