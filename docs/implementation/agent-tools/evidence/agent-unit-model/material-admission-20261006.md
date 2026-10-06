# 016 同Registry材料能力准入（2026-10-06）

基线215c503060。多gpt-6-luna：core_impl五原生产文件、wire_impl唯一新test、core_review只读攻击；root文档/指导/串行验证/Git。原资源entry加第五能力快照，旧二元与四元lookup原形；无新索引/权限/执行账。新metadata包装原014三个字段+能力副本，不泄露raw provider/callable，权限仍独立agents.resources read。

## 攻击与修订

Stage/commit/read重核显式能力；legacy静态无声明继续C1注册，新增exact视图明确unavailable、list省略。None后增声明（包括坏getter）不能当legacy省略，必须重新宿主接纳；active唯一Host/原对象先核，inactive省略。非法ID在ACL后查表前typed拒，无原值回显。声明错误包装原CoreDTOError，明确发表前拒绝仍原路径清理still-staged；未知publish不扩大rollback。

独立终审发现能力实例to_dict可被object.__setattr__覆写，直接按四字段复制且lifetimes只exact tuple；tripwire覆盖stage/commit/read不执行覆写与恶意tuple迭代。能力property要求纯声明，但不声称Python plugin沙箱或防所有恶意自定义getter。新测试包括stage/commit整批拒、纠正同ID重试；尚未实测先缺能力→unregister/新activation声明后的重新发现，不用stage失败retry代替该场景，更不说明旧operation能替换新provider pin。

## 串行验收

```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_material_provider_admission.py docs/implementation/agent-tools/evidence/agent-unit-model/test_material_contract.py docs/implementation/agent-tools/evidence/agent-unit-model/test_resource_provider_admission_view.py -q --tb=short
```

55P/0F，exit0，0.27s，新增20+十五14+十四21；14个新增函数经参数化收集20，不重复累计为产品场景。无skip，仅in-memory真Environment/Registry的单元/合同，无材料效果或原生过程。

```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c packages/backend/pacthold/pyproject.toml packages/backend/pacthold/tests tests/integration/environment packages/backend/environment-api/tests -q --tb=short
```

307P/0F，exit0，7.80s，SKIPPED_TOTAL=0。原公共方向/C1/API断言保留；runner仍报告worker/sidecar/ACP资产ABSENT，不能当资源齐全。

```bash
PYTHONPATH=plugins/harness/codex/src:plugins/harness/pi/src:plugins/harness/claude-code/src:packages/backend/harness-transport/src:plugins/harness/records/src /home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests -q --tb=short
```

产品全套788P/0F，exit0，217.57s，session69317已terminal。源码/测试始终冻结；期间只准备获用户裁定的下一原Store设计。

## 边界、缺口及成本

只元数据准入，不授resolve/release authority、不调用旧C1 acquire；原作用路由、原具名步骤/Usage、未知查询、owner消费/三生命周期仍未实现/未验。CLI/Skill仍PARTIAL，不启材料保证；阶段性原Store能力用户已采用，尚未实现。真实模型0、第三方安装0、用户数据/服务/凭据/全局配置操作0、无push/主树合并；.env不读取不入库；费用unknown，以平台账为准。
