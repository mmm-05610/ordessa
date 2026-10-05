# 三 Skill / 显式 bundle 安装使用回执

2026-10-05；前置 `88375b109d`。本轮接纳既有成果，主会话独占源码/测试/Git/账本；已有代理 completed，另开一个只读指令演练代理，无共享写者。采用 `/home/maoqh/.codex/skills/.system/skill-creator/SKILL.md` 的现有 Skill 更新、结构验证与独立指令演练规则；不将 Skill 安装到全局 Agent 配置。

## 修改

- configure-agent-profile：保留 catalog 与运行实例分离；补公开 Provider 发现并明确不能由此验证所有 leaf；移除 nodes=false 对已宣告纯读的错误总闸。
- manage-external-agent：给出现有 Node list/inspect 和 configuration describe/inspect/apply/query 精确语法、完整引用、owner 版本、默认 policy、逐项 partial/unknown 与原 operation 核实；明确 query 可记录证据，缺 operationRef 没有公开 request-key 查找，不以独立 model=new 观测证明丢回执操作完成。
- use-external-agent：同步已有只读/配置面；prepare/task/result/lifecycle 未实现仍拒，不把本地 Pi 路径当远程 admission 或模型授权。
- capabilities：独立报告匹配合同/逐项支持，不再依赖 Profile 写入 fingerprint；doctor 和 Profile 原保障检查保持。该问题由独立演练发现，真实 Core 设置 fingerprint=None 的反例先红后修，非修改 HTTP payload 假造能力。
- ACCEPTANCE/README：去除“当前仅Profile”“当前固定240测”等过期描述，区分受控配置/发布观察、真实隔离Server权限负例、未验证生产Harness/任务。
- 安装 exercise：必须显式选 --bundle/--evidence，不自动用旧 alpha bundle，也不覆盖旧记录；复用 bundle checksum/required assets/wheel gate。实际 v1 Node方法缺席4取代缺参数2冒认命令未实现的旧检查。保持已有catalog/CAS/授权/恢复后历史读断言。
- wheel gate：禁止 client namespace 外任何 Python 实现，覆盖三家独立包改名后只导入stdlib也可能夹入CLI轮包的漏洞；不新增品牌白名单或运行时依赖。

## 指令演练

独立代理仅读三Skill与真实parser，按三个原始请求作命令/停止条件推演，没有CLI/服务/模型/测试/Git或写入：

1. 已有NodeRef、read/inspect方法已宣告、nodes/configurationManagement=false、读取权限未观察：用对应公开读观察权限，不误以全局写标志挡读；actual model只指owner快照，非真实推理验收。
2. apply失联仅requestId，无operationRef，独立inspect=model=new：不发apply、不换键、不读DB；不能由值相同推导原操作或整批 applied。
3. 本地Pi存在，managedInput=false，未许模型/安装/daemon：拒任务入口，不擅转native通道或补模型授权。

发现 capabilities 的 Profile 保障总闸后已补实际回归；这只是说明解释验证，不是外部Agent完成任务或M验收。

## 真实命令与结果

`<PY>` 为 `/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python`，所有测试主会话串行，句柄终态。

1. `<PY> /home/maoqh/.codex/skills/.system/skill-creator/scripts/quick_validate.py products/agent-tools/skills/NAME`，NAME依次configure-agent-profile/manage-external-agent/use-external-agent：三次exit0，仅结构门。
2. `<PY> -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_nodes_cli.py -k fingerprint -q --tb=short`：修改前2P/1F、25 deselected、exit1、0.74s；capabilities错误拒4，doctor拒4和Node读0已有正确行为。修单一条件后 Node/discovery/bundle组合55P/0F exit0、23.02s。
3. `<PY> -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_bundle.py -k independent_provider -q --tb=short`：旧gate0P/3F、7 deselected、exit1、0.05s，三独立包stdlib代码未被拒。补client-only Python门后完整下列组合最终58P/0F exit0、23.04s：

   `<PY> -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_nodes_cli.py products/agent-tools/tests/test_discovery.py products/agent-tools/tests/test_bundle.py -q --tb=short`

   新3多域capability反例＋3轮包反例，共6项；55/58是快照，不累加。没有skip/删断言/恢复compat。
4. `PIP_NO_INDEX=1 <PY> products/agent-tools/packaging/build_bundle.py --output products/agent-tools/dist/bundle-0.1.0a2-node-skills-88375b`：exit0，工具0.94s；新bundle，未覆盖旧资产。没有第三方安装/下载。后续加强gate也对这个实际bundle调用verify_checksums/verify_wheel再exit0，文件未改变。
5. `PIP_NO_INDEX=1 <PY> products/agent-tools/acceptance/install_use.py --bundle products/agent-tools/dist/bundle-0.1.0a2-node-skills-88375b --evidence docs/implementation/agent-tools/evidence/install-use-node-skills-88375b.json`：exit0、27条实际命令/stop记录、M0、runtime_cleaned=true。每条argv/退出码/安全输出见JSON。实际fresh venv安装无backend依赖，init不执行Harness候选，CLI actual catalog/CAS/replay/ref历史/鉴权/离线/自有Server重启；Profile引用故意absent，preview4，v1Node观察未宣告4、任务CLI未实现2正确保留。没有生产Node/config正向或native任务；前轮配置fresh测试另有回执，不混成本轮。

   wheel SHA256=`19b8359bbaedfdf6f784e8b3f8232c6077922845870442fdd5cd76831f9fea1e`。bundle位于ignored dist，不提交二进制。主会话读JSON并检查其create-fresh-client-venv所属临时workspace已不存在：client/Server/本地Skill复制均已移除。
6. 再用同上安装命令与同一个已存在证据路径，主会话subprocess反例：工具exit1，正回执SHA不变，失败回执仅ValueError/records=[]，没有安装/服务命令。包装验证脚本exit0表示该拒绝被验证，不把工具exit1藏成成功。新 `install-use-node-skills-88375b-failed.json` 是预期no-overwrite负例。

五工单strict及diff-check exit0只结构/格式。这里没有Core/Server/Harness源码改变，没重复全Core或三家回归；历史Core269P/3F保留本轮前一已验记录，生产缺资源仍ABSENT。Server进程回执不是nativeHarnessP；三Skill只是被打包/复制和只读解释演练，非M使用。总体AU002–005 PARTIAL；真实owner/权限/材料/冷恢复/lifecycle、旧model/Server迁移、prepare/tasks/results/全纵向验收继续。无用户数据/凭据/全局配置/登录/用户服务/第三方更新安装/模型/push/主树合并；成本unknown。

终审另建议保留实际supports而非硬写false；README/use Skill/ACCEPTANCE已改为当前optional部署false、其他兼容服务按实际报告，但当前CLI无task命令仍明确停止。helper wheel选择收窄为唯一ordessa_agent_tools-*.whl，和distribution门一致，不会选入其他wheel。源CLI/packaging门没有再改；Skill末端quick_validate exit0。

上述文字/选择修正后新建（不覆盖）最终bundle：`PIP_NO_INDEX=1 <PY> products/agent-tools/packaging/build_bundle.py --output products/agent-tools/dist/bundle-0.1.0a2-node-skills-final-88375b`，exit0。完整安装命令同第5条但选此新bundle与 `docs/implementation/agent-tools/evidence/install-use-node-skills-final-88375b.json`，最终exit0/27命令/M0/runtimecleaned。新wheel SHA256=`6a8c08b9c9a6ed174b162f7d22a2792d4040051e45530e65492ec27a931dcc9e`；主会话末端读取真实JSON、核27记录与已删除workspace、三Skill字节等同当前source、verify_checksums/verify_wheel均exit0。新旧27是两次快照，不报54项测试。旧正/负回执与旧bundle保留，不冒充终审后的资产；最终bundle同样ignored不入Git。
