# 迁移接缝备料（只读，不是已批准实施）

当前技术候选V3，政策D3/D4/D5待答。正式实施计划须在模型修订与最终独立复查后给验收状态。

| 调用接缝 | 当前路径（M，除P另标） | 必须改变的行为 | 兼容限制 |
| --- | --- | --- | --- |
| 运行装配根 | `apps/server/src/ordessa_server/bootstrap/runtime.py:627,632,669,701` | 注入同一个Environment和transport扩展点；去独立激活权威 | 保留data-root ownership/token/auth墙；不把网络host当Core实例工厂第二权威 |
| 公共Core接缝 | `apps/server/src/ordessa_server/core_binding.py:99,180,217` | 由薄adapter转同环境激活/活动；retire只有同义务账判定 | 不复制DTO/平行busy账；历史旧submit/query错误码保持或版本明确 |
| 服务/HTTP/stream贡献 | `apps/server/src/ordessa_server/plugin_host/host.py:315,691,720,835,909` | 通用stage/commit/hold/drain移环境；方法/路由索引仅同一committed revision投影 | HTTP运行预挂载形状不能扩签名/auth；未来若动态routes需另版本，不靠移目录伪支持 |
| 原生通道 | `plugins/harness/src/ordessa_harness/server_acp/registry.py:234,290`，`runs.py:26,55` | open活动、channel Object、native session correlation分离；入口send/reply安全意图/结果 | 旧Session+Turn ledger只作兼容投影/只读历史，不能平行判新object终态 |
| 原生transport/protocol | `plugins/harness/src/ordessa_harness/server_acp/access_entry.py:61`、`plugin.py:154,323,353` | Surface声明/role/Scope覆盖证明；adapter保留native透传/approval | 不把ACP字段/brand/native commands放Core；UI-only gap别假报可达 |
| ACP admission | `apps/server/src/ordessa_server/acp_admission.py:305,327`、product:219 | 原生意图识别归Harness；共用中性policy port/current grant/response slot | 单一policy authority，不能Core另造审批流；错误/拒绝后也验owner |
| 旧sidecar执行 | `plugins/server-compat/src/ordessa_server_compat/execution/sidecar_backend.py:201,231` | Work业务关联保留，dispatch/cancel归环境；NeutralRunTracker只当投影/adapter缓存 | 历史exec/dispatch/server_turn字段不双主写；no runtime-compat反向re-export |
| 旧插件环境入口 | `packages/pacthold/src/pacthold/extensions/bootstrap.py:40,62,82` | loader/entrypoint解析复用，迁移为选定installed清单与环境贡献 | 当前“load all installed”不能当enable选择；旧接口暂留forwarder不再私建registry |
| 资源/配置 | `plugins/server-compat/src/ordessa_server_compat/plugin.py:155,225,339,348`；`plugins/profile/src/ordessa_profile/plugin.py:79,91,127` | Surface/resource projection声明、source ref和退出合同；资源独立不需Profile/Harness | 领域DB/journal保留为配置事实owner，环境只投递账；真实数据改需另裁定 |
| product selection | `products/server/src/ordessa_server_product/composition.py:146,173,219` | 单manifest选择启用；裸环境显式空清单；注入Store/fingerprint/policy按要求 | 来源/安装≠enable≠实例；无policy不默认full grant |
| P native历史 | P `plugins/harness/src/ordessa_harness/server_acp/history.py:13`、P `registry.py`未提交修改 | 作为native continuation事实/decoder，关联新Environment稳定身份 | 先钉P工作内容；不靠同nativeId/path接管原生旧对象 |
| 前端connector | P `plugins/connectors/acp/src/{channel,client,host,native}.ts`；M `plugins/connectors/ordessa` | 读取receipt/current、对象/usage、delivery控制/gap、normal-removal pending | 此轮只合同，未来UI改需另外范围；本地直接native connector不冒称后端环境已管理 |

必须再查的不是目录形状，而是每个真实执行请求只有一个主写者、所有可调用旧路由都能转入同一权威，还是有绕过/遗留业务链。默认产品含模型/权限/sandbox的源码装配不直接说明全产品closure完成。
