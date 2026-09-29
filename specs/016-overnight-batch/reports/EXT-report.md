# EXT-report · extensions(可执行扩展全域)016 夜批交付

状态:**REVIEW_READY(zcode 代打)**。分支 `codex/plugin-extensions`,基线 main
(`5a22ffc587`)。执行记录:run-qoder.sh 首跑被会话中断外部杀死;原样重试退出 0 但
goal 自报 blocked(`-p`+`--permission-mode default` 下写与执行被自动拒绝);降级条款
原样命令裸调探针证实模型名 `qwen-3.8-flash` 不可用(自动回落)+ 账户 credit 耗尽。
三重证据详见父会话 `worktrees/overnight-2/reports/qoder-unavailable-record.md` 与
logs/ 下三份日志。按 spec.md 红线 5 标注:**qoder 失败、zcode 代打**。

## 逐任务账

- [x] **EXT-1 域骨架**:`plugins/assets/extensions/`(pyproject `ordessa-extensions`
      1.0.0a1;依赖仅 server-plugin-api + ordessa-harness-api,零 pacthold——域未用
      即不虚报)。`ExtensionsServerPlugin`(id `ordessa.extensions`,requires=())
      提供 `extensions.service` 端口与 `extensions.approvals.*` 两方法;facet
      `assets.hooks` 的 C2 注册=经 `harness.configuration-adapters`(v1,多属主)
      贡献 codex/claude 两个 ConfigurationAdapter,字符串常量在测试中钉对
      `ordessa_harness.contributions`(包内不 import harness——AGENTS 规则 3,
      test_dependency_direction 断言)。product 装配归 C0(api-requests 记录)。
- [x] **EXT-2 hook 定义模型**:`definitions.py` — hook_id/event/matcher/
      command-argv-元组|handler_ref/timeout(1..600s)/run_async 全冻结校验;机制 D
      红线字段 pin(X.Y.Z)+ content_sha256(sha256:64hex)为构造必填;事件词表
      **只收在库有证者**:SessionStart(codex/hooks.py:16 一手 + harnesses.toml:38-40)、
      PreToolUse(toml:117-119)、SubagentStop(toml:38-40 注记)——Claude 官网全事件表
      属 vendor-doc,一律拒绝(EVENT_UNEVIDENCED),扩表须附 repo 引用。
- [x] **EXT-3 批准与安全**:approval.py 三态总状态机(unapproved/approved/revoked,
      无默认放行态;指纹+pin 双匹配才叫 matches;revoke 幂等、revive 显式;
      snapshot/restore 留宿主持久化);security.py 注入面清单——HIGH(分号/管道/
      反引号/重定向/`$(` 命令替换/解释器打头/换行)一律拒载(批准也不能洗白),
      MEDIUM($VAR/~ 展开、glob 尾)可载但须入批准记录的 findings_digest;loader.py
      单一闸门:**未批准定义=不装载**(NOT_APPROVED/SHELL_INJECTION_SURFACE,
      类型化拒绝逐条计数);批准状态可诊断(approvals.list/records())、可撤销
      (approvals.revoke/revoke())。
- [x] **EXT-4 逐品牌投影表**:capabilities.py 单一品牌表,8 家×4 轴全带 file:line
      证据(构造期强制,无证 supported 直接 ValueError)。native_slot:codex/claude
      =supported(toml hooks slot 注记+source-index.json 键抽取);pi/hermes/
      opencode/dsh/kilo=unsupported(各自 toml slots 行);**qwen 行=除名注记**
      (用户裁定 2026-09-28,spec.md 品牌优先级 2;harness 侧摘除归 PE2-8,本包不动)。
      projection_path 全表 unsupported(见 EXT-5)。blocking_semantics 全表
      unsupported(EXT-6)。实施处置与能力格分离:codex/claude=implement;
      pi=ar-registered;hermes/opencode/dsh/kilo=phase2-design(阶段二设计,
      今晚不实施);qwen=removed-by-ruling。
- [x] **EXT-5 投影执行**:adapters/contribution.py — descriptor/assess/verify 全量
      实现(version gate:未探测=unknown,错版=unsupported fail-closed;verify 只认
      placement 事实、model_claim 与 load 事件一律 unknown)。**compile=类型化拒绝**
      ——两道一手证据门:①运行时无 hooks target 供给(registry/schema.py:90-104 解析
      后零消费,AR-3 实测);②原生 hook 条目值 schema 在库不完整(source-index.json:
      196-203 codex 仅键族、:552 claude 仅裸键)——猜 schema 写品牌配置=造假,拒绝。
      意图构造半件为真且被测:build_codex_intents(MountContent 整文件只读挂载)/
      build_claude_intents(SetField("hooks") 键替换)按 server 签发 target 构造
      发布 DTO,通即可抬闸。**AR-3 已按预案登记报回**(api-requests.md),不越界改
      harness。
- [x] **EXT-6 阻断语义如实**:blocking.py — projection 词表只容
      `semantics="observational"`(payload schema enum 层即拒 blocking 声明);
      Codex hook 失败不阻断反例(classification.md:52)进常量与测试断言;能力表
      blocking_semantics 全 unsupported;verify 的 Match 证据串明写
      "blocking/enforcement is NOT claimed"。
- [x] **EXT-7 本报告** + 审阅节(下)。

## 测试证据(实跑)

命令:`python -m pytest plugins/assets/extensions -q`(仓库根,venv 按
docs/baseline.md;cwd 上 son 工作树根)。**101 passed, 0 failed / 0 skipped**(2026-09-29 01:5x 收官实跑,含 18 轮审阅
修复新增用例;收集无同名遮蔽)。分件:definitions 10、security 11、approval 10、
loader 8、brand_table 8、adapters_conformance 22、blocking 6、error_families 5、
plugin_registration 7、dependency_direction 3。

## 写入面自检

`git -C <son> status --short` = `?? plugins/assets/extensions/` +
`M specs/016-overnight-batch/api-requests.md`(AR-3 回填,AR 通道即为此设)+
本报告与审阅轮次文件(specs/016-overnight-batch/reports/)。零越界。**未提交**:父会话 git 纪律=只读 git 命令,提交动作按 father.md 归
qoder 侧;qoder 不可用时代打不代提交,留树内待用户验收。

## 复用与自建清单(红线 7)

复用:published `ordessa_harness_api` 全套 DTO(ConfigurationAdapter/Intent/
ValueSchema/Verification 词汇)、`harness.configuration-adapters` 注册通路(AR-2,
与 skills 同点)、skills 的能力表形制(证据强制的三档格)、wire.error-families seam、
conftest 路径钉形制。自建:hook 定义模型/批准链/注入面清单/品牌表数据(本域事实
与机制,skills 等域无现成物)。自建占比约六成——原因:可执行扩展域为本批新域,
机制 D 批准链与注入面清单无既有实现可投影;凡有发布词汇处(注册、意图、核验)
一律走既有面,未造第二套协议。

## 审阅

run-review.sh 返回「空 diff」——代打工作未提交(父会话 git 只读纪律),`main...HEAD`
为空;按降级条款用同口径裸调 pi+mimo-v2.6-pro 审阅工作树伪 diff(25 文件,超 128KB
命令行上限截至 120KB,尾部测试文件个别轮次不可见,全量测试本地实跑补证)。
**共 18 轮,每轮意见逐条落实**:首轮「有保留」三项(批准链放行 HIGH 注入面/错误族
未知码谎报 400/stale-pin 测试未测 pin)→修复;二轮 revive 旁路+补测→修复;三轮
restore 未设防第三门+verify 缺 digest 判 Match+弱断言→修复;四轮 open_points 空声明
+glob 中段漏判→修复;五轮 assess 身份闸+restore 形状+expected 覆盖→修复;六轮
Match 证据来源/restore 声称对齐/claude comment-grade 改判 unknown→修复;七轮宿主
行为声明收敛+转移记录声明对齐+restore 非字典行→修复;八轮 open_points 条件化+
glob→修复;九轮 codex 目标筛选对称+assess payload 错误不作能力声称→修复;十轮
supported 需 server 签发 target+approve 文档对齐+引号括号入清单/反斜杠降 MEDIUM→
修复;十一轮 allowed_fields 空通配收紧+restore 拒 unapproved→修复;十二轮 assess 与
compile 恒拒对齐(schema 未证即 unknown)+adapter_version 契约说明+笔误→修复;十三轮
interpreter 分级细化(eval 旗标 HIGH、裸解释器+脚本 MEDIUM)+pacthold 文档失实→修复;
十四轮 wrapper/版本号绕过+同名测试静默欠收集+dev extra→修复;十五轮 eval flag 任意
后续位置/等号附着+dev extra 回撤循 skills 先例+native_file_stat 覆盖→修复;十六轮
loader 拒 handler 路由+粘载荷绕过+反例补齐→修复;十七轮 HANDLER_ROUTE_UNAVAILABLE
入族表+matches() 纳入 findings_digest 对账→修复;十八轮(收官)测试力度
(monkeypatch 证 matches 对账现值)+loader 未类型化崩溃路径(DEFINITION_INVALID)+
capability 行 evidence_ref 硬编码→修复。
**终态:100% 审阅意见落实,101 passed/0 failed,收集无同名遮蔽;末轮(18)两项收敛后
未再起轮,残留风险=无新增实质问题可修,审阅反复确认「无 fake green、写入面未越界」。**
全部轮次原文:本目录 EXT-review-*.md(fallback 20260929 + round3/4/5/6/7/8 +
final2..final11)。
两项设计边界裁定(审阅方提请任务侧确认,现记录于此):①verify 的 Match 信任边界=
发布观察词汇既定形状(与 skills 同形;adapter 无法独立复采样本,docstring 已声明,
改动属协议级超出本包);②compile 恒拒=AR-3 预案授权交付(api-requests.md「定义就绪、
投影待通」),非降级逃避。
