# 017 · tasks

## W-1 写入链死亡（派单波次一）

- [ ] SC-0 全量分类账：19 模块 × {死亡/毕业/迁移} 逐格定案表（对照 plan 映射
      提案+用户裁定），先落 report 再动代码。
- [ ] SC-1 `model_configs` writer 退役（按 W1-W15 逐行执行；行号漂移以现行树
      复测后记录）。
- [ ] SC-2 `server_profiles` writer 退役（R10；与 R 系 harness 侧退役的波次
      协调，不在本树改 harness）。
- [ ] SC-3 退役后门检：两 writer 的兼容回归测试退役（断言删除逐条留名，不整批
      跳过）；apps/server 侧断言更新清单交 AR-1。
- [ ] SC-4 W-1 report：执行证据+行号漂移记录+无双写窗口声明。

## W-2 组装与冻结面迁移（波次二，core seam 密集）

- [ ] SC-5 冻结清单+wire_validators 迁 apps/server/wire（AR-2：core 侧接收，
      本侧只删不代写）。
- [ ] SC-6 composition（native/sidecar 组装）按裁定归宿迁移（AR-3；含
      products/server 两处 import 切换=AR-4）。
- [ ] SC-7 `ServerCompatPlugin` boot 线摘除（AR-4 同批；products/server
      pyproject 依赖行删除时点与装配切换同批，不留悬空依赖）。

## W-3 业务域毕业（波次三，逐域一_wave）

- [ ] SC-8 approvals → permissions 域毕业波。
- [ ] SC-9 sessions 对界 plugins/agent/sessions 后的毕业/并入波。
- [ ] SC-10 execution/usage_aggregate → work_core 账目面波。
- [ ] SC-11 accounts/assets/http/persistence/facade 等按总方向裁定逐域波。
- [ ] SC-12 92 个消费测试逐一定向（跟域走/退役/重写），清单落 report。

## 收尾

- [ ] SC-13 目录删除：`plugins/server-compat/**` 清空；边界测试更新；
      known-issues 逐域登记；closeout.md。

（每波独立派单、独立验收；本 tasks 为总纲账，波内细化各自派单时补行。）
