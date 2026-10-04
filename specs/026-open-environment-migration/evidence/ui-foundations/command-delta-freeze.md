# UI01 命令增量接口冻结

接收源码 HEAD：5df67c464662d84969e99dfb5829bd6c608b7d9b，工作树干净；013受控恢复检查点后，UI-T01进行中。本子接口冻结不代表整项UI-T01完成。原公开合同文本、Token身份、业务动作与原断言保留。

## 单一执行归属

宿主现有C07 CommandSource是唯一生产注册/执行owner。旧CommandsToken保留；其生产提供者改为对同一CommandSource的薄适配：forScope.add登记原execute处理器到C07，getSnapshot只投影id/title，subscribe转发，execute映射Accepted/Refused/Unknown到原CommandResult。不建立另一命令Map、镜像执行注册表、全局业务store。旧createCommands直接工厂保留历史独立fixture，不用作默认产品第二owner。异步返回值原样保留；业务异常由原C07捕获。

## 生命周期与目标捕获

同id活贡献重复注册拒绝，关闭scope拒绝；registration由原scope拥有，dispose只撤销对应record，旧句柄不得撤销新record。公开CommandSource兼容增加可选capture(id)，返回原贡献代次的CapturedCommand（commandId、execute(args?)）；capture缺席/旧贡献失效返回Refused command-absent或command-stale，不按同id寻找新贡献。原execute仍供即时按钮/快捷键使用，菜单等延后执行必须在打开时capture。执行再次读取既有when/hostReady投影；when只呈现可用性，领域handler仍重核原目标和授权，公共层不制造权限事实。命令参数仅瞬时传递，不布局持久化。

## 分工与验证

root独占C07类型、host实现、产品接线、Git、证据与串行测试；叶适配可独立新文件，接口冻结后才准写入。反例：重复id、scope退出、卸载/重装旧句柄、捕获后同id重装、打开后可用性撤销。测试新文件；不改既有断言或skip。菜单/快捷键GUI和UI-A02/10完整场景仍待跑，不以机制单测替代。
