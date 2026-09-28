# Quickstart：实施预检与验收入口

本包是 Spec Kit 结构的完整设计输入，不是已完成实现。根目录继续 main；本次没有新建 worktree、派发或授权合并。实际实现必须在后续指定的独立工作树。

## 1. 先冻结可执行起点

读取该树 AGENTS、baseline 和本包；运行只读检查：

```bash
git status --short
git branch --show-current
git rev-parse HEAD
git worktree list
```

创建 `evidence/platform-bindings.md`（实施树内）记录：批准的 base SHA、C1/Server/前端公开 API 的 import 路径与类型、会话稳定 ID、提交前准入门、Harness plan/apply/reconcile、Chat 工具栏贡献与 UI binding、产品装配位置。每项附现有源码和一个最小编译/调用测试。

平台观察点不是集成授权：本轮看到 main=`cd7d31f3cf`，前端=`54c2ef4110`，Pacthold=`9e33a4df51`，Server=`d40b13b83f`。不要自动合并这些仍在各自工作树的分支。基线未定只完成只读绑定报告，不在 main 试验。

产品行为以 spec/ux 为准；类型命名适配不需重新讨论产品。发现缺真实发送准入门/运行应用端口时，列缺失符号、归属、最小接口和受影响验收；可继续独立存储/UI 工作，不能绕开边界或称全链完成。

## 2. 旧实现基线

使用实施树自己的隔离 venv，不改其他工作树 editable 指向。按最终批准的平台安装顺序安装本地依赖，再安装 Profile dev extra。下列命令中的 venv 须已经按该树 baseline 准备：

```bash
.venv/bin/python -m pip install -e './plugins/profile[dev]'
.venv/bin/python -m pytest plugins/profile/tests -q --junitxml=evidence/profile.xml
```

安装前确认本地 pacthold/plugin SDK 已安装且版本匹配；不能让 pip 从公共索引寻找私有包。先运行原有测试并留存逐 ID 结果，再适配新契约。测试副本数据根，不读真实用户配置和凭据。

前端新增包必须提供 `test` 和 `typecheck` 脚本，在绑定报告登记真实 workspace 名及命令；不能把尚不存在的命令写成通过。保留根 typecheck/build/桌面 smoke，并分别运行 Profile、glue、会话服务的独立测试，根 npm test 不算自动覆盖所有包。

## 3. 三个独立组合

1. Profile + 零配置面、无 Chat：管理可用；不出现伪造模型/Skill 卡。
2. Profile + model-provider/Skill 两真实 glue、无 Chat：保存/编辑/设置注册/卸载可用。
3. 加 Chat + 受控 Harness：在真实服务接缝上验证下次提交应用和消息准入，不只测 Profile DB。

实际品牌矩阵独立写品牌、版本、字段、live/restart-resume/reset 及证据。受控 adapter 成功不等于 Pi/Codex/Claude 全字段通过；真实模型仍需另外授权。

## 4. 用户验收脚本

- 管理器：展开 Harness、新建中文名称预设、保存；第二窗口制造修订冲突，第一窗口输入不丢。
- 设置页：注册第三配置提供者，同时贡献设置区和预设编辑器；不改 Profile 实现。卸载两处消失，重装存值恢复。
- Chat：A 正在输出时选 B 再选 C，按钮显示 C、原输出继续；输出结束没有应用；下次输入只按 C 应用并发送一次。
- 会话 A 临时改模型；全局 Profile 改模型和另一项，下一轮 A 保留临时模型但跟随另一项，会话 B 全部跟随。
- 切换失败保留输入和旧覆盖，不发送；成功切换清覆盖、无额外提示。重启恢复不能新建可见会话冒充。
- 断服务/卸载必要提供者、恢复服务：错误可恢复，无数据删除、无自动重发。
- 键盘操作全路径，浅/深主题与 200% 缩放，截图和浏览器控制台记录；仅 jsdom 不可报几何验收通过。

## 5. 完成口径

tasks 全部勾选附证据、G01–G20 可追踪、无假绿/隐性跳过、复用账和迁移账齐全。独立模块完成可提交检查点；有接缝缺口不冒充全包完成。报告区分未执行、受控通过、真实品牌通过。合并、push 和清理工作树另行批准。
