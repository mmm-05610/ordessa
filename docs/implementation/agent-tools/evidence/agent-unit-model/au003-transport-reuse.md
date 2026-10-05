# AU003 公共运输复用

来源固定为77a1d8a92c，未重新编写品牌协议或启动通用翻译层。

| 来源 | 提取结果 | 验证与限制 |
| --- | --- | --- |
| products/agent-tools/src/ordessa_agent_tools/native_clients/_transport.py | ordessa_harness_transport.channel | 原14项测试保留；实际ProcessChannel单stdin lease、write/fence同RLock、unknown保留、close connection不stop、异步原生帧不改写。修复原request立即重排不匹配帧导致永远消费同帧的缺陷，有事件先于response反例。 |
| plugins/harness/src/ordessa_harness/server_acp/transport.py | ordessa_harness_transport.ndjson | 已审阅managed NDJSON原实现提取；旧七家依赖仍在过渡原包，不在此次直接替换其未核对路径。新包保留并实际执行原31项测试。 |

公共包distribution为ordessa-harness-transport，Python import为ordessa_harness_transport，无运行依赖，无品牌方法/配置schema、注册/持久状态或daemon。三家独立包以它为提供者侧依赖；Agent Tools最终wheel不得含它或品牌客户端。当前产品/旧Harness来源尚保留，迁移退出条件为三家独立provider接纳、调用方迁移与AU004发行边界反例通过；不将临时重复称最终去重。

ProcessChannel默认保留旧非managed受控客户端API；生产提供者应显式managed=True并使用acquire_writer/bind_writer。LeaseBoundChannel符合原send_raw/request/notify/reply/poll接口，close只撤销自己的writer，Unit进程由owner明确stop。writer lease只证明实际运输占用，不是InvocationContext/目录/activation/management epoch授权；提供者必须逐dispatch重核全部作用许可和固定capture。没有可信lease/权限不开放入口。

主会话执行专属venv `-m pytest -c packages/backend/harness-transport/pyproject.toml packages/backend/harness-transport/tests/test_channel.py -q`：14P/0F、exit0、5.78s。随后同命令改tests目录：23P/0F、exit0、6.08s。新增9项反例验证实际Python peer stdin：无lease/复制lease、竞争writer、断连仍存活、旧lease不写、unknown跨fence/断连保留、非法有限UTF-8 JSON发前拒绝、真实write与撤销共享屏障、interleaved事件保留、timeout禁止替代writer。属于受控peer C＋实际pipe证据，非三家P/M。

尚未验证：整套提供者租约Authority/NativeState持久恢复接线、真实上游进程、跨进程连接争抢、子进程树退出、Windows。同步ProcessChannel只在观察stdout EOF时fence，生产owner还需持续读泵与重核；不能凭此门宣称完整运行时可用。NDJSON及ProcessChannel均不会自动重发或自授权。

最终快照：完整目录 `-m pytest -c packages/backend/harness-transport/pyproject.toml packages/backend/harness-transport/tests -q`，55P/0F、exit0、6.37s。包括14个原channel、31个原managed NDJSON和10个新managed channel反例。新增反例拒绝跨LF借用UTF-8续字节，逐帧独立解码；历史54P快照不覆盖这一修复。fresh六个本树wheel离线安装及三家隔离Registry检查共12条命令全exit0，临时环境已清除，详见au003-fresh-provider-install.json；没有安装第三方或启动Harness。
