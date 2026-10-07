# Codex 纯读效果边界补验

本批只补离线验收，不增加模型请求、不读取凭据用于测试、不启动 Harness。实际原 Codex owner 经真实临时 SQLite 核心的公开 providers 接缝运行，未新增产品执行器或效果权威。

| 场景 | 证据与结果 |
| --- | --- |
| valid / invalid / unverifiable，真实 Profile 来源与 offer/assessment | offline/full-suite.xml、offline/T57.xml、offline/T62.xml：三个状态的已监测写文件、进程、socket调用尝试均0；DB/WAL及其余文件字节和目录项不变 |
| 编译器吞掉写文件、os.write、进程、网络guard异常后仍返回valid | 同上，四项故障注入各精确记录1次尝试；不把被阻止的尝试记成零调用，文件状态仍不变 |
| 初版要求全部文件字节不变 | codex-effects-shm-red.txt/xml：3F/15P，SQLite共享内存读者标记变化，保留失败原记录 |
| 核对SQLite正常读者标记后修订判据 | codex-effects.txt/xml：初次18P；最终全套含新增fd反例359P；SHM仅字节100–119允许变化，其余SHM、DB、WAL和其他文件仍严格相同 |
| 全套、逐场景、原家族与基线 | offline/receipt.json：359P、67独立场景P，T60离线NOT_RUN；codex-family.xml：147P；baseline-core.xml/current-core.xml：各57P |
| 原模块独立wheel离线构建安装 | acceptance-build.txt、acceptance-wheel-install.txt：退出0 |

SQLite字节100–119是五个读者标记，依据[官方WAL格式说明](https://www.sqlite.org/walformat.html)。这不是放宽业务写入门：提交帧/数据库/WAL变化或SHM其他字节变化仍失败。

监测覆盖当次Python open写模式、os写入/文件变更/进程API、subprocess.Popen、socket发送/连接；不声称OS级sandbox或任意代码都不能逃逸。预先保存函数别名、已有Python文件对象方法、C扩展等未由该observer全面拦截；最终快照证明净状态，不证明任意未监测短暂变化。现实际owner源码未走这些效果路径。独立只读审查指出fd漏检后补上os.write/pwrite/writev/ftruncate guard与具名fd反例。

既有真实Jev归档独立复验仍通过，无key/HTTP/Harness；累计请求仍220，报告tokens仍176303/14227，历史3次usage未知、费用UNKNOWN。旧质量/协议失败及其他继承红、Python3.10、真实断电/远程FS等未验证项不关闭。Codex仅声明编译能力，原生配置应用仍unknown，其他家族unsupported。真实Harness有限烟测授权尚待答复，all_work_complete=false。

```sh
.venv-decision/bin/python packages/backend/decision/checks/offline_acceptance.py
.venv-decision/bin/python specs/031-jev-decision-module/evidence/codex-pure-read-20261005/verify_archive.py
```
