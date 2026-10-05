# Agent Tools 准备状态

## 已完成（仅准备）

- 托管worktree：`/home/maoqh/.codex/worktrees/agent-tools-product/ordessa`。
- 分支：`codex/agent-tools-product`。
- 固定准备基线：`baseline/cp-monorepo-0`，`6a3f24456130b5caad82682d692d2d198721f0a8`。
- 主树只读观察HEAD：`b4bf7cd90951d0fa9bcf3a3de2e66b7db6a62aa0`；主树已有dirty文件未动。
- 026只读观察HEAD：`b12296ad4444c1cf0c1cdb891be2ca55cc850536`；活跃、可变化，不是获准消费基线。
- 独立venv：`/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312`，在源码树外，不共享旧树site-packages。
- Python 3.12.14；pip 25.0.1；`pip check`退出0，无broken requirements。venv只含基础bootstrap，不代表产品依赖已安装。
- 标准库检查：sqlite3 3.53.1、SSL OpenSSL 3.5.8可加载；sys.prefix与base_prefix不同。
- Node v22.22.1、npm9.2.0实测；本工具CLI拟用Python，没有运行npm ci。
- Codex/Pi命令路径可发现；没有执行模型、启动Harness或读凭据，不据此宣称支持完整原生入口。
- 029目录、架构、接口和阶段设计已保存。
- 材料检查：6份文档标题与本地链接检查通过，退出0；只是设计材料检查，不是产品测试。

## 需要明确的下一步

当前准备基线早于最新主树和026；不在旧树实现新核心，更不复活旧兼容链。正式实现先固定已验收的消费SHA，按授权更新此树并同步028修订权威。P0完成不等于可以直接跳P4真实调用。

产品Python/npm依赖、wheel构建、真实核心装配、CLI实现、三Skill实际资产、MCP、真实SQLite/原生进程/DOM/模型测试均未完成或未运行。本轮只准备环境与设计。

## 运行权限

未启动任何服务，未打开端口，未改变用户数据、Token、原Harness安装或Codex配置，未安装全局Skill；未创建新仓库、提交、合并或push。没有实施执行者在此树运行。

## 查看设计

[029产品目录与架构](../../../specs/029-agent-tools-product/architecture.md)。核心装配规则沿用主树028审阅材料，只读引用；变更需同步正式权威而非子树自建一套。

## 2026-10-04 实施启动核查（尚未切换基线）

已完整读取本树AGENTS/baseline、029四文档、章程/状态及028核心设计/契约/迁移/验收/审阅/材料校验源码。已开3个只读子代理并由主会话复核；用户已明确要求多个子代理高效执行。

建议固定adce734db21945181bf93da9720158d05e957654，理由与精确切换提案见[基线核查](baseline-review.md)。待用户确认该SHA和本树归档/摘要核验后fast-forward方式；当前HEAD仍6a3f244，未实现产品源码。已有设计材料不覆盖；原章程“仅准备”由本轮实施请求更新，基线批准门仍有效。

第一批001–005准备工单已保存，依赖/写权/反例/缺席行为/并行单元明确，尚未派执行。公开核心缺口与未决wire均登记。后续原生任务、三Skill/分发、隔离安装验收按029顺序，MCP不阻第一版。

本次命令与原文件/设计摘要见evidence/baseline-inspection.json。产品单测0、契约测试0、真实隔离服务测试0、真实模型调用0；引用026已有验收不记本次通过。没有服务启动/重启、用户DB/凭据/全局配置修改、Git提交/切换/推送/主树合并。

### Spend

子代理请求3；费用无法精确取得，标unknown；真实外部Agent/模型测试调用0。

### 本轮准备校验

工单结构首跑退出1（5单缺depends_on order id），补正后严格校验5/5、退出0；git diff --check退出0，HEAD复核仍6a3f244。四份原029文档SHA256逐项未变。记录见evidence/preparation-validation.json。均为准备校验，产品门未运行。

## 2026-10-04 固定基线后的实施（当前权威状态）

前文“仅准备/未切换”是历史记录。用户go批准固定adce734db21945181bf93da9720158d05e957654及先归档、摘要核验、ff-only切换，本树已执行完成；归档15份设计文件逐项hash未变。证据pre-switch/receipt.json与baseline-review.md。未cherry-pick移动分支，其他树只读。用户另明确批准现有RequestKey身份与核心公开薄绑定，见rulings.md R-0002/R-0003。

修改：同Environment/同SQLite Store增加原子domain-records/1，Profile不可变manifest与独立catalog版本、双CAS、授权、请求键重放/冲突、SecretRef限制；Pacthold新增agents.public（不改既有pacthold.public导出），无业务插件/第二数据库。Server唯一registry新增核心方法factory生命周期与owner保留，公开Profile wire薄绑定。CLI独立stdlib transport、发现和Profile命令，schema由核心生成；节点与输入未装配。三子代理按存储/Server生命周期、CLI/分发、核心反例/部署切片并行，主会话独占合同、Git和本账本。

已验证：持久化新定向12项通过（执行者）；CLI早期发现20项通过（主会话，6.15s）；核心真实隔离SQLite31项通过（执行者）；Server生命周期15项通过（执行者，0.11s，owner/DB double，非真实service）；薄wire契约6项通过（主会话，0.11s，实际临时SQLite，非HTTP服务）。CLI新增命令、部署及安装包仍待主会话整体验证，不能相加称产品验收。

基线全量327P/3F，退出1，继承方向扫描失败已登记docs/known-issues.md，不删断言。生命周期首跑11P/1F为新fixture遗漏display_name，补正后15P。Server依赖安装两次退出1（本地闭包未全提供：server-compat/harness），解析所有本地pyproject依赖闭包后安装退出0，沿用server-linux-py312 lock；专属venv内，无全局安装。

本轮真实模型调用0。当前无Git提交/推送/主树合并；临时服务验收尚未完成。P1仅Profile数据基础完成，不能称非Chat真实节点prepare门通过。P3/P4仍需公开贡献者、目录授权、唯一Harness owner和原生session/input证据；P5分发/Skill在并行准备。

### Profile切片真实服务与分发检查点

主会话定向核心/存储/生命周期/薄wire联跑64P退出0(0.35s)；后续完整性修复增加重放identity/revision/digest/extra篡改拒绝、损坏JSONtyped不可用、registry并发RLock（执行者16P，确定性反例能抓去锁实现）。真实临时uvicorn＋独立CLI两场景，连同部署边界9P退出0（执行者，5.08s）：CRUD/CAS/历史、权限、重启同namespace、预置unknown独立标fixture；实际TCP回执丢失另场景提交create恰1次，CLI unknown6，恢复仅entry/show/list，未重发。测试服务与proxy均主动退出，无用户服务动作。

CLI/客户端合同/隔离wheel安装42P退出0（20.60s，执行者），bundle6P退出0（1.93s）。3个Skill格式校验退出0（只材料，不计Agent任务完成）。build-time生成schema，不是客户端依赖；实物products/agent-tools/dist/bundle-0.1.0a1（ignored）包含wheel/3Skills/schema/README/SHA256SUMS，7文件hash核验退出0。Skill明确nodes/input缺席。

受影响Server/Plugin API回归11F/162P退出1（2.86s），同固定adce源隔离比较也是完全相同11个失败ID、162P（2.67s）；日志server-seams-regression.txt/server-seams-fixed-baseline.txt，无新失败ID，不把总回归报绿。新core全量首次4F/338P退出1，其中新增一项是旧scanner probe路径退休后随机选首module，对合法environment-api导入误判；只把probe固定到真实core/dtos.py，原断言全部保留。方向定向3F/3P，三个继承失败保持，见direction-regression.txt。

用户已批准R0004 Workspace＋显式DirectoryAuthorityPort；新增006目录授权与007同journal具名step工单，签发/存储基础并行，公开合同主会话冻结。现有Workspace local host=None不能证明realm，缺可信host授权映射拒绝，不能靠目录访问权限冒充execute。生产接纳、Harness RuntimeProvider/唯一owner、native session reservation/input、transport fence、真实模型仍未验收。

主会话全products/agent-tools联跑116P，退出0，27.17s；按类别精确分账见evidence/profile-slice-validation.json（42客户端/安装、6bundle、31核心SQLite、16生命周期double、12wire契约SQLite、9部署/真实service）。这是Profile-only快照。随后resolver改为只返本轮捕获Environment并与撤销共享锁，防止旧handler lazy-open下一轮；新增反例后生命周期17＋wire12=29P退出0(0.29s)。

006/007新工单结构首跑退出1（重叠写权serialization和缺fenced command），补正后7/7退出0；没有改产品断言来通过结构校验。归档tar.gz与临时固定源码副本明确ignore，文本receipt可审阅；bundle ignored，不存二进制入Git。

### Directory授权切片与后续独立复查

006执行者20P退出0(0.25s)，主会话联跑Directory20+薄wire16=36P退出0(0.29s)。同原WorkspaceRecords/DB读取项目，不另建项目库；绑定写同Environment StorePort、实际临时目录stat，OS事实不代替AuthorityPort。绑定只授固定requested purposes；原始grant超集不扩权；重放核project/purposes/realm、原三元request和protected digest，拒另一合法binding调包。原fixture大写RequestKey首跑失败已修为合法小写，不改断言。严格env_host=None缺证据拒绝；未生产接纳/原生使用。

独立复查后：部署core.sqlite-wal/-shm链接写前拒，四反例目标/main DB字节不变，部署＋HTTP13P退出0(5.14s)。薄wire分开参数阶段和调用阶段，已提交后ValueError/TypeError/KeyError/RuntimeError全部unknown而不是INVALID_REQUEST，16P退出0；UTF-8/非有限JSON输入发前拒。CLI ProfileRef形状/类型/namespace/关联identity从生成schema核验；初跑clone fixture错误地返回源id reviewer，而新请求id copy，新检测报unknown6（1F/34P），修正fixture真实clone结果，原成功断言保留；定向25P后新增两个UTF-8数值反例。主会话全产品目录最新快照152P退出0(29.73s)，日志profile-directory-validation.txt，随后新增core owner冒领反例等待下轮完整复跑。

具名operation-records/1合同已冻结供007实现：沿env_requests完整三元主记录，env_request_steps子步骤，现env_usages增量持久holder/target CAS；不采用第二CoreRuntime/Agent journal。读写始终完整RequestKey，opRef同env唯一；Usage holder为完整scoped mapping而非裸id。old rows保持旧知识枚举与花费事实，阶段status独立，不扩oe-contract/1 Outcome。暂无provider调用或node能力发布，基础存储通过也不计native成功。

### Profile＋目录＋操作存储基础最终复跑

主会话全products目录187P、0F、exit0、29.30s，见evidence/product-final-foundations.{txt,json}。分账：49客户端/隔离wheel安装，6bundle资产；16薄wire合同（实际临时SQLite、非HTTP服务）；17生命周期/registry double；32核心Profile SQLite、20Workspace授权/目录事实、34operation SQLite；11部署边界；2真实隔离Server＋独立CLI场景。两HTTP场景覆盖真实提交回执丢失与零重发、重启身份、权限和CAS；不代表原生任务成功。产品整体仍PARTIAL。

007独立复查发现同digest不同intent、Usage rights扩张、published/step证据与冻结配方篡改，均已修并加反例。intent/result/evidence独立canonical摘要用于损坏检测，不是授权签名；旧bare-id写口拒覆盖scoped记录。沿现Environment语义released Usage终结，不能复活/转holder，重取须新id；unknown→active仅concluded证据。独立临时SQLite反例最终exit0、未发现新增确定阻断。操作专测34P，含原SQLite测试71P（执行者exit0，主会话复跑日志operation-and-storage-final.txt）。SIGKILL仅自建临时测试进程。

核心回归339P/3F、exit1、7.50s，仍同三个方向扫描继承失败，日志core-operation-regression.txt；受影响Server此前11F/162P与固定基线同ID保持登记，不称全量绿。资料工单12/12 exit0、diff check exit0只算结构。原始Profile-only bundle是历史快照；新build输出dist/bundle-0.1.0a1-profile-directory，exit0，全部7 payload hash校验exit0，CLI仍独立、不带后台或秘密。

用户已批准R-0005显式InvocationAuthorityPort。008当前冻结具体签名/不可伪造可信Context验证边界；现Policy bool与owner_application不能冒充新的授权。失去进程内Context证明时拒effect，不能据memory空证明notDispatched。下一生产缺口仍包括Unit/Session目标及同配置owner journal迁移、共同配置scope排他、可信贡献接纳、原生correlation/query、实际transport fence与单session/input reservation。未实现nodes/tasks/results；Skill格式/安装不计Agent任务验收。真实模型调用仍0；没有push/main merge、用户服务重启或全局Agent配置修改。

### R-0005 Invocation基础主会话验收快照

AT-008A仅新增core agents/invocation.py与products隔离测试；显式authority/current-state且冻结invocationBindings，从同SQLite Store claim首次才签发。Context精确issuer对象身份、immutable快照、受限verifier、锁内一次consume、重入保护、有界ticket与claim前容量预留。grant/epoch/provider/目录/取得关系重核；Cleanup限已取得目标，独立当前read grant可查询旧epoch未知事实。失去进程身份不重签已花费claim，verify失败也不恢复effect ticket，不写假native结果。有限UTC clock拒NaN/Inf/bool/负数；future annotations只修已知3.9类型定义兼容，未实测3.9。

执行者authority53P、连operation87P exit0；主会话此前47P快照早于6项clock反例，最终全products **240P、0F、exit0、29.13s**，分账evidence/product-invocation-validation.json。新增53项是真实SQLite claim＋受控authority/state合同，不能算真实Provider或模型。核心复跑339P/3F exit1、7.74s，同三个继承方向失败不隐藏。资料12/12与diff check退出0只结构。

AT-008B两个只读审阅完成，共同scope与target/journal迁移准备见harness-target-migration.md。现session/channel排他未证明跨channel/Unit共享物理资源；普通scope字符串无权威。生产缺口是第一家真实unit reservation、owner统一scope映射与跨journal共享资源authority、所有入口admission cut及native receipt/query/fence。这些实现事实缺席时保持unsupported，不能用fixture取得关系替代。当前仍未实现节点/任务/结果查询，整体不是完成版。

分发新增ACCEPTANCE.md，说明安装/使用/分类验收与未完成门；bundle now包含该文档。相关bundle6P exit0、1.92s，build新鲜输出dist/bundle-0.1.0a1-foundations exit0，8项payload checksum全通过；不覆盖历史bundle。240P快照后只有分发文档/复制清单修改，定向6P覆盖；未再重复无关测试。原029四份设计hash仍与切换前归档一致，见design-preservation-final.json。

AT-008A最终独立代码复查53P exit0(0.52s)；额外撤销probe exit0：grant撤销拒、恢复也不恢复effect ticket，持久claim仍possibly-dispatched。独立连接writer探针第二Store被WriterLockHeldError拒绝，exit1（owner安全门符合预期，未绕过）；不能宣称独立writer并发claim已实测。8issuer/8线程是共享同可信Store的竞争。未发现基础范围内新确定阻断。跨进程授权、生产接线、跨端口原子性、真实Harness作用与运输fence仍未验收。所有临时过程只本树隔离资源，模型0。

下一原生切片只读核查推荐Pi installed profile bridge：entry.mjs导入前固定私有配置/session目录；creation.mjs refresh allowNetwork:false；server.mjs session.new与prompt分离；AccessEntryTransport已有启动/释放证据。这里只读源码，SDK实际零模型/零网络session创建未实测，不报绿。旧AcpChannelRegistry仍launch先于run持久化且spent scope内存，依赖profiles/session/turn；native creation attempted/query无冷恢复ledger，history仅prompt后写。下一008B/009必须在Harness同owner补真实unit reservation、统一scope、创建前持久core correlation、响应后立即NativeSessionBinding、epoch与晚到效果fence。不能直接接旧ExecutionProvider或runtime_compat。详见harness-target-migration.md，整个产品保持PARTIAL。

### 独立安装后实际使用（用户要求自试）

直接执行本地bundle wheel，不复用pytest辅助类、不以源码模块代替已安装entrypoint。新建ignored临时目录及fresh client venv，pip --no-index --no-deps安装实际wheel；pacthold/ordessa_server/ordessa_harness均不在客户端环境。配套服务使用既有Server、自己持有的临时root/随机端口/随机fingerprint key与临时Bearer，不读或修改用户凭据；正常停止两轮，临时venv/DB/Token/日志均清除。模型调用0。

运行命令：`/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python products/agent-tools/acceptance/install_use.py`。脚本首次执行位置在evidence，完成后归产品acceptance目录并更新相对路径（满足测试/分发资产在products），逻辑未改变。实际运行exit0、26项安装/命令/停止记录，原始安全输出见evidence/install-use-exercise.json。不是新增26项pytest。

安装/独立性/help、doctor、capabilities、Profile create/read/edit/history/clone/archive/restore、确认后同请求重放、服务正常重启后历史读取与原edit结果重放均退出0。无效临时Token退出3；陈旧CAS退出5；缺真实provider的preview退出4、ready=false；停服doctor退出4。nodes list与run hello解析退出2，明确命令尚不存在，不是可运行任务。doctor supports=profileCatalog:true/nodes:false/managedInput:false。

Profile manifest显式标记catalog-only，引用deliberately-absent-catalog-check；只能证明目录数据真实服务读写，不能算真实Harness配置或Agent成功。三Skill拷到临时项目目录并核对configure Skill步骤，没有全局安装，也没有独立模型Agent行为评测。用户要求的自试结论：wheel可独立安装、目录功能可用，Agent运行能力仍未交付。diff check退出0。

迁到products/agent-tools/acceptance后已按上述精确命令再执行，exit0、26记录、runtime_cleaned=true、模型0，覆盖相对路径变更；安全记录更新为该轮，不累加成52场景。未改CLI实现或隐藏缺失命令。


### AT-013 本机初始化发现与 0.1.0a2 安装验收

用户要求的初始化已完成Linux切片：`ordessa-agent init --json` 不需要service配置/Token；`--path`可显式选择扫描PATH，`--output`只写调用者选择的新文件（600、排他创建、拒覆盖）。扫描常规可执行文件、链接目标、全部shadow路径，保留不可扫描诊断；空/相对PATH不会隐式搜索当前目录。没有候选退出4，参数/报告错误退出2；发现候选仅表示本机文件观察，artifact/provider未核、runtimeReady=unknown，不发布节点能力。

候选目录由Harness公开纯metadata API `ordessa_harness_api.command_discovery`发布；8个family的名称取自现有Harness声明，构建期生成客户端JSON镜像并验证digest。CLI不导入Harness/Server，扫描不执行候选程序、不查询版本、不安装/登录、不联网、不启动服务、不写全局Agent配置。三份Skill均增加init步骤与本机/远端、文件/运行就绪边界。

修改覆盖products下CLI、初始化模块、候选镜像、生成器、打包清单、测试、三Skill、README/ACCEPTANCE及真实安装使用脚本；Harness只新增公开metadata模块。版本升为0.1.0a2，使已有alpha用户可以正常升级。安装包为ignored `products/agent-tools/dist/bundle-0.1.0a2-init`；build exit0，9个payload的`sha256sum --check SHA256SUMS`全部通过、exit0。

验证命令使用本树专属`.venv-ordessa-py312/bin/python`：`-m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests -q` **260P/0F、exit0、29.68s**（日志init-product-validation.txt）；其中新增初始化真实临时文件反例20项。release版本修改后`test_bundle.py test_distribution.py -q` **8P/0F、exit0、5.87s**（init-release-validation.txt），验证wheel内镜像、独立安装入口与资源。此前26项初始化/安装定向快照是修复前历史记录，不与260累加。三个Skill格式检查各exit0，只证明材料结构；不算独立Agent行为验收。

独立只读审阅发现两处边缘缺陷：已找到文件时仍须保留其他PATH访问失败，及FileNotFound后的链接检查也可能权限失败。已修复并增加两个反例；最终独立初始化复跑20P/0F、exit0、0.07s，无本单范围内新确定阻断。工单结构首跑缺三个必需段落退出1，补齐后13/13、exit0（init-work-order-validation.txt），只算资料结构。

再执行 `python products/agent-tools/acceptance/install_use.py`：fresh client venv安装实际0.1.0a2 wheel，确认无后台包，实际已安装entrypoint在服务启动前执行init，然后完成既有Profile真实隔离服务用例。总脚本exit0、27条安装/命令/停止记录（含预期拒绝的非零CLI结果），临时runtime清除、真实模型调用0，见init-installed-use.txt及install-use-exercise.json。本机实测发现codex `/usr/lib/chatgpt/resources/codex` 与pi `/home/maoqh/.local/bin/pi`；它们均未执行，runtimeReady仍unknown。27条记录不是新增27个pytest，也不能算Agent任务成功。

AT_013_DONE仅指Linux本机初始化门完成。Windows真实宿主/PATHEXT未验证；没有验证候选版本、认证、原生session或模型。整个Agent Tools仍PARTIAL：节点/任务/结果命令和生产Harness接纳/授权/共享scope/journal/fence缺口保持。此切片不改核心运行实现，未重复无关核心/Server全量；既有3个核心继承失败和11个Server固定基线同ID失败仍保留。无推送、主树合并、用户服务重启或全局配置修改。


### 2026-10-05 三家优先目标恢复 · 源码核查

当前HEAD3086825a6177438c042431cdb94812ded576ee6c，开工git status clean；已包含029收口0f786dfc34及030十家CODE_READY检查点，不把旧adce当现有实现快照。前一初始化轮为progress（CLI/Skill/source/evidence已落盘）；030终账并未证明节点/输入运行。当前核实核心AgentServices仍仅ProfileCatalog，AT008/009/010/011未完成。新增客户端存在，但真实协议关联/完成有缺陷：Codex嵌套turn形状未读、Pi0.86.1成功prompt无disposition，Claude控制stdio尚未消费。三个代理按家族不重叠消费者文件修复，主会话负责核心接纳/契约/整合。

本次用户目标改为Pi、Codex、Claude Code优先，其余七家保留。继续原工单并采用incremental-work-order纪律；单元合同见runtime-admission-contract.md。未经另行授权不安装更新第三方、不读用户认证/运行DB、不执行真实模型或用户服务重启。所有测试分L1合同、SQLite、L2真实进程和L3/L4产品任务记录；当前未新增运行可用声明。

### 2026-10-05 初始化入口复核与使用边界

用户再次要求CLI/Skill初始化探查。当前源码已具备`ordessa-agent init --json`，三Skill均包含步骤。本次实际源码入口exit0，发现Codex `/usr/lib/chatgpt/resources/codex`、Pi `/home/maoqh/.local/bin/pi`（链接目标`/home/maoqh/.pi/agent/bin/pi`），Claude Code未找到。命令未执行候选、未探版本、未使用认证，runtimeReady仍unknown。

定向命令：专属Python `-m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_initialization.py -q`，20P/0F，exit0，0.06s。另fresh临时venv通过`pip install --no-index --no-deps`安装已有历史0.1.0a2-init wheel，实际已安装entrypoint `init --json` exit0；扫描完整，找到同两家。证据`evidence/init-recheck-20261005.json`，临时venv已自动清除。这不是当前未提交原生协议修改的新分发验收，也不代表Agent任务可运行。

独立只读复查指出目录限8家、仅PATH、命中不证明引擎身份、部分扫描需看诊断、Windows未验收。README补充8家范围/部分扫描/远端使用边界；三Skill明确本机初始化可选，缺本机二进制不阻止远端Profile操作。未扩展其余七家、未自动安装二进制或修改全局配置。

核心最新复跑：`-m pytest packages/backend/pacthold -q` 269P/3F，exit1，7.10s；三个同ID继承方向扫描失败仍指向测试目录旧SQLite import。原C1三字段及public facade新增失败已修复，未删断言。新RuntimeProvider接纳21P与原public合同34P定向55P已通过；节点发布20P、UnitRecords18P+原journal9P和managed运输31P是执行者定向证据，主会话整合复跑尚待完成。InputReservations当前正在审阅和加反例，尚不算已验收；CLI nodes/managedInput能力继续false。

### 三家核心/消费者基础整合复跑（未接产品运行）

主会话全products复跑570P/0F、exit0、68.36s，日志evidence/three-family-product-validation.txt。这是发布资源完整性修复前的源码快照；其后独立复查实际复现遗漏Usage仍可published，已在同publish transaction要求交接所有未released Usage、拒unknown，并在NodePublication要求真实unit use关系，保留失败反例。之后operation＋node＋input定向94P/0F exit0、1.98s（39＋25＋35，共享用例不能与570累计）。其后把028已定义connect(unitRef,authorizedLease)补入RuntimeProvider SPI，接纳＋node＋input再次复跑81项；整体仍不声明nodes可用。

协议复跑：Codex＋Claude消费者52P exit0、8.00s；Pi三文件69P exit0、2.76s（固定0.86.1真实无disposition receipt、unknown便利prompt拒新id、UI confirm等native shape一次响应；通知不授回应资格）；Claude纯planner43P exit0、0.14s。Pi原14P历史fixture中的虚构approval/action/text更新为官方confirm/method/confirmed响应，same-id和native回应断言仍保留。N003“无官方SDK”错误已撤回并引用固定SHA官方SDK文档，仍选择单一原生RPC通道，无fallback。

Harness共享scope/UnitRecords＋原OperationJournal32P exit0、0.36s；真实stdin managed transport31P exit0、0.42s。旧reserve_new同BEGIN IMMEDIATE接唯一owner scope guard；重启缺authority但有持久Unit拒，原request重放不作用；同scope旧跨channel互斥、scope_key损坏拒。此门不覆盖旧ProviderRestoration/Registration的owners.begin_restoration执行链，本产品不接该链。UnitRecords的scope释放、冷重启受限reconcile记录授权及生产原生证据端口仍未实现。

当前新增基础只复用唯一registry/SQLite operation/Usage、既有Harness journal及实际运输。生产prepare层须读取并核验真实immutable Profile manifest；publication primitive只核ref/步骤/owner投影，测试故意使用受控owner不能代替完整装配。InputReservations只持久reservation与一次Invocation claim；生产writer必须消费同context固定captureDigest/正文/native correlation，不允许另给正文/id。真实capture store、生产RuntimeOwner、public node管理入口、CLI附着、配置apply/结果/恢复链尚未闭合。真实模型0、安装第三方0、用户服务重启0，整体仍PARTIAL。

最终修复后主会话全products再次复跑 **575P/0F、exit0、68.53s**，日志evidence/three-family-product-final.txt；替代前570项源码快照，不累计成1145。最新节点25P、输入35P、runtime接纳21P定向组合81P/0F、exit0、1.60s。13份工单结构检查及git diff check均exit0，仅资料/格式证据。

生成新鲜分发`products/agent-tools/dist/bundle-0.1.0a2-three-family-foundations`，build exit0；9项payload SHA256校验exit0，未覆盖历史包。三Skill包含本机发现可选/远端操作边界。后续Pi生产接线责任及资源缺席行为写pi-owner-integration.md。全量绿仅覆盖当前测试定义，未补的production RuntimeOwner、CLI nodes/tasks、授权生产部署及真实模型L3/L4保持未完成。

新鲜wheel实际独立安装复验：fresh临时venv，pip --no-index --no-deps install exit0；实际entrypoint init --json exit0，发现同Codex/Pi、scanComplete=true、runtimeReady=unknown。证据evidence/init-current-wheel-20261005.json；临时venv清除，未执行候选或访问用户认证/服务。

### AU-1增量包接纳 · 2026-10-05

用户已确认AU001–AU005，按docs/implementation/work-orders/agent-unit-model的五份合同及五工单串行推进。本次HEAD仍3086825a6177438c042431cdb94812ded576ee6c；上一轮575P和三家/核心源码为实际progress，但未提交。现无运行子代理/共享写者，三位均completed。逐文件读取本包11个新增文件并记录SHA256到evidence/agent-unit-model/adoption.json，显式纳入接纳检查点，未改本包语义正文。

保留全部已暂存三家修复及CoreRegistry/Node/Input/journal/transport基础；品牌实现仍在products属于待AU003/AU004迁移，575P不满足AU A15发行边界，不将旧绿等同新目标完成。AU001主会话唯一共享作者，不派家族执行；AU003接口冻结后才允许各家独立包写权。继承raw pytest日志仅去行尾空白以通过diff格式检查，失败诊断及计数保留。当前只接纳/冻结准备，不标任何AU_DONE。真实模型0、安装更新第三方0、用户服务操作0。

### AU001 配置/Unit公开契约冻结切片

接纳检查点30c4ef5ac0，无其他活跃写者。已有C1 resource describe/acquire/release/reconcile与supported_contracts、Harness配置adapter claims/intents已核查；实施映射和CAS范围表见evidence/agent-unit-model/interface-map.md。不新增kind/provider注册中心。新增pacthold.agents.configuration，复用Profile声明校验/SecretRef与现有scoped refs；不可变ChangeRequest/Policy/Description/Snapshot/ItemResult/ChangeResult，仅合同无副作用/状态库。

RuntimeProvider增加describe_configuration/apply_configuration/query_change，显式升级agent-runtime/2；旧/1不作新管理接纳，历史引用不篡改。descriptor新增supportedMethods默认空，方法存在不代表能力。wire_contract保留默认Profile agent-assembly/1及digest，显式version=agent-assembly/2获得providers/nodes/配置/lifecycle冻结方法；当前Server/CLI尚不启用这些方法，AU004负责镜像/接线。

C层结构测试先33P exit0(0.08s)，增加wire版本反例后与runtime/node/input115P exit0(1.10s)；增加supportedMethods反例后configuration35P＋runtime21P=56P exit0(0.17s)。发行/旧Profile镜像8P exit0(6.35s)。这些只证明不可变编码、默认不restart/defer、ACK缺依据不能applied、partial逐项保留、secret/未知实际字段/跨scope/旧Runtime版本拒绝，未验证生产配置应用。

本包--strict结构5份通过。首次误提前加--batch完成门exit1，五单每单四stage未勾选；这是未完成门真实红，未删门/改合同或伪勾选。接纳commit前格式检查exit0，仅说明格式。AU001尚待核心回归与公开验证收口；下一AU002仍按串行依赖进入，不派三家执行。三家生产scope及CAS能力未核，M预算0，整体PARTIAL。

AU001补强：UnitInspection为当前owner只读来源，DirectoryBinding/epoch/ownership不由core猜测；版本未知snapshot允许sourceRevision=null且comparisonGuarantee=unavailable，未知kind允许scope=null/actions空，不制造支持。配置结构最终38P，连runtime/node/input119P/0F、exit0、1.15s；核心全回归269P/3F、exit1、7.38s，仍同三个已登记方向扫描ID，日志au001-core-regression.txt。未改继承红断言，未恢复legacy。AU001契约切片CODE_READY、整体门PARTIAL，后续AU002按已冻结契约推进；AU003之前不派三家包写者。

### 初始化入口再次实测 · 2026-10-05 02:10 UTC

用户再次要求初始化探查系统Harness二进制。现有CLI与三Skill已覆盖，无需重复新增入口；独立子代理只读复查确认。系统`python3 -m pytest` exit1（缺pytest），改用本树既有专属venv，未安装或修改全局依赖。

执行`/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_initialization.py products/agent-tools/tests/test_distribution.py -q`：22P/0F、exit0、3.93s。含当前源码wheel构建、fresh隔离venv安装及实际entrypoint初始化受控目录；候选执行标记未创建。不是真实Harness任务验收。

执行`PYTHONPATH=products/agent-tools/src /home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m ordessa_agent_tools init --json`：exit0，扫描完整，找到Codex `/usr/lib/chatgpt/resources/codex` 和Pi `/home/maoqh/.local/bin/pi`；Claude Code未找到。候选未执行，runtimeReady=unknown。范围仍为八家已审阅命令名及绝对PATH；版本、登录、真实运行、Windows实机及远端安装未验证。AU003拆包时必须同步迁移目录生成器的旧Harness汇总来源。AU002未提交工作保留，整体仍PARTIAL。

### AU002 核心配置协调阶段检查点

基线2ce8a151286760b427c58c8111fcf341060ce95f，旧三个执行者及初始化只读审阅者均已结束，主会话唯一共享写者。新增AgentConfiguration复用Environment的同一个OperationStore/DomainStore、受保护fingerprint及InvocationIssuer；规范target scope在同SQLite事务预留，固定Node/Unit/provider activation/目录/epoch/expected native revision。required未知配置或未取得材料发前拒绝；optional不送owner并逐项rejected；全optional不适用则无claim/无native dispatch、记录refused。

owner必须实际通过同Issuer的verify_and_consume；仅收到ACK、错误digest/scope、吞掉失败验证均unknown。同key重放只读原操作，unknown/deferred占用scope，查询只核实原attempt。确认后发布中断可从concluded step完成数据发布，不重新调owner。并发查询捕获step revision，迟到结果不替换后来的已记录结果；步骤内保留独立历史观察而非“最新配置”。inspect每次向当前owner查询，实例修改不保存Profile。Issuer成功验证标志复用原_live issued_条目，无新授权字典/持久权限源。

Server的agent_core_methods新增显式contract_version参数，默认agent-assembly/1及原Profile镜像不变。显式v2接四个配置公开方法，配置结果只投影operationRef/revision/status/configurationResult，不暴露内部授权/请求事实。版本冲突为CONFLICT_VERSION、同key异内容CONFLICT_REQUEST、授权不足FORBIDDEN、未实现节点操作CAPABILITY_UNSUPPORTED；supportedMethods不包含尚未实现的节点方法，nodes/managedInput仍false。生产部署未切v2，不宣称节点产品可用。

验证（Python均为本树专属venv）：初始management10P/0F exit0、0.87s；补optional/deferred/ACK/并发及中断反例22P/0F exit0、1.82s；补Server绑定、退役、真实SQLite冷开/原子回滚后management31项。`-m pytest evidence/agent-unit-model/test_management.py`与Profile wire、Invocation组合100P/0F exit0、2.46s。随后management/configuration合同/Profile wire/Invocation/runtime接纳/Node/input七文件组合219P/0F exit0、4.36s（真实路径均为docs/implementation/agent-tools/evidence/agent-unit-model或products/agent-tools/tests）。发行test_distribution.py＋test_bundle.py 8P/0F exit0、6.30s，含fresh wheel安装；不累计历史快照。核心全回归269P/3F exit1、7.12s，仍同三个继承方向扫描ID，原始日志au002-core-regression.txt；只去行尾空白，保留诊断。五单--strict结构检查exit0，不代表完成门。

C：同SQLite真实事务＋受控owner/authority，无真实Harness；P：本阶段未启动真实Harness（发行测试为独立客户端安装证据）；M：0/未授权。AU002_PARTIAL：C1材料acquire与SecretRef受权解析仍缺生产接线；不能把resourceRefs直接传成已取得材料。生产prepare/applyProfile/lifecycle/access、三家实际Unit/native确认与owner版本比较、完整迟到原生证据的provider持久保存待后续补齐。没有新DB版本或用户数据迁移，没有安装更新第三方/读用户认证/改登录/服务重启/模型调用。共享接口及管理反例已具阶段提交条件，依AU003前置进入三家接线；所有未完成门保留，整体PARTIAL，不勾伪Stages。

### 2026-10-05 初始化入口再次实测

用户要求CLI或Skill补初始化探查。本树现有 `ordessa-agent init --json` 及三份Skill步骤已核实；执行 `PYTHONPATH=products/agent-tools/src /home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m ordessa_agent_tools init --json` exit0，扫描完整，发现Codex `/usr/lib/chatgpt/resources/codex`、Pi `/home/maoqh/.local/bin/pi`（实际链接目标 `/home/maoqh/.pi/agent/bin/pi`），Claude Code未找到。未执行候选、探版本、读登录凭据或启动服务；runtimeReady=unknown。

执行专属Python `-m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_initialization.py -q`：20P/0F，exit0，0.06s。只验证初始化发现切片；实际Harness启动、认证、模型调用及远端资源仍未验证。没有新增依赖或全局配置修改，整体产品保持PARTIAL。

### 2026-10-05 AU003 独立包与公共运输检查点（PARTIAL）

真实前置HEAD 77a1d8a92c95f607db1671e8c700d96e4ccabe3f。三家执行者均已完成切片并明确释放写权；主会话独占共享运输、原journal、装配、Git及账本。保留所有已核对成果，不回退、不整树stash。新包与复用比较逐项核对后显式纳入；原UnitRecords导入改为延迟旧品牌入口，未移除旧三家注册，A15迁移仍未完成。

三家主会话最终串行执行（专属Python，分别以各包pyproject为-c）：Pi tests 86P/0F exit0、2.92s；Codex tests 48P/0F exit0、1.50s；Claude Code tests 112P/0F exit0、6.75s。早期Pi 81P/2F为迁移后旧异常类型导入，已改为公共运输异常，断言保留；Claude96P及Codex41P是较早快照，不与最终计数累加。新公共运输完整目录55P/0F exit0、6.37s（包含最终UTF-8跨LF反例），复用说明au003-transport-reuse.md。

独立Registry与导入隔离8P/0F exit0、0.85s：staged隐藏、同唯一Environment接纳、单家退役不影响其他家、只导入选定家及故意导入另一家使guard失败。原UnitRecords＋OperationJournal＋隔离guard组合36P/0F exit0、1.00s。曾误用不存在的tests/application/test_operation_journal.py，exit4、0 tests；改为实际tests/test_operation_journal.py后执行上述36项，未隐藏失败。

执行 packages/backend/harness-transport/tests/acceptance_install.py：六个本树包构建、fresh venv离线安装、pip check及三家fresh独立Registry，共12条命令全exit0，临时环境已清除；证据au003-fresh-provider-install.json。无Server/旧Harness/CLI/Claude SDK安装，未导入其他家。工单结构五单exit0、git diff --check exit0，只证明材料/格式。

C为受控契约及真实Python peer/SQLite；P为三家真实上游进程0（未验证），M为0（未授权）。Pi实际配置读写与原操作确认消费显式owner端口；Codex接prepare/start原UnitRecords但生产端口未接，配置写入待补；Claude选官方SDK显式适配，但SDK实物/真实Unit未装配。公共运输lease仅是stdin屏障，不授予执行权。生产原生回执持久保存、授权持续重核、scope释放/恢复、三家生命周期、核心prepare/Node纵向接线及产品品牌客户端迁出仍缺，AU003_PARTIAL，不勾完成门。没有第三方安装更新、用户认证/全局配置修改、服务重启、模型调用、push或主树合并。

### 2026-10-05 AU003 原配置attempt与原生RPC关联

独立包阶段检查点996463b39a后继续；主会话仅改原UnitRecords同OperationJournal，增加原配置attempt/ticket及native RPC pre-send绑定，不增加操作系统/配置缓存/数据库。完整接缝configuration-journal-port.md：prepare原Unit必须已confirmed；原applyConfiguration Context消费、规范scope/Node epoch重核；opening/unknown拒绝替代key，原correlation不给新ticket；配置实际native版本仍由提供者串行观察比较。只持久身份/版本/摘要/证据引用，ACK或当前相同值不能确认。

专属Python `-m pytest -c plugins/harness/pyproject.toml plugins/harness/tests/test_unit_configuration_records.py plugins/harness/tests/test_unit_records.py -q` 首跑29P/15F exit1、0.63s，safe_json只接受映射而直接传了整数RPC id。改为requestId字段映射后44P/0F exit0、0.34s。追加并发/损坏/下一操作反例，并加原tests/test_operation_journal.py：最终56P/0F exit0、0.45s（配置24＋UnitRecords23＋journal9）。C为真实临时SQLite＋受控owner/verifier，尚未接Codex真实RPC，因此P/M未验证。未删断言或隐藏失败。

Codex执行者恢复写权仅plugins/harness/codex/**，接expectedVersion＋白名单defaults/readback＋实际pre-send id与原receipt；不写共享、不运行pytest。主会话独占原journal、装配与账本。Pi/Claude尚无生产确认端口，三家生命周期/core prepare/Node及CLI迁出缺口保持；AU003整体PARTIAL。

本接缝追加真实InvocationIssuer＋SqliteStorePort贯通5项：首跑56P/5F exit1、0.71s，受控流程漏掉prepare/start原步骤结论，核心正确拒绝后续claim。补真实owner结果后的原step concluded记录，保持全部门和断言；最终同三文件61P/0F exit0、0.66s（配置29＋UnitRecords23＋journal9）。issue之后撤销authority/activation/Directory/epoch均无新配置attempt，原possibly-dispatched claim保留；原配置query不重发。C层贯通，不升级为三家P/M。

### 2026-10-05 现有Codex隔离版本探测

独立于init文件扫描，在新临时HOME/CODEX_HOME/XDG与显式清空环境下，仅运行绝对路径 `/usr/lib/chatgpt/resources/codex --version`：子命令exit0，stdout `codex-cli 0.159.0`，二进制SHA256 d2752c52353401f7f6efbfcea68796f4f7a3d3e4769f5d1da53fa49d4856b72f。stderr提示临时CODEX_HOME子目录不存在、未创建PATH aliases。临时环境清除；未继承用户登录环境、未安装更新或启动服务、模型0。未对进程任意文件读取实施OS sandbox，因此证据不声称沙箱级用户文件隔离。

当前Codex实现依据固定0.157.1协议源码；观察到0.159.0不证明兼容，不自动更改pin或选该二进制运行Agent。证据codex-local-version-probe.json仅版本探测成功，compatibilityVerified=false/runtimeReady=unknown。此前init“不执行候选”仍指init自身，不能与此次独立版本探测混淆。原历史截断npm artifact仍是另一来源的已知缺口。

### 2026-10-05 AU003 Pi Unit与Codex配置增量冻结

HEAD9ef1dc2023上保持共享唯一作者。Codex与Pi执行者均完成切片并释放全部家族写权；Claude只读核对完成。Pi按原UnitRecords接prepare/start/query/access/connect，开进程前固定opening，实际原生两次get_state身份相符才确认；缺端口保持不支持。Codex默认配置batchWrite接expectedVersion、pre-send真实id、原receipt/readback；thread实际与defaults严格分离。仍缺生产端口、授权原生入口完整owner写cut、生命周期及核心纵向装配。

串行专属Python复跑：首个Codex命令未显式设置源PYTHONPATH，collection 3 errors、exit2、0 executed；补 `PYTHONPATH=plugins/harness/codex/src:packages/backend/harness-transport/src` 后 `-m pytest -c plugins/harness/codex/pyproject.toml plugins/harness/codex/tests -q` 65P/0F exit0、1.63s。审阅发现okOverridden条目unknown但attempt误confirmed导致scope释放，主会话修为unknown保留原waiter/排他，并加强原反例查询不重发；同命令最终65P/0F exit0、1.64s。`PYTHONPATH=plugins/harness/pi/src:packages/backend/harness-transport/src` 同Pi包命令104P/0F exit0、2.93s。计数均为最终快照，不累计历史。git diff --check exit0。

Claude发现记录claude-unit-session-findings.md：SDK无prompt connect可有控制握手但不保证session，core允许Unit存在且nativeSessionRefs为空。原record_session不放宽；需明确Unit确认接缝及同pipe真实process/initialize证据。只读来源核对不是P/M。三家此次测试为C（含Python peer），真实家族P未验证、M0；没有安装更新/登录配置/用户服务操作或push。AU003_PARTIAL检查点后串行返回AU002补原许可逐write重核，再回AU003实现生产投影/Unit接线。

### 2026-10-05 AU002 核心持续重核补强

AU003增量e08916abae冻结/提交后三家写权全部释放，主会话串行返回AU002。新增公开Verifier/Issuer.verify_continuation复用原Context/claim/grant，不第二claim/新Context；原步骤结束、unknown、版本/epoch/目录/activation/authority变动即拒。缺continuation绑定不以初次verify代替。活跃effect证明保留到实际结论/失败/过期，容量满发前拒新claim；可信状态检查时释放Issuer锁，避免与部署admission锁互等，状态观察之后重核grant、最后核claim。详见invocation-continuation-port.md。

原authority测试两个反例加强：缓存容量必须保留active effect（先拒新read且证明仍存，真实concluded后才回收）；当前状态之前/之后两次authority回调都拒重入。没有删除原安全断言。作为核心接口影响的验收联动，唯一主会话同步这一现有产品integration测试（无第二写者），其余测试集中在本单允许的evidence目录。

执行专属Python `-m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_invocation_continuation.py products/agent-tools/tests/integration/test_invocation_authority.py docs/implementation/agent-tools/evidence/agent-unit-model/test_management.py products/agent-tools/tests/integration/test_runtime_admission.py products/agent-tools/tests/integration/test_node_publication.py products/agent-tools/tests/integration/test_managed_input_reservations.py -q`：最终189P/0F exit0、4.59s。初次小组合100P/2F exit1、2.83s；并发版186P exit0、4.49s；状态后grant重核版188P/1F exit1、3.65s，修回调次数断言后189P。曾误用input反例单数路径exit4、0 tests，后改为真实复数路径。历史快照不累计。新continuation24项，均C层；不证明native writer屏障或三家真实任务。

核心全回归中间快照 `-m pytest -c packages/backend/pacthold/pyproject.toml packages/backend/pacthold/tests -q`：269P/3F exit1、7.38s，仍同test_kernel_tree_has_no_import_of_server_harness_or_product、test_tripwire_planted_server_import_turns_the_guard_red、test_tripwire_from_import_form_is_detected_too；日志au002-continuation-core-regression.txt。最终共享改动后复跑日志au002-continuation-core-final.txt另记。AU002仍PARTIAL，准备/材料/Node/使用/生命周期生产协调未完成；本补强不等于核心收尾。P未启动，M0，无安装/登录/服务/用户数据库操作。

最终核心全回归269P/3F exit1、7.02s，同三个继承ID，au002-continuation-core-final.txt。两份raw日志只去行尾空白，计数及诊断保留。未恢复legacy或删除失败断言。

共享Issuer最后补强后，原配置journal贯通回归 `-m pytest -c plugins/harness/pyproject.toml plugins/harness/tests/test_unit_configuration_records.py plugins/harness/tests/test_unit_records.py plugins/harness/tests/test_operation_journal.py -q`：61P/0F exit0、0.67s。确认原core claim消费/原query及owner journal不受持续重核改动破坏。
### 2026-10-05 AU002 准备前占用原子接缝

开工HEAD5790b5374b24bbf754f1e8a5cc60b32b1ac9beb3，工作树clean；实时代理清单三家均completed，无活跃家族写者。共享工作仍由主会话串行执行。NodePublication.reserve新增显式usages参数，复用原Store.reserve_operation同事务写Node身份、原操作和准备前资源占用；重放只读原预留，不追加占用。没有新数据库、注册中心或原生状态副本。协调方必须将固定资源配方包含在原输入digest，本接缝不替代生产Provider接纳或材料取得。

命令：`/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_preparation_holds.py products/agent-tools/tests/integration/test_node_publication.py -q`。首跑29P/1F exit1、0.49s，冷启动fixture未关闭原writer，正确触发WriterLockHeldError；第二次30P/1 teardown error exit1、0.50s，fixture重复close；修正资源清理后30P/0F exit0、0.46s。新增5项真实SQLite验证：dispatch前持有、错误holder和跨环境target导致身份/操作/Usage整体回滚、重放不追加占用、unknown及冷启动保留原占用且不重复claim。既有Node25项同跑；未删除断言、放宽writer锁或用takeover绕过。

C为真实SQLite受控协调证据；P/M均未运行，本次无第三方安装/更新、用户数据或配置操作、服务重启。生产prepare→Unit→Node、材料/SecretRef、完整使用与生命周期仍未完成，AU002_PARTIAL。此前核心全回归3个已登记失败仍保持，未用本次窄测宣称修复。下一步接固定Profile与当前Registry Provider的准备协调及实际owner证据。

### 2026-10-05 AU002 唯一 Registry 公开发现

开工HEAD84b980f619c6351daacc219fa3694d39799966c5，clean；上一轮是已提交占用接缝进展，本轮继续可行核心工作。新增Environment.agent_runtime_contributions与AgentServices.providers只观察唯一CoreRegistry当前active贡献；公开descriptor/host providerRef不泄漏实例对象，不调用品牌生命周期/安装探测。staged/draining排除，active接纳后篡改拒绝，空Registry仍检查读权限。显式v2 wire绑定既定agents.providers.list/describe并如实加入supportedMethods；默认v1不变，nodes.prepare仍未组成。详见provider-discovery-port.md。

命令 `/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_provider_discovery.py docs/implementation/agent-tools/evidence/agent-unit-model/test_management.py products/agent-tools/tests/integration/test_runtime_admission.py -q`：首跑64P/1F exit1、1.85s，新增测试误用WireError.code，修为既定family；最终65P exit0、2.32s（新发现13、管理31、接纳21）。涵盖公开wire、权限/引用反例、篡改、generation更新及副本隔离；没有修改既有断言。

Environment共享修改后核心全回归同命令 `-m pytest -c packages/backend/pacthold/pyproject.toml packages/backend/pacthold/tests -q`：269P/3F exit1、7.37s，仍已登记test_n4r1_kernel_direction的三个ID，触发源仍是既有核心test_closeout_environment_dispatch导入具体SQLite；没有把全量报绿或移除失败。P/M0，无第三方安装更新、用户服务/登录/数据操作。AU002仍PARTIAL：生产prepare/材料/SecretRef/Unit→Node装配与使用生命周期待接通；发现可用不等于产品可用。

### 2026-10-05 AU002 固定 Profile→Unit→Node 协调检查点（PARTIAL）

开工HEAD740012eeffa17d9e0d70416b51f55c01c13ef3f6，clean；主会话独占共享写权，三家completed成果保留，本轮没有另派家族写者。新增AgentAssembly及两个显式部署观察端口；复用原ProfileCatalog/唯一Registry/同SQLite OperationStore、原Issuer/NodePublication。固定Profile、当前Provider generation、安装/目录来源、epoch与受保护plan摘要后，原prepare/start各claim一次；外部Provider调用在admission锁外。原计划/私有根不写操作日志。准备结论和Unit Usage同事务写，发布时全部原持有Usage转Node。

公开AgentServices.assembly及显式v2 agents.nodes.prepare调用真实协调器；仅所需端口组成时supportedMethods才列prepare，缺席typed拒绝。默认v1不扩展，不谎称默认部署具备Harness。query只核实已claim原步骤，不派发缺失步骤；显式prepare可沿原结论继续未派发步骤或数据发布。旧/失败观察不能覆盖较新revision；并发重放不派发同claim。caller host路径与不符的DirectoryBinding拒绝。未组成C1材料/SecretRef时在claim前拒绝，不将raw resourceRef当材料。详见preparation-coordination-port.md。

验证命令统一解释器 `/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python`。初次 `-m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_assembly.py -q` 13P exit0、0.69s。增加公开服务/wire、材料和原查询反例后，与preparation_holds/provider_discovery/management/Node/runtime六文件112P exit0、3.44s。全products/agent-tools/tests/integration + 五份新增证据（test_assembly、test_provider_discovery、test_preparation_holds、test_management、test_invocation_continuation）初次340P exit0、11.04s；新增并发反例342P exit0、11.28s；读授权343P exit0、11.78s；最终 caller路径/目录反例后同命令346P exit0、11.75s。其中assembly23项，C层真实Profile/Registry/SQLite/Issuer和受控Provider/owner；不是三家实际进程。完整命令：`-m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration docs/implementation/agent-tools/evidence/agent-unit-model/test_assembly.py docs/implementation/agent-tools/evidence/agent-unit-model/test_provider_discovery.py docs/implementation/agent-tools/evidence/agent-unit-model/test_preparation_holds.py docs/implementation/agent-tools/evidence/agent-unit-model/test_management.py docs/implementation/agent-tools/evidence/agent-unit-model/test_invocation_continuation.py -q`。

核心回归 `-m pytest -c packages/backend/pacthold/pyproject.toml packages/backend/pacthold/tests -q` 269P/3F exit1、7.51s，仍同已登记test_kernel_tree_has_no_import_of_server_harness_or_product、test_tripwire_planted_server_import_turns_the_guard_red、test_tripwire_from_import_form_is_detected_too，既有测试导入具体SQLite触发方向扫描；没有删断言/skip/移动测试隐藏红。后续末端改动由346项覆盖，不把窄绿宣称核心全绿。diff-check exit0。P未运行，M0；没有第三方安装更新、用户数据库/凭据/全局配置写入、服务重启、push或主树合并。

剩余：三家prepare返回raw两字段UnitRef，Node公共绑定要求同owner/sourceRevision的完整来源引用，AU003需所属owner统一身份与投影，不能在CLI里补造；生产Context/receipt ports、安装版本与目录/作用权限、原生writer fence、C1材料/SecretRef、三家真实进程/冷恢复和stop/release/access尚未贯通。新协调器是C_READY切片，不是生产接线完成，也不等于AU002_DONE；核心与CLI/Skill/发行边界、AU003–005全部门仍继续。

### 2026-10-05 AU003 原 Unit 公开引用冻结

前置48bf7b159f5eb031bee70a400407e1871ce019a0，clean；实时三家状态completed，原成果已提交保留。AU002共享准备协调检查点后串行进入AU003，主会话仍独占共享接口/journal/Git/账本及验证。UnitReservation.public_ref从原journal immutable来源生成严格owner/source引用，sourceRevision不是native配置/session计数；resolve_unit_reference沿原授权read核实四字段，拒绝raw两字段/伪owner/来源/环境与缺权限。没有新增库或迁移。家族冻结消费说明unit-reference-port.md。

命令 `/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c plugins/harness/pyproject.toml plugins/harness/tests/test_unit_records.py plugins/harness/tests/test_unit_configuration_records.py plugins/harness/tests/test_operation_journal.py -q`：66P exit0、0.73s（新增引用5、原Unit23、配置29、journal9）。覆盖冷读取来源不变、session观察与引用版本分离、嵌套不可变、原授权及伪引用反例。C真实SQLite＋受控authority；P/M未运行。接下来Pi/Codex/Claude各自包独占接入，主会话串行复跑；本冻结不标AU003_DONE。
