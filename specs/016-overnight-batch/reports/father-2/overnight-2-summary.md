# overnight-2 父会话总汇报(016 夜批 · 内容资源+可执行扩展线)

日期:2026-09-29 凌晨收官。父会话工作根=/home/maoqh/projects/ordessa/worktrees/
overnight-2;本汇报与阶段二产物均在本目录 reports/ 下。git 纪律:全程未执行任何
git 写操作(主仓与儿子树均只读),**四个儿子树的全部产出留在各自工作树未提交**,
待用户明早验收后自行提交;「绝不 merge/rebase/动其他分支」遵守。

## 全局裁定:qoder 失败,zcode 代打(四包同因)

- 两次封装运行(run-qoder.sh)退出 0 但 goal 自报 **blocked**:`-p` 非交互 +
  `--permission-mode default` 下写/执行被自动拒绝(会话严格只读)。
- 降级条款原样命令裸调探针:模型白名单名 `qwen-3.8-flash` 不可用(CLI 实名单
  `Qwen3.8-Flash`,自动回落),随后 **credit 额度耗尽**——任何任务无法执行。
- 旁证:overnight-1(PE1)、overnight-3(LSP)同款脚本同款只读受阻。
- 证据链:specs/016-overnight-batch/reports/logs/ 各日志 + 本目录
  qoder-unavailable-record.md。审阅全程按降级条款走 run-review 同口径裸调
  (pi + mimo-v2.6-pro,物理只读)。

## 各包一段(结果/测试计数/qoder 与审阅记录/卡点/复用与自建)

### 1. son-ext-extensions(EXT-1..7,新支 codex/plugin-extensions)

- **结果**:域完整交付——hook 定义模型(机制 D:强制批准+来源哈希+版本 pin)、
  三态批准链(未批准不装载/可诊断/可撤销)、注入面清单(HIGH 拒载)、八品牌
  三/四轴能力表(qwen 除名行、四家 phase2)、`assets.hooks` C2 注册(codex/claude
  两 adapter 经发布 point);**compile=类型化拒绝**(hooks_target 仅被 registry
  解析、运行时零消费 + 原生 hook 值 schema 在库不完整 → AR-3 预案「定义就绪、
  投影待通」,api-requests.md 已回填);意图构造半件(MountContent/SetField)
  为真且被测。
- **测试**:101 passed / 0 failed(9 个测试文件)。
- **qoder/审阅**:qoder 失败(见上);审阅 **18 轮**全部落实(批准链放行 HIGH、
  revive/restore 旁路、错误族 503 化、assess 身份闸与 target 供给门、blocking
  词表、claude comment-grade 改 unknown、digest 对账等),末轮确认无 fake green、
  写入面干净。
- **卡点**:投影 materialization 待 harness 侧 target 供给+钉版 schema 读
  (AR-3);未提交(见 git 纪律)。
- **复用/自建**:复用 harness-api 全套 DTO、注册通路、skills 形制;自建=机制 D
  批准链/注入面清单/品牌表(新域无既有物),占比约六成,理由在报告。

### 2. son-px-prompts(PX-0..7,支 codex/plugin-prompts)

- **结果**:R0 实测(原 149 项 G01–G08 已在树)+ 三品牌 prompts adapter 按
  「定义就绪、投影待通」交付(**AR-6**:registry 连 instruction target 声明
  都不存在——较 EXT 的 AR-3 更前置);三语义×八品牌能力表(三家逐格+四家
  unknown 预置+反例+qwen 除名);四家转阶段二;G01 白名单增两项(新子包)
  无删断言、敌例在;43 项账逐项处置落报告(账本文件不在写入面,勾选留所有者)。
- **测试**:186→**187 passed / 0 failed**(净增 38,含 citations spot-check 使
  证据链可证伪)。
- **qoder/审阅**:同上代打;审阅 **6 轮**全部落实(HM 路径 bug、白名单账实、
  反例纪律、计数口径、边界扫描覆盖证明、死代码)。
- **卡点**:AR-6(harness 侧 instruction target+路线核读);docs/design 矩阵
  并入属写入面外(接入请求已登记);command-templates 域不在本包范围。
- **复用/自建**:复用为主(发布词汇/通路/149 既有测试/pin 事实);自建=三
  adapter+能力表+payload schema,约四成。

### 3. son-cmp-skills(CMP-SK,q1 账本 23 项,支 codex/plugin-skills)

- **结果**:**纯甄别包,代码零改动**。甄别结论:写入面内账本各事项域内实现
  完备且有测试证据(T03–T14 域内半全部有指名测试文件),剩余未勾项全部是
  跨域/线级卡点(前端、产品装配、线级门、git 纪律)或上游断链;23 项三档
  逐项落表;八家覆盖缺口表列出(三家已实现、四家阶段二、qwen 除名)。
- **测试**:**427 passed / 0 failed / 6 errors**(433 collected;6 errors=
  profile-api 上游断链的收集期失败,测试自身如实命名缺口,写入面禁改 profile;
  known-issues.md 无该条目——提请有权限侧补登记)。
- **qoder/审阅**:同上代打;审阅 **3 轮**落实(git 证据表述、计数口径精确化
  433/427/6、T17 去自证、指针冻结 main@b6d2748134、6-error 排除性映射+
  原始输出冻结文件)。
- **卡点**:profile 断链(上游);真实装载格=unknown(brand-matrix 无一手
  证据,不冒称)。
- **复用/自建**:100% 复用,零自建(甄别结论=无缺口可补,不为凑数造码)。

### 4. son-cmp-subagents(CMP-SA,q3 账本 21 项,支 codex/plugin-subagents)

- **结果**:**纯甄别包,代码零改动**。21 项三档逐项落表;实测 862 passed
  (`--continue-on-collection-errors` 让唯一上游阻塞文件不掩盖其余 28 文件的
  真实绿,error 如实在案+冻结输出含命令行/错误原因/29-28 演进说明);T10
  (profile facet,29 测试)因 profile 独立仓不在本环境登记「已实现未验」,
  二手指针(q3 报告 671 passed)标注不作勾选依据;Pi L3 未完成按任务原文
  声明;品牌缺口表(三家、四家阶段二、qwen 除名)。
- **测试**:**862 passed / 0 failed / 1 collection error**。
- **qoder/审阅**:同上代打;审阅 **2 轮**落实(冻结件入 diff/二手指针/口径
  统一/冻结件补命令与原因)。
- **卡点**:profile 独立仓缺位(T10 复跑);真实链归 C0;Pi extension-backed
  L3 缺(任务原文要求明确未完成)。
- **复用/自建**:100% 复用,零自建。

## 阶段二(四儿子全部完成后执行)

- **四家设计×4 域**:phase2-design-{extensions,prompts,skills,subagents}.md
  ——每域把三态表里 hermes/opencode/dsh/kilo 的格子写成可派单方案包草案
  (T0 侦察→T1 registry target(四域统一:合并一个 harness 侧小包一次授权;
  subagents 另需 T0 显式产出「通道裁决」)→T2 adapter→T3 扩格→T4 测试),
  含统一落格口径 §5(unsupported 需一手证据/unknown 无据/supported 仅 L2)、
  门与 DoD、排序建议。
- **qoder 侦察**:recon-qoder.md——按盘点模式(配置入口/扩展面/通道/license/
  安全面)+信任阶梯逐条标注(L3 官方四页 2026-09-29 抓取+L5 本地一手:
  v1.1.62、-p+default 只读实测、模型白名单/额度、--acp/SDK 通道);**对接建议
  =ACP 通道+硬闸(模型面与 qwen 除名裁定冲突,须用户明示)**。
- **审阅**:阶段二产物审阅 **8 轮**(slot 现状两档实况、opencode 误引剔除、
  URL/日志逐一登记、证据闸门统一、撞名术语加注、T1 打包收口、同源注记),
  终态**通过**(附三条不阻塞措辞项已顺手清理)。产物与轮次原文均在本目录。

## 遗留与移交清单

1. 四树未提交(用户验收后自提交);2. AR-3/AR-6(harness 侧 target 供给+
   schema 核读);3. profile 断链与 known-issues 补登记(有权限侧);
4. 阶段二方案包待派单(harness registry 小包建议先行);5. qoder 对接的
   模型面硬闸待用户裁定。
