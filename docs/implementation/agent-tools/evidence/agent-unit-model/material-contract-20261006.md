# 015 非秘密材料纯合同证据（2026-10-06）

基线52607c1e80。三名gpt-6-luna分别源码、新测试、只读攻击；主会话指导、冻结合同、串行验证、文档/Git。用户已采用受权扩展；本片仅纯类型与可选端口，不取得材料、不建Usage、不装配Assembly、无真实模型/用户服务调用。

## 修改与独立反例

ResourceRef与Host pin分开；planned Node、目录、epoch、用途、descriptor绑定输入摘要；获取/释放各自原请求关联，释放允许新操作而不复用原三字段step身份。两个成功结果都须类型化匹配回执；unknown无回执或错误正文。receipt引用不是消费或授权证据，DTO不修改Usage。原InvocationContext参数，不新增权限签发器。

独立审查抓获并修复：获取回执与自己的request摘要脱钩；释放过度限制同操作；释放空成功；helper不能区分坏property与缺席（包括property内部AttributeError）；静态导入取样期间缺inspect已补。helper只返回纯能力副本，检查同对象C1和材料八方法，不调用它们；读取能力property契约要求无作用，但Python自定义getter违反纯声明的行为仍需可信部署提供者保证，不能据helper声称隔离恶意Python代码。

## 串行命令、退出码和过程

Python解释器均为 `/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python`，本实施树cwd。

```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_material_contract.py -q --tb=short
```

首轮8P/6F，exit1，0.35s：合法schema/1被源码当路径拒绝（影响三个测试）；新测试错误把孤立Host pin当可自行判断资源环境、ReleaseResult旧位置参数、原C1夹具不满足冻结dataclass。源码仅schemaVersion用窄精确标识验证，资源及provider版本不放宽；新夹具改真实request跨环境拒绝、关键字error_code、真实C1 frozen类型，保留原断言意义并加绝对路径/遍历反例。

第二轮13P/1F，exit1，0.23s：新测试错误要求单独跨操作release receipt拒绝；修为合法foreign receipt不能装入当前不同correlation结果，保留错误关联拒绝。

最终14P/0F，exit0，0.20s；14个测试函数含多组正反例，不把循环内assert算独立测试数，无skip。

```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c packages/backend/pacthold/pyproject.toml packages/backend/pacthold/tests tests/integration/environment packages/backend/environment-api/tests -q --tb=short
```

307P/0F，exit0，8.22s，SKIPPED_TOTAL=0。原公共依赖方向/C1/API断言保持。runner报告worker/sidecar/ACP资产ABSENT，不能算资源齐全或产品可用。

```bash
PYTHONPATH=plugins/harness/codex/src:plugins/harness/pi/src:plugins/harness/claude-code/src:packages/backend/harness-transport/src:plugins/harness/records/src /home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_resource_provider_admission_view.py docs/implementation/agent-tools/evidence/agent-unit-model/test_configuration_unresolved_secrets.py docs/implementation/agent-tools/evidence/agent-unit-model/test_apply_profile.py docs/implementation/agent-tools/evidence/agent-unit-model/test_management.py docs/implementation/agent-tools/evidence/agent-unit-model/test_assembly.py -q --tb=short
```

106P/0F，exit0，5.32s（014元数据21及既有材料/配置/装配85），无skip，受控端口/临时SQLite合同回归。只增加纯合同与导出，产品788全套在014已跑且未改运行链，本片没有为重复绿再次全跑。

## 未验证范围与费用

单元/纯合同级证据；真实资源获取、丢回执恢复、同Registry能力固定、持久原步骤/Usage/权限、owner消费、三生命周期、隔离服务均尚未验。CLI/Skill未因此增加可用能力。整体PARTIAL，下一片继续原注册表准入，之后才实际协调与消费。模型调用0、安装0、用户数据/服务/凭据/全局配置操作0，无push/主树合并；.env不读取不入库；子代理token/费用以平台账为准，当前unknown。
