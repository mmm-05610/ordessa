# 交付与验收入口

## 现在可以检查什么
本包文档结构与反例守卫：
```bash
node /home/maoqh/projects/ordessa/specs/031-jev-decision-module/checks/validate-materials.mjs
node /home/maoqh/projects/ordessa/specs/031-jev-decision-module/checks/validate-materials.test.mjs
```
这两条不安装/执行pydantic-graph或Jev SDK、不调用模型、不操作Agent。
材料检查只能确认结构/编号/链接/映射完整，不能验证业务或生命周期正确性。

## 实施后应该能看到什么
1. offline_assignment：输入清楚任务，显示选用已有单元/新配置方案的提案；所有原生操作0。
2. 模糊任务：显示具名clarify/revise缺口，不启动任何单元。
3. alternate_flow：调整可信判断顺序，运行器源码不变。
4. 新配置kind含小数：不改引擎即可选择并由外部owner校验。
5. 取消/日志故障：不显示ready，不重发潜在模型调用。
6. 提案之后核心版本变化：实际消费前检查拒绝，原状态不被决策日志修改。

目标示例与测试路径见tasks；目前未实现，不给用户伪装成可运行产品命令。


## 当前树可直接离线运行
```bash
.venv-decision/bin/python packages/backend/decision/checks/offline_acceptance.py
.venv-decision/bin/python packages/backend/decision/examples/offline_assignment.py
.venv-decision/bin/python packages/backend/decision/examples/alternate_flow.py
.venv-decision/bin/python packages/backend/decision/evaluation/prepare.py
```
入口串行构建独立 wheel、离线安装基础依赖、对比固定基线、逐场景复验；不发真实模型请求。
需要已有本树 .venv-decision 和 .decision-tmp/wheels 缓存；缺席时明确失败，不自动下载/读取凭据。

Codex纯读范围扩展后，同一离线入口还会从本树以 --no-index/--no-deps/--no-build-isolation editable安装既有 harness-transport 与 Codex Python包，并串行跑家族回归；不安装/启动原生二进制。原owner计算证据不是实际应用保证。真实归档可无key/HTTP复核：

```bash
.venv-decision/bin/python specs/031-jev-decision-module/evidence/codex-pure-read-20261005/verify_archive.py
```
