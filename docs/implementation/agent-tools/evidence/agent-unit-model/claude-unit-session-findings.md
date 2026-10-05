# Claude SDK：Unit 与 Session 分离

只读子代理核对官方SDK0.2.163固定源码9c69ce7aced5cdf2aa1ac86fe62e877b4962de8b。没有安装或启动SDK/Claude，没有模型调用。

- client.py84–235：connect(None)仅transport.connect/Query.start/initialize，不发送user prompt；不证明CLI无初始化网络副作用。
- client.py488–510及query.py287–338：get_server_info是初始化control回执缓存，不校验session/PID，不是独立Unit或Session身份依据。
- query.py658–700：原initialize有原生request_id及匹配控制响应。可信transport owner可保存同一受控pipe上的原请求/success receipt，绑定原start操作。
- subprocess_cli.py733–826：默认transport私有_process为anyio.open_process实际句柄；公共SDK client不暴露PID。本产品应使用自己的owned transport观察面，不导入SDK私有_process。
- message_parser.py199–339：system/init保留在SystemMessage.data，assistant/session_id可缺；result/stream_event有session_id。时序不保证，default只是发送选择值，不能作为native SessionID。

源码根：https://github.com/anthropics/claude-agent-sdk-python/tree/9c69ce7aced5cdf2aa1ac86fe62e877b4962de8b/src/claude_agent_sdk

设计明确Unit、Process、Session分离。核心NodePublication允许nativeSessionRefs为空，但真实Unit需owned process/transport身份、固定安装/根、原start关联、同pipe initialize success及当前存活证据。现UnitRecords.record_session仍严格要求实际session；不能放宽它来填假ID。后续主会话须增加明确版本的Unit确认记录方法并保持原Session合同，之后才能接Claude。当前SDK receive_native只看message.session_id，亦须补SystemMessage.data中的实际init身份以及owner侧原帧保留。此发现是实际接缝缺口，不是已完成实现。
