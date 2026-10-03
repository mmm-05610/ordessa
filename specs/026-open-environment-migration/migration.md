# 来源、数据与切换协议

## 1 实施源不能只用main SHA

主树与产品树差异包括已验历史恢复、输入/配置修复、清单和未提交测试。工单001必须比较merge-base、commit范围、tracked diff、非忽略未跟踪源码、lock/安装资产引用；记录文件digest。禁止读取/打包key.txt/token/.env/数据库/运行数据/node_modules或系统登录。

推荐在用户批准的实施树建立“产品能力基线”：从批准来源导入已验源码及设计包，保留main新增内容，冲突逐项记录。不得自行认定P全优于M、提交其他人脏文件，或把未经用户批准的cherry-pick当普通文件移动。

必须形成baseline-receipt：source heads、合成SHA、批准范围、未提交源码清单摘要、安装资产只读引用、测试发现/逐ID红账、现有产品验收引用等级。未授权新工作树时只给建议，不创建。旧docs/baseline的固定switch规则与产品来源要求若冲突，先获明确批准，不悄悄改AGENTS。

## 2 数据边界

仅fixture目录可做schema演练。数据根/DB路径/table与迁移编号/extension id/native history id保留。准备独立环境事实schema、source mapping、历史只读decoder；不把领域DB和core.sqlite强合。真实迁移需提交具体schema差异、备份恢复、空/历史/WAL/损坏处理后获许可。

backup须SQLite备份API或可靠停写snapshot，不能只copy .db忽略WAL。测试WAL未checkpoint写入可见；空目录不是旧库，缺marker/未知schema不能初始化覆盖。

## 3 单writer切换

controlled切换先freeze该部署新准入，不中断运行；清点旧active/unknown/Usage/创建attempt；未知原关系固定保留并交继续者；新Environment接手能力和请求入口；旧入口仅转同实例，旧终态表成为只读历史。

不得双写比较；可以shadow计算只读派生比较但不调用native/写状态。Server transport mount和Environment publication同revision对应，失败不留下半route。

live切换需要服务操作许可。若旧运行无法收尾且仍需旧实现，则保留其明确历史/closure作用域，不允许它接新业务。不能两个writer争同请求/对象。

## 4 回退分类

外部效果包含激活时创建资源、实例创建、配置应用与控制答复，不仅input-send。零效果必须有所有相关所有者证据；未知也越过effects fence。详细强制顺序见 contracts/recovery.md。

- 未切调用/无新外部效果：可切回已验证装配/源码快照，保fixture证据。
- 已新派发：先关新准入，保Store/spent key/unknown/closure。仅回退到兼容新事实的实现或只读模式，禁止旧writer重放。
- 已真实schema迁移：按获批恢复方案处理；备份恢复不能倒退已经发生的外部效果。运行/credential数据不随git revert处理。
- key不可取/轮换不兼容：可靠入口拒绝，原unknown保留；显式raw仍可但不能自动重发原unknown。

## 5 兼容退役台账

逐entry记录old specifier/ID/API、消费者、唯一新实现、保证等级、测试ID、截止工单。允许仅必要公开facade，不允许旧目录运行实现/新旧registry/业务反向export。012清除zero-consumer适配；有外部使用者的公开入口不无授权破坏，记录版本兼容在新包exports。
