# 019 非秘密材料原步骤协调（2026-10-06）

基线a94d54639a。core_impl唯一3生产文件、wire_impl唯一产品测试、core_review只读攻击；root指导/合同/串行测试/账本/Git。同Registry提供者、服务器固定Issuer、原Operation/Step/两Usage，零C1作用fallback。不解析Profile、不接Assembly/SecretRef、不新增执行账或权限真值。

## 过程反例与修订

首轮静态审查修复：持久化失败不能第二unknown写掩盖、provider未核query票不能由核心自验冒其已验、旧query观察只能用开始时版本CAS、issue后及返回前同Registry对象重核、完整结果回放核当前query权限/active pin/两holds、寿命能力门和固定provenance。描述证据与本次获取evidence允许不同，不强行合并两个事件。

```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration/test_material_operations.py products/agent-tools/tests/integration/test_staged_operations.py products/agent-tools/tests/integration/test_invocation_authority.py docs/implementation/agent-tools/evidence/agent-unit-model/test_material_contract.py docs/implementation/agent-tools/evidence/agent-unit-model/test_material_provider_admission.py -q --tb=short
```

首次121P/25F exit1 2.63s：源码Node身份无to_dict方法、测试helper漏holder；原作者窄修字段级精确比较及变量，未放宽身份断言。第二次136P/10F exit1 2.96s：query新票必须先原verify_and_consume再claimed-query continuation，source/fixture补既有API时序，不改Issuer。三个纯describe0断言与允许resources-read下纯描述的合同不符，改为describe1并保所有作用0；claim后返回明确unknown符合合同，以unknown/holds/revision/零作用取代错误的必抛预期。第三次145P/1F exit1 2.90s：两次unknown的hold revision应3而非2，只修该计数。最终146P/0F exit0 3.31s（session24399 terminal）。作者原报18函数/27项错误，实际17函数/26项，旧120；不累计重复快照为独立场景。

```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c packages/backend/pacthold/pyproject.toml packages/backend/pacthold/tests tests/integration/environment packages/backend/environment-api/tests -q --tb=short
PYTHONPATH=plugins/harness/codex/src:plugins/harness/pi/src:plugins/harness/claude-code/src:packages/backend/harness-transport/src:plugins/harness/records/src /home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests -q --tb=short
```

核心/API307P/0F exit0 8.40s；无skip，但worker/sidecar/ACP原资产ABSENT。不把runner GREEN_NO_SKIPS当资源齐全。产品全冻结852P/0F exit0 222.66s，session82522已terminal；新26+旧826，不与组合146累计。

## 实测层级和未验范围

新26项真实Environment/Registry/原Issuer与临时SQLite＋受控provider的C级集成：精确固定facts/两个holds、原对象一次resolve、当前query授权回放、无issuer/权限/目录/epoch/pin/descriptor/lifetime拒、claim后拒unknown、lostreceipt无lease query、无Verifier假成功拒、并发旧观察不覆盖、SQLite结论事务失败无部分结果、两hold坏/缺/released不披露完整材料引用。跨环境/跨principal外部调用及所有恶意provider情况未穷尽，不说已全面安全审计。

SQLite重开只验固定facts/claim/Usage持久；新generation+新issuer仅验证不可替旧pin。正式原activation恢复＋新issuer冷query缺公开rehydrate接缝，NOT_RUN/PARTIAL，绝不以同shape重激活/私换活跃环境Store冒证明。此不是生产服务、真实材料内容/消费或Harness证据。P新增0/M0，无安装、用户数据/服务/凭据/全局配置、push/主树合并。.env不读取不入库，子代理费用/token以平台账。

上游reserve前能力preflight、ConfigurationProvider完整引用提取与材料交接、Assembly先材料后计划、真实消费/三寿命/释放、访问/输入writer与结果、CLI/Skill/隔离发行未收口。产品整体PARTIAL；本单绿色只覆盖受控核心acquire/query。

独立Luna最新终审query首次验票与claim continuation时序、回放Registry/hold、故障/CAS无阻断；全19工单strict exit0，git diff --check exit0，只资料/格式门。AT_019_PARTIAL（受控核心获取/查询已验，生产消费及原activation冷query未验）。
