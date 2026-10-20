# 2.1.0 资产验证与未完成边界

在此worktree已安装的环境执行：

    .venv-nightly/bin/python methods/incremental-engineering/tests/validate_assets.py

显式修改本候选资源后，用同命令加 `--rebuild-release`重建本版编译golden和lock，然后重新验证。该动作仅形成发布候选文件，不注册/启用方法；发布后不得同版本换内容。校验器使用实际Engineering loader/compiler，fixture catalog warning保留。

已运行的验证：全部资源bytes/manifest/lock/compiled golden绑定、schema格式、实际typed编译；语义check satisfied/unknown均不自动pass；空catalog编译拒绝；资源篡改loader拒绝；NOR缺basis schema拒绝；极小替代方法使用同compiler编译。

这些结果不证明来源语义判断正确、官方工程标准合规、真实通知/接受/DID应用、Pi执行或整套产品完成。12条`tests/judgment-cases.json`是人工待复核真值候选，涵盖部分支持/缺依据/冲突/删除/普通自由/重要未知/摘要失真/质量空壳/旧确认/意见非授权/offline不得验收；没有调用真实JEV，对冲突及旧版本确认的运行拒绝仍需Engineering owner测试。新schema只强制材料结构，不靠正文或模板认证人类。

`contracts/capability-catalog.json`为fixture_only；操作声明和可编译wait event都不证明注册/adapters/唯一写权已实现。新增notice、DID apply、feedback owner事件及proposal事件的decisions/baseline/summary/standard-profile绑定须冻结并接入验证。任何缺失明确保持不可用/等待，不回退旧链。

实际最终验收待：父任务选择并接受具体DID标准/修订/条款及裁剪；真实JEV问题/上下文/模型评测并接受校准策略；真实受信人类notice/确认且新修订不能继承旧确认；DID owner同TX/CAS与回读；按已应用目标转换完整spec/plan/tasks和追溯；逻辑executor真实Pi技能/输入/原生证据；结果/验收/反馈连续证据；极小替代方法在同application执行。禁止offline/fake替代最终验收。

先前1.1.0合成fixtures/hash-golden保持历史身份，不改旧Grant/Review绑定来套本版新摘要。fixture-lock仅表示发布资产完整性，不能赋予信任。methods/c09-prototype历史未修改；测试安装构建由父任务串行安排。

当前v1确认以[明确问答决定](docs/decisions/user-confirmation-v1.md)及外置product-chat-confirmation.v1 policy为准：获准主Agent如实记录明确问答可作为依据，不要求再次点击浮窗或独立验签。actual出处限制、agent-attested等级、exact版本/scope及正式owner回执仍需保留；旧强验证建议不再作为v1硬阻塞。
