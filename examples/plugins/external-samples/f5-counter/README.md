# F5 fixture sample — counter（样例#4，T008-13/20）

## Owner
`f5-counter`：一个 CounterOwner（唯一写面）+ 两个独立消费者（count/label 选择订阅）。
零 Agent/Profile/Chat/Harness 依赖；非 React。

## 公开能力
F5 状态机制（`@ordessa/ui-components/state`）：identity-stable 快照、深层不可变、批量单次
完整快照、selector 相等抑制通知、scope 释放幂等。

## 缺席行为
无宿主适配、无持久化、无 UI：这是机制 fixture，不是产品功能。

## 生命周期
`node --test tests/test.mjs`（构建期经 esbuild 从仓源编译平台状态库=受控 fixture 接线；
声明的运行时依赖只有公共平台包 `@ordessa/ui-components`）。

反例钉住：消费者无写入口、快照嵌套不可变、批量单次发布、释放后零通知。
