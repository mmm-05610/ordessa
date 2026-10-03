# T010-03 H2 观察登记（待裁决，未改行为）

**对象**：`plugins/model-provider/chat-contribution/src/next-turn-client.ts` 的
`submitTurn` ready 应用。

**现象**（转换期间发现，行为保持原样未动）：ready 回答携带的 `sequence`
无条件覆盖已记录序（`sequence = answer.sequence`）。若 ready 是对**较旧意图**
的迟到回执、而期间已有更新的 queue ack（M12 围栏要求"较旧点击的迟到确认永
不覆盖较新记录序"），ready 会将序**回退**，与 M12 围栏注释的规则相悖。

**证据**：`tests/turn-application-dispatch.test.tsx` M11 用例中 ready 携带
sequence=5 而 queue ack 为 6，测试只断言 pending 不被消费、不断言序——现行为
下内部序回退至 5。

**为何未改**：ready 的 `sequence` 语义有两种解读（被消费意图的序 vs 队列修
订序），改哪边都可能动到 12 个测试文件里未明示的假设。按"不擅自改语义"纪律，
保持行为逐字节一致，登记待用户/012 裁决。

**选项**：
- A（建议）：ready 应用加单调围栏（同 M12：`answer.sequence >= recorded` 才
  覆盖），补红首测试（旧意图迟到 ready 不回退序）。影响面小，与注释规则一致。
- B：维持现状，把 `sequence` 明确为"被消费意图的序"，在契约注释里写死，围栏
  只属于 queue ack。需同步改 M12 注释与 guarantee 文档。
- C：让服务端 ready 回执改带队列修订序（wire 变更，跨版本，需 012 发行流程）。

**建议**：A。红首测试可以先落（对现行为为红），实施即转绿。
