# Data model

## 主体

```text
PromptRecord
  id: opaque stable ID
  kind: instruction | persona | system-replacement   # 创建后不可改；换用途用复制
  scope: library | profile(profileId)
  title, description, archived
  metadataVersion, latestRevision

PromptRevision
  promptId, revision, bodyUtf8, sha256, createdAt

PromptRef
  promptId, track: latest                          # 首版不提供用户 pin 选项

ResolvedPrompt
  promptId, kind, revision, sha256, bodyUtf8

PromptSelection
  instructions: ordered PromptRef[]
  persona: PromptRef | null
  systemReplacement: PromptRef | null

PromptSnapshot
  snapshotId, serverScope, profileRevision, overlayRevision
  resolved ordered content, source metadata versions, adapter version
  contentDigest, compositionVersion
```

记录和授权均限当前 Server 数据域。profileId 是引用而非反向 import Profile 的 DB。资源身份是 serverScope+id，不能把不同 Server 同名/同 ID 内容互换。

## 首版限制（产品默认，非上游能力声称）

- 标题 1–160 Unicode 字符，说明最多 2,000 字符；允许同名，选择器有说明/短 ID 消歧。
- 正文 UTF-8，拒绝非法编码、NUL、纯空白；单份最多 128 KiB，最多 32 份补充指令。
- 一个解析快照总正文最多 1 MiB；目标原生上限更小时必须在应用前拒绝，不能静默截断。
- 不做隐式换行/Unicode 正规化或 trim 正文；导入 UTF-8 BOM 可仅剥离开头 BOM 并告知，正文摘要基于最终保存字节。UI 不承诺二进制原样 round-trip。
- 元数据与修订存于插件自有 SQLite schema；正文小且有上限，首版同库事务保存，避免无必要的文件+数据库双事务。原生临时文件归 Harness。
- 内容修订永不就地修改。恢复旧版是基于旧正文创建新修订；不倒退 latestRevision。

## 更新、复制和归档

更新携带 expectedMetadataVersion/expectedLatestRevision 与幂等键。相同正文保存不制造新内容修订，元数据变化仍更新版本；并发不 last-wins。

复制生成新实体+首修订，复制当时正文而不是跟随原实体未来修改。Profile 专用内容不跨 Profile 引用；用户可显式“复制到内容库”创建独立公共实体，无静默提升 scope。

归档过滤新选择列表，但已有引用仍解析 latest；归档后内容只读，先恢复再编辑。用户从 Profile 取消选择不删除实体。首版无 hard-delete/GC；历史 revision 和已冻结快照保留。Profile 被归档/删除不级联删正文，专用内容按授权显示为所属 Profile 已停用，显式恢复/复制处理。

## 保存 Profile 内联草稿

采用明确两步，不引入跨插件内容创建事务：内容弹窗的“保存内容并选用”先创建内容，再把引用填入 Profile 页面 draft；随后“保存 Profile”才保存绑定。按钮旁说明“内容会单独保存，Profile 尚未保存”。未点内容保存就取消不产生记录；之后取消 Profile 保留已显式保存的内容，可从该 Profile 的专用内容列表找回，不暗中删除。

创建请求超时用同一 operationKey 查询/重试，不能再建一份。Profile 尚未有持久 ID 时先保存基础 Profile 才可建专用内容；不捏造临时 profileId，不自动改成公共内容。修改既有公共正文同样是独立保存，Profile 取消不能撤销它；编辑器明确显示共享影响，不增加每轮会话的确认弹窗。

## 快照与覆盖

Prompts 在一个只读事务中解析该次请求所有 latest，返回确切 revision+正文。Profile 已先冻结选择项；Harness plan 绑定该快照，不在 apply 时再次追 latest。之后正文改动只影响下一次提交；授权/所有者卸载等安全条件仍须应用前重查。

Profile 的 instructions 是一个有序列表 item：会话覆盖该列表就屏蔽 Profile 对此 item 的更改，不做未经定义的逐列表元素 merge。persona/systemReplacement 为另两个 item，各自覆盖独立。latest 跟随的是内容实体修订，不是 Profile item 值：即便会话覆盖选中了某个引用，该引用仍默认追最新正文；需要固定内容时复制出独立实体。快照始终固定，不受以上后续更新影响。
