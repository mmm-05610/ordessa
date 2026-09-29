## 1) 三个最重要问题

1. **specs/016-overnight-batch/reports/CMP-SK-report.md:28（同 :82）**：「433 collected = 427 passed + 6 errors」与「收集期 error（导入链断裂、被测逻辑未执行）」自相矛盾——import 失败属 collection error，不会被计入 collected（此时应为 collected 427 / 6 errors）；若确为 433 collected 则 6 项是 setup/装配期 error，"收集期失败"的表述就不准确。计数口径与失败性质须二选一，现在的算法可能被读成"6 项也算进了通过基数"。
2. **CMP-SK-report.md:21、32–34（R1/T00–T02）**：证据指针只写「specs/011-q1-skills/...(main 版)」无 SHA 冻结，与本轮刚立的 T17 `main@b6d2748134`、R0 `ab402f4f7b` 冻结纪律不一致；"main 版"随 main 前移即漂移，指针可复核性打折。
3. **CMP-SK-report.md:43、26–27**：T11 档位写「已实现已验(域内半)」，落在第 11 行自declare的三档口径之外；且声称"文件名与 item 的 G 门对应关系逐条列明"，但 T03 行的 test_frontmatter_spec.py、test_tree_bounds.py 等并无 G 门对应标注，"逐条列明"口径偏松。

## 2) fake green 迹象

未见删断言/空测试/skip 掩盖/谎报通过。6 errors 诚实类型化并如实承认 known-issues.md 无条目、只"提请"未越权写入；T14 真实装载格=unknown、T17 不自证、八家表不冒称覆盖，均是反 fake-green 的正向证据。唯一软性风险是第 1 点的 433/6 计数——若不修正，可能被读作把 6 项未跑项混入"套件实跑绿"的勾选基数；但报告已明示勾选强度=文件存在+套件绿+文件名映射，且不冒称断言级审计，尚不构成谎报。

## 3) 结论

**有保留**——结论方向与证据指针总体可信、写入面纪律干净（零代码改动、唯一新增即报告、越权面如实提请）；但 433/6 计数口径自相矛盾、main 版指针缺 SHA 冻结两处须修正后再收口。
