# PE1 · api-requests 回填(AR-1 消费面)

状态:2026-09-29 夜批。本文件是 `specs/016-overnight-batch/api-requests.md` AR-1 行的
permissions 侧回填;因包写入面仅 `plugins/permissions/**` 与 `reports/`,主台账的
合并归集成收口(明早验收时合入),内容以此文件为准。

## AR-1 permissions 半边:authority 查询面(core C4 admission 消费)

### 1. 提供端口(provided port)

- 端口名:`permissions.authority.query@1`(api 常量 `AUTHORITY_QUERY_PORT`;
  backend 常量 `AUTHORITY_PORT`,守卫测试钉死两处字面量不可漂移)。
- 载体:`PermissionsAuthority`(backend),经 `PermissionsBackendPlugin.build`
  的 `provided_ports` 注册——`server_plugin_api` Contribution 形态,core 无需改动
  即可经宿主端口表取用(PE1-3)。
- 进程内契约:`ordessa_permissions_api.PermissionsAuthorityQueryPort`(Protocol,
  五方法:`effective_for_operation` / `effective_for_session` /
  `effective_for_user` / `lookup` / `revoke`)。

### 2. wire 方法(只读)

- 方法 id:`permissions.authority.query`;required 参数:无;optional:
  `factRef` / `tool` / `target` / `sessionId` / `principal` / `operationDigest`。
- 响应闭形:`{ready: bool, records: AuthorityRecord[]}`;`factRef` 在场时
  records 为 0/1 条。`ready:false` = 存储不可读,诚实空表,绝不造记录。
- 该方法只报事实,不产生裁决;无任何 wire 路径能产出 `allow`。

### 3. DTO 冻结字段(AuthorityRecord,13 字段,闭集)

| 字段 | 类型 | 语义 / 空值语义 |
| --- | --- | --- |
| authorityId | str(必填) | `authority_<sha256_32>`:source+factRef 决定性派生,同一事实永不二次铸造 |
| source | enum(必填) | `approval_grant` \| `policy_rule`(读自哪个既有存储;无第三存储) |
| scope | enum(必填) | `session` \| `user` \| `profile`;存量 `project` 拼写由投影层映射为 `profile` |
| tool | str(必填) | 工具键,闭词表(TOOL_KEYS),未知键构造即拒 |
| target | str \| None | 规则/授权绑定的目标;None=该事实不指名目标(声明式缺位) |
| operationDigest | str \| None | 64 位小写十六进制;grant 专有;非 hex64 构造即拒 |
| requestedBy | str \| None | 操作请求人;存储未记录即 None(PE1 新增列,当前无写入路径,见 §5) |
| approvedBy | str \| None | 批准人(grant 的 decidedBy / 例外规则的 authorization.issuer);未记录即 None |
| grantedAt | ISO8601 aware \| None | grant 落定时刻;naive 时间戳构造即拒 |
| expiresAt | ISO8601 aware \| None | 时效;None=存储未记时效,**不是**"永久有效"(裁决路径每次重查) |
| state | enum(必填) | `active` \| `expired` \| `revoked` \| `consumed`(由存储事实派生,非裁决) |
| revision | int ≥1 \| None | grant 的 CAS version / 规则的 intent revision |
| factRef | str(必填) | 事实引用:审批 id,或规则 `intentId@revision#index`(lookup 的解析键) |

未知字段、缺必填字段、未知枚举拼写、naive 时间戳、非 hex 摘要:一律
`PERMISSION_AUTHORIZATION_INVALID` 拒绝(既有 schema code,wire family
`INVALID_REQUEST`,无新增 family——AR-1 失败反例对齐)。

### 4. 消费纪律(core 侧必须遵守)

1. 事实≠裁决:仅 `permissions.authorizer@1` 的 `AllowedOnce` 允许副作用;
   本面的任何记录(含 `active`)都不放行任何操作。
2. 缺席=诚实空:查询返回空元组/None 意为"无生效授权事实在案",
   **不得**读作默认放行(受控测试反例:test_absent_authorization_*)。
3. 列表只含 `active`;读"过期/被撤销"本身须经 `lookup`。

### 5. 已登记限制(api-request 语义)

- `principal`/`decided_by` 两列已加(server_approvals,加列可空,旧行零迁移),
  但本包无写入路径:decide 线签名被 api 端口测试逐成员钉死,扩张属面变更;
  principal 证据按 G5 归宿主/C0 决定链。**core 若需"谁批了"有值,需 C0 在
  decide/admission 链落笔**——这是本回填对集成方的显式请求。
- 规则事实永不回答 session 过滤查询(intent 无会话身份,不造);撤销无 wire
  入口(进程内 `revoke` 已备),产品若需 wire 撤销面另立请求。
- 行缺失 toolKey 的 legacy grant 不投影(无法回答任何操作查询,不造工具键)。
