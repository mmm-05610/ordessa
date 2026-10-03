# E5 — 同一Environment内的持久资源关联

R4补齐E3资源依赖语义。不是独立引用总线/核心，不扫描插件payload。002冻结合同，004实现同关系准入，005持久化/崩溃证据，007迁资源消费者，012完整回归。

## 三种关系不能混淆

- Usage：当前调用/实例/激活正在使用，按其scope收口。
- PersistentReference：已保存对象版本声明的资源关系，插件停用仍保留。
- HistoricalAssociation：过去发生的只读关联，不自动阻新操作或获得调用权。

引用源与目标使用中性稳定资源键（CanonicalFactTarget + revision选择器），不是短命socket或可执行ObjectRef代次；解析实际invoke仍须当前Binding。源插件声明关联性质/版本绑定/保留规则，目标插件声明哪些变更可能破坏该性质；核心不理解providerId/modelId/Skill。

PersistentReference字段：relationId、sourceKey/sourceRevision、targetKey/revisionSelector、declaringOwnerDomain、policyContractId/version、operationId、sourceCommitEvidence、status、coverageEpoch。状态prepared/published/withdrawn/unverified，retire activation不撤published。owner实现停用不等ownerDomain数据消失。引用不是权限，不转移secret读取权。

## 登记与反查

publishReferenceSet(sourceKey,sourceRevision,relations,operationId)完整替换该源版本的声明集合，版本和operationId幂等，未知不重做业务写。按统一调用合同登记意图，取得关联准入reservation后由领域提交源数据，再交付可信commit evidence使published；失败确认零效果才撤prepared。外部提交未知保留潜在关联阻塞，不能空集假安全。

inspectIncoming(targetKey,changeKind,coverageEpoch)返回关联和完整性known/unknown，不扫描业务库。已有保存内容需源插件显式导出关系并按版本证明索引覆盖；停用插件的已登记关系仍可读，未登记或缺恢复证据标coverage unknown。核心维护声明覆盖登记，不把缺扫描者当“无引用”。不承诺自动发现偷偷绕过合同写入的外部数据。

## 变更准入与竞态

prepareResourceChange(targetKey,expectedRevision,changeKind,operationId)在同一Environment准入门检查声明覆盖、目标变更合同、runtime Usage与冲突关联，生成ChangeReservation。新引用与该reservation在同门串行化；拒冲突新关联，不能先query空列表再无保护delete。没有声明强一致边界的外部存储只支持observational保证，需要强保证时typed unsupported。

核心只按版本化合同声明的关系/变更兼容性规则校验，不能执行品牌/资源业务解释器或替目标决定归档语义。目标owner给出允许的变更描述和证据；archive可能仅禁新选用、delete可能破坏固定版本，二者不能被核心统一当destroy。业务策略不允许静默修改已有记录来求过门。

变更已接纳后归Activity，reservation不能因UI关闭/TTL/进程死自动当已释放。跨关系Store与领域库不承诺事务原子：intent→领域效果→结果确认；effect unknown保留gate及恢复关联，只核对原operationId。C2同根writer与恢复fence沿用，无强证据不得强接管/解锁。普通读取或不破坏关联的操作可以继续，不能锁整个环境。

## 去实现依赖和敏感性

历史读取/反查不要求source插件活着；公共中性记录保relation身份和安全引用，不存源内容/秘密。领域decoder缺席只读描述或明确无法解释，不拿此授予删除权。SecretRef适用同一机制，但秘密用途、版本与真正删除由SecretPort合同决定。

依赖存储缺席，内存资源可声明non-durable关系；需要跨重启完整性保证的路径拒绝，不能静默降级。显式purge用户数据须另授权，不借插件卸载自动清关系。

## 强制反例

保存Profile后停用Profile插件，引用仍阻有破坏性的Provider变更；其他资源插件声明同样关联无需改内核。注入引用保存与归档并发，最多合法一侧通过，不得同时破坏完整性。源数据已写/关系确认丢失、索引覆盖未知、reserve后崩溃、版本升级缺decoder均不得报无引用或自动重发。重启核对完整证据后可推进，保原operation关联。
