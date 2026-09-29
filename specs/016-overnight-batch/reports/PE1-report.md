# PE1 · permissions-authority 报告(016 夜批)

**结果:七任务全做完,零真实模型,继承红如实带账。执行方式:qoder 失败、zcode 代打**(见 §2)。

## 1. 任务勾选对照(016 tasks.md PE1 节;不删行,勾选=本文有证据)

| 任务 | 态 | 证据 |
| --- | --- | --- |
| PE1-1 authority 记录模型 | ✅ | `api/src/ordessa_permissions_api/authority.py`:`AuthorityRecord`(13 字段冻结 DTO)、`AuthorityScope/SourceKind/StateKind`、决定性 `authority_id_for`;读既有 `server_approvals` 与 intent 规则,**无平行存储**(store 数不变:server_approvals 加 4 可空列) |
| PE1-2 查询面 | ✅ | 端口 `permissions.authority.query@1`(api `PermissionsAuthorityQueryPort` 五方法);backend `PermissionsAuthority` 实现;wire 只读方法 `permissions.authority.query`(required 空/optional 6 参数,响应闭形 `{ready,records}`);DTO 全字段冻结见 `reports/PE1-api-requests.md` §3 |
| PE1-3 接入贡献 | ✅ | `plugin.py` build:`provided_ports={..., AUTHORITY_PORT: authority}` + `ServerMethodDescriptor`(availability 挂真实可读性)——server_plugin_api Contribution 形态,零 core 改动;守卫测试 `test_the_authority_fact_port_is_provided_and_bound_to_the_api_literal` 钉 api/backend 字面量不漂移 |
| PE1-4 受控测试四态 | ✅ | `backend/tests/test_authority_query.py`:在场(`test_present_*`)/缺席(空元组+None,**断言绝不默认放行**)/过期(出列表,lookup 报 expired)/被撤销(出列表+consume 拒花);另有 consumed 态 |
| PE1-5 边界测试 | ✅ | 依赖方向门(auto-glob 覆盖新模块,backend 门含禁词文本扫描)全绿;两会话互不串扰 `test_two_sessions_never_see_each_others_authorization`;规则事实永不回答 session 查询(有专门断言) |
| PE1-6 report+api-requests 回填 | ✅ | 本文件 + `reports/PE1-api-requests.md`(DTO 13 字段全列+失败反例+对 core 的显式请求) |
| PE1-7 q5 账本甄别 | ✅ | §5 甄别表;sandbox 目录零写入,无需报回改动 |

## 2. qoder 调用记录(次数/退出码/失败处置)

| # | 时刻 | 命令 | 结果 | 处置 |
| --- | --- | --- | --- | --- |
| 1 | 09-28 23:24 | `run-qoder.sh worktrees/overnight-1/son-pe1-permissions …/PE1-permissions-authority.md`(5400s) | 父会话宿主中断连带杀死,无退出码行、工作树零改动(日志 `logs/son-pe1-permissions-qoder-20260928-232404.log`) | 非任务失败,原样重试 |
| 2 | 09-28 23:41 | 同上(5400s) | qoder 1.1.62 `--permission-mode default` 无人值守:Edit/Bash 连续三次权限拒绝后自宣告阻塞,仅产出 `api/.../authority.py` 一文件;**退出码 0 但任务未完成**(自述 "cannot claim any of 1–6 as passing";日志 `logs/son-pe1-permissions-qoder-20260928-234151.log`) | 失败原因确定性强(同命令必现同一权限墙),不做第三次无谓派工;按父文档失败路径**「qoder 失败、zcode 代打」**,自检后接管 |

代打说明:qoder 留下的 `authority.py` 经核对与既有词汇吻合,保留并修一处缺陷
(未知 source/state 枚举曾抛裸 `ValueError`,补 `AuthoritySourceKind.of` 并改为
typed `PolicyRefusal`);其余 6 个源/测试文件由 zcode 新写。

## 3. 测试证据(真跑,命令与计数)

环境:主仓 venv(`/home/maoqh/projects/ordessa/.venv`),PYTHONPATH 指向本工作树
src(不改动主仓 editable 安装)。改动前基线与改动后同法实跑:

```
cd plugins/permissions/api
  PYTHONPATH=<api>/src  python -m pytest tests -q
  → 基线 320 passed / 7 errors → 现在 329 passed / 7 errors(同 7 个继承 error)
cd plugins/permissions/backend
  PYTHONPATH=<api>/src:<backend>/src  python -m pytest tests -q
  → 基线 174 passed / 1 failed → 现在 191 passed / 1 failed(同一继承 fail)
cd plugins/permissions/adapters(未触碰,回归核对)
  → 131 passed / 1 failed(与基线一致)
```

新增/更新测试:api `test_authority_dto.py` 9 项、backend `test_authority_query.py`
16 项、`test_wire_plugin_registration.py` 5→6(扩充方法集钉+新增端口绑定钉,
未删任何断言)。

继承红(全部改动前即在,非本包造成,已与 q5/known-issues 口径一致登记):
- api 7 errors:`test_legacy_last_match_divergence` 等经 `plugins/server-compat`
  旧树导入,旧树 `from pacthold.storage import Database` 与 venv 中 pacthold
  2.0.0a1 不兼容——环境级继承红;
- backend 1 fail:`test_host_pre_effect_l2` 期望 `POLICY_SCOPE_UNVERIFIED` 实得
  `CAPABILITY_UNSUPPORTED`(L2 harness-owner 拒绝码漂移,基线即红);
- adapters 1 fail:`test_c4_fragment_identity_gap`(基线即红,本包未触碰 adapters)。

## 4. 三态逐格表(本包域)

| 格 | 态 | 依据 |
| --- | --- | --- |
| authority DTO/查询面(pi/codex/claude 无关的中立面) | 已实现已验 | 329/191 passed;四态矩阵+隔离+只读快照 |
| principal/decided_by 写入路径 | 未做(卡点:归宿主) | 列已备;decide 签名被端口测试逐成员钉死,扩张属面变更,principal 证据归 G5/C0 |
| wire 撤销面 | 未做(卡点:需求未立) | 进程内 `revoke` 已备;产品若需 wire 撤销另立请求 |
| grants-only 降级世界 | 已实现已验 | `policies=None` 时 grant 面照答、规则面诚实缺席(`test_a_grants_only_world_*`) |

## 5. PE1-7 · q5 safety 账本甄别(016 三档口径)

| q5 行 | 三档 | 处置/证据 |
| --- | --- | --- |
| T01 规则/上限/合成 | 已实现已验 | q5 原证:api 223 passed;`test_legacy_last_match_divergence` 先红后绿(该测试文件本体在本环境因 legacy 树环境问题 error,先红历史记录在案于 q5 tasks.md) |
| T02 ApprovalFacts 迁移+receipt | 已实现已验 | q5 原证:proof 16/16、双权威冲突测试;本包加列后 191 passed 回归 |
| T03 三品牌 assess/compile/verify | 已实现已验(编译面)/已实现未验(生效面) | 生效半受 G1/C0 pre-effect gate 阻塞——**卡点:core 依赖,不代做**;本包未触碰 adapters |
| T04 sandbox 原生 schema | 已实现已验(q5 原证 89+68 passed) | sandbox 目录本包零写入 |
| T05 sandbox adapter/探针 | 已实现已验(受控层) | q5 消费 harness-api 后更新行:adapters 94 passed;L2 写回读 blocked 项随 C3 绑定 DONE(受控层) |
| T06 Settings/Chat 区 + Profile glue | 已实现已验(区)/未做(glue) | glue blocked G4——**卡点:profile/foundation 不兼容,归集成** |
| T07 单一 ACP owner 接线 | 已实现已验(port+反例 29 条)/未做(宿主装配) | **卡点:core(C0)装配,permissions 侧已备 `AcpAdmissionPort`** |
| T08 旧存储迁移/compat | 未做(卡点:core) | 清单在 q5 `integration-request.md` §A/§B;单侧无可做 |
| T09 独立安装/红账/L2/L3 | 部分已实现已验 | 安装/依赖方向/红账零增量已验;受控 L2 三品牌中 harness-owner 面当前环境为继承红(见 §3);真实浏览器/L3 未做——卡点:E3 禁真实 + 环境 |

结论:q5 账本在 permissions 侧无"可由本包单侧补做而未做"的项;开口全部
core/环境卡点,如实带账。

## 6. 卡点清单

1. `principal`/`decided_by` 写入路径归宿主/C0 决定链(AR-1 显式请求,§PE1-api-requests §5)。
2. pre-effect gate 生产装配(G1)与旧存储迁移(T08)归 C0——PE1 不代做、不造假装配。
3. 继承红三项(api 7 errors / backend L2 1 fail / adapters C4 1 fail)基线即在,待白天裁。
4. wire 撤销面未立(进程内能力已备)。

## 7. 复用了什么 / 自建了什么(红线 7)

复用(机制零重造):既有 `server_approvals` 存储(加 4 可空列,零迁移)、
`PolicyRepository` intents 读取、`wire_family` 既有 code→family 表、
`server_plugin_api` 端口注册/方法描述符/`WireError`、describe 面的只读纪律模式
(availability+闭形响应+码-only 拒绝)、`_store` 事件写入器、backend 测试
`support.py` 全套真实存储设施、既有依赖方向门(auto-glob 无需改)。

自建:`api/authority.py`(DTO+端口契约,主体为 qoder 代打产出+zcode 修缺陷)、
`backend/authority.py`(查询实现+wire 投影,新写)、`facts.py` 的 revoke/行读取
(新写)、plugin 注册增量、两组新测试。自建占比超三成的理由:父文档指定的
qoder 失败代打路径;查询面在本包之前不存在,无现成机制可投影。

## 8. 审阅记录

- **封装审阅(`run-review.sh`)**:执行成功但判「空 diff,无事可审」(exit 0)——
  原因:本包为 qoder 失败后 zcode 代打,变更留在工作树**未提交**(父文档 git 纪律
  只允许父会话对儿子树做只读 git 操作,不得代为 commit),封装审阅审的是
  `main...HEAD` 已提交差异,故无可见内容。按「未审阅」记此原因。
- **同口径代审(pi + mimo-v2.6-pro,模型白名单遵守)**:封装脚本无法看到未提交
  工作树,故按父文档阶段二同款「把文件内容直接喂 run-review 所用模型口径」形式,
  以 `git diff` 工作树增量+新文件全文(78KB,截 180KB 内)直接喂入,指令与封装
  的 system prompt 逐字一致;留痕
  `主仓 specs/016-overnight-batch/reports/son-pe1-permissions-review-fallback-*.md`。
  **结论:有保留**(写入面未越界、无 fake green;三条具体问题)。
- 三条问题全部核实为真并当场修复,修复后全套测试复跑(backend 194 passed /
  1 继承红;api 329 passed / 7 继承 error,与 §3 一致):
  1. wire `query` 未实现"存储不可读→ready:false+空表"短路 → 已加
     availability 短路+异常保护(describe 同款),补测试
     `test_an_unreadable_store_answers_ready_false_with_no_half_read`;
  2. `revoke` 的 reason 端口可选/实现必填的契约漂移+None 强转 → 端口改为
     必填(reason: str),实现去掉 `or ""` 强转,补逐成员签名守卫测试
     `test_the_query_port_signatures_match_the_implementation_member_by_member`;
  3. `operationDigest` 过滤不作用于规则面 → digest 窄化查询现只由 grant 回答
     (规则无 digest,排除而非滥答),补测试
     `test_a_digest_narrowed_query_is_answered_by_grants_only`;
  4. 附带:撤销不可变性原为同义反复断言,改为真断言(首次撤销的 reason/时间戳
     不被二次撤销覆盖)。
