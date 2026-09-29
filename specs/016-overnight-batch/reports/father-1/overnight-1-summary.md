# overnight-1 夜批汇报(PE1 → PE2 → MPX + 阶段二)

会话:`worktrees/overnight-1`(父编排,非 git 仓库)。执行窗口:2026-09-28
23:24 – 09-29 03:0x。纪律执行情况先行一句:**封装调用全部走
`run-qoder.sh`/`run-review.sh`,裸调仅发生在封装自身无法运行的降级场景并逐一
留痕;模型白名单(qoder 线 qwen-3.8-flash 未动用——三包均未走到裸调 qoder;
审阅线只用了 mimo-v2.6-pro);儿子树内父会话零 git 写操作(PE1/MPX 代打产出
以未提交工作树交付,PE2 提交由 qoder 完成)**。

## 一、PE1 permissions-authority(son-pe1-permissions,支 codex/plugin-permissions)

- **结果:七任务全做完。qoder 失败、zcode 代打。**authority 事实模型+查询面
  (`permissions.authority.query@1` 端口+只读 wire 方法)、四态受控测试、边界门、
  q5 账本甄别全部落地;无平行存储(server_approvals 加 4 可空列)。
- **qoder 记录**:2 次派工。#1(23:24)被会话宿主中断连带杀死(无退出码、零产
  出)→原样重试;#2(23:41)qoder 1.1.62 在 `--permission-mode default` 无人值
  守下 Edit/Bash 连续三次权限拒绝后自宣告阻塞,仅落盘 authority.py 一文件,
  **退出码 0 但任务未完成**——失败确定性强,按父文档失败路径代打。
- **测试**:api 320→329 passed(7 errors 为继承:legacy server-compat 树与
  pacthold 2.0.0a1 不兼容);backend 174→194 passed(1 fail 继承:L2
  harness-owner 拒绝码漂移);adapters 未触碰 131 passed/1 fail(继承)。
- **审阅**:封装判「空 diff」(代打未提交,父会话禁 git 写不能提交)→按同模型
  同指令口径直喂工作树 diff(78KB);**结论:有保留**,三条发现(ready:false
  短路未实现/revoke 契约漂移+None 强转/digest 过滤不作用于规则面)**全部属实
  全部当场修复**,另把一处同义反复断言改真断言;修复后复跑全绿。留痕
  `son-pe1-permissions-review-fallback-20260929-004301.md`。
- **卡点**:principal/decided_by 写入归宿主 C0(AR-1 显式请求);pre-effect
  gate 生产装配归 C0(G1);继承红三项待白天裁。
- **复用/自建**:复用既有审批存储/intent 存储/wire_family/端口注册形制/describe
  只读纪律/测试设施;自建查询面(此前不存在)+qoder 代打产出的 DTO 修缺陷。

## 二、PE2 harness-native-evidence(son-pe2-harness,支 codex/plugin-harness)

- **结果:qoder 一次成功**(00:50 派工,01:52 退出码 0,62 分钟,4/100 turns)。
  两笔提交:`63b3aaa84d`(C4 读侧 evidence 五型 DTO+NativeEvidenceService 三态
  判定+qwen 除名)、`f81218c51f`(报告+c0 24 项甄别 A8/B11/C5)。复用既有
  journal native_evidence/native_verifications 表,零新表零新协议;qwen 摘除
  (8→7 段)带 `RETIRED_NPM_ROOTS` 显式记账,不删数据。
- **测试(qoder 报告声明,父会话逐字复跑核实)**:全量 `2 failed, 445 passed,
  3 skipped`(2 红=known-issues 登记的 pi sdk drift 继承红);隔离 15 passed;
  JS launch_descriptors 3 pass/0 fail。下游 server 侧 2 个 qwen 红实测在案转
  core(KeyError 'qwen'/期望列表含 qwen)。
- **审阅**:封装 exit 126(分支全量 diff 146KB 超 argv 单参数上限)→降级裸调,
  改审夜批增量(102KB 未截断);**结论:有保留**,三条:①qwen 测试文件退役而
  生产模块留存=覆盖空洞(待裁项,保守保留等用户裁);②readback 独立性判定
  仅凭 evidence_ref 不等(属 C4 协议边界,转 core);③下游红未入 known-issues
  (docs/ 越面,已移交)。**无 fake green**。结论已抄回 PE2-report §5(未提交
  修改,见树)。
- **卡点**:C-PE2-1..4 见 PE2-report §6(known-issues 两条应登记项、下游 qwen
  同步 11 文件清单、真模型审阅、干净安装门)。

## 三、MPX model-provider-params(son-mpx-model-provider,支 codex/plugin-model-provider)

- **结果:四类请求级参数键投影面落地。qoder 失败、zcode 代打。**两格真投影
  (codex `model_reasoning_effort` 词表钉 remote.py;pi `maxTokens` 黄金对象
  重写)、pi retry 声明+宿主签发闸门(`pi.settings.json`,未签发即类型化拒绝)、
  其余格诚实拒绝各带钉源理由;零新包/零新 facet;requestParams 闭形载荷;
  runtime-preferences 目录零触碰。
- **qoder 记录**:1 次派工(02:04),退出码 0 但自宣告 BLOCKED(无人值守下一切
  变更动作被权限模式自动拒绝),零产出落盘——与 PE1 #2 同因,不再空耗第二次,
  代打。
- **测试**:adapters 48→66 passed(新增 18 项);server 128 passed(回归,未触
  碰);profile-contribution/chat/desktop/contracts 未在本环境复跑(缺
  ordessa_profile/node_modules——既有环境缺口,z3 基线数字在案,本包零触碰)。
- **审阅**:封装 exit 126(同 argv 上限)→降级直喂工作树增量(40KB);**结论:
  有保留**,三条:①pi 预算重写会吞同批端点变更(真缺陷,**已修**:choice 自身
  baseUrl/api 叠加在样例上,补回归测试);②非法 requestParams 裸 ValueError+
  schema/DTO 口径不一(**已修**:assess→unknown/compile→INVALID_FRAGMENT 类型
  化,schema required 对齐);③pi.settings.json 声明扩大写入面(设计裁定保留:
  唯一 first-hand 目标,声明 inert+未签发拒绝即最诚实通路,理由在案)。另修
  死 assert 与夸大 docstring。修复后复跑全绿。留痕
  `son-mpx-model-provider-review-fallback-*.md`。
- **卡点**:timeout 族归 harness 域裁定;pi settings target 需宿主签发(AR-6);
  z3 REQ-Z3-1/2 生产缝归 C0。
- **复用/自建**:复用既有 facet/三品牌 adapter 骨架/C2 契约/conformance 门;
  自建 RequestParams DTO+两格投影+闸门+18 测试(超三成理由:父文档指定代打路
  径,参数面此前不存在)。

## 四、阶段二(全部儿子完成后;只写文档)

1. **三域四家设计**:`reports/phase2-design-permissions.md` /
   `phase2-design-harness.md` / `phase2-design-model-provider.md`——hermes/
   opencode/dsh/kilo 逐家原生面(L2/L3 引用+行号)、投影设计、待钉源清单、
   派单草案(P2-PE1-A/B/C、P2-PE2-A/B/C、P2-MPX-A/B/C)与证据门。要点:
   opencode/kilo 权限规则同构候选直投影;dsh 整行替换语义(禁深合并);
   hermes permissions 域 honest unsupported;harness 域四家 receipt 需先裁
   operation 签发点,launch_provenance 通道可预埋;model-provider 域
   opencode/kilo 同构对先行、dsh 连接级 retry 不与请求级双收。
2. **mcode 侦察**:`reports/recon-mcode-20260929.md`——mcode=MiniMax Code CLI
   (MiniMax-AI/minimax-code,MIT,main `68284bb101bb`,tag v0.5.8
   `e3d78551c241`);ACP 一等入口(`mcode acp`)+Pi 底座;provider add/
   config.yaml/AGENTS.md/hooks(Claude 格)等 L3@commit 走查;建议 pin v0.5.8;
   六项下一轮侦察清单。
3. **阶段二审阅**:四份文档合并直喂 mimo-v2.6-pro(第一次输出异常作废,第二
   次有效),**结论:有保留**,三条全部采纳修订:①侦察文档证据级通胀
   (README/docs 属 L3@commit 非 L2,已加口径声明并降级);②model-provider
   hermes"同键位/同构"预判先于证据(已改"候选形状,待逐家核对");③
   P2-PE2-A"零依赖"不实(已改:三品牌格补齐+四家通道预埋,真投影以品牌接入
   裁定为前提)。留痕 `phase2-overnight-1-review-fallback-*.md`(前一无效文件
   亦保留,如实)。

## 五、横切事项与移交(白天处理)

1. **qoder 权限墙(环境级)**:`--permission-mode default` 在无人值守下对
   Write/Edit/Bash 自动拒绝,三包两败(qoder 1.1.62)。夜批封装如需 qoder 可用,
   白天需裁:换 permission 模式/预签发写入面/或继续 zcode 代打路径。
2. **known-issues 应登记**:①`access_launch_route.test.mjs` G05 继承红
   (PE2 E7–E9 主树复现证据);②qwen 运行数据目录孤儿态疑点;③api 7 errors
   (server-compat×pacthold 不兼容);④backend L2 拒绝码漂移;⑤adapters C4
   fragment 红(③④⑤基线即在)。
3. **代打产出的提交**:PE1/MPX 变更与两份 report 以**未提交工作树**交付(父会
   话 git 写禁令),明早验收后由用户/集成侧提交;PE2 已由 qoder 提交两笔。
4. **下游 qwen 同步**(PE2 §10):server 侧 2 红逐文件清单转 core。
5. 并行线注记:overnight-2 父会话(EXT/LSP 线)同时在跑,本会话未触碰其树。

## 六、诚实声明

- 本报告所有测试计数均为真实命令输出,继承红与首 rouge 红逐项列明,无删除断
  言、无 skip 掩盖、无"未跑称跑"。qoder 两次失败的日志分别在
  `logs/son-pe1-permissions-qoder-20260928-234151.log` 与
  `logs/son-mpx-model-provider-qoder-20260929-020444.log`,可复核。
- 审阅是附加证据不是验收;三个"有保留"的完整原文都在留痕文件里,未摘要美化。
