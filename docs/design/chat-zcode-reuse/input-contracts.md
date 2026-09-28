# Chat v2 输入契约与数据模型

本文件冻结语义，不捏造集成基线不存在的 Token。编译级 API 在 S0/S1 按真实服务声明落定；不得同时保留两套等价注册表。

## 1. Chat 自有菜单注册

在 ChatContributions 同一个 scoped API 下增加 `addInputSource`，不是 UI 平台新增业务 slot；原六个 UI 位置继续有效。菜单条目是结构化数据，不要求每行注册一个 UiComponentKey。

```ts
type InputEntryAction =
  | { kind: 'insert-command'; text: string }
  | { kind: 'add-content'; prepare: ScopedAction }
  | { kind: 'invoke'; execute: ScopedAction };
type InputEntry = {
  id: string; title: string; description?: string;
  groupId: string; order: number;
  surfaces: readonly ('plus' | 'slash')[];
  availability: { kind: 'ready' } | { kind: 'disabled'; reason: string };
  action: InputEntryAction;
};
```

`ScopedAction` 必须使用 C7 的真实动作机制/上下文 guard，以上为示意，不新增万能函数调用协议。来源和 scope 由宿主授予，不能自填 owner。source/query 返回只读条目（来源、条目 ID 唯一），查询输入含 ChatLocation、query、surface、AbortSignal；返回取消不等于业务取消。query 无副作用，不创建会话/通道，不扫描整个磁盘。每个来源可独立 loading/error/ready；按 group order/id、item order/id 稳定排序。

选择时重新验证 contribution generation + location revision + 条目可用性；异步结果绑定原草稿与内容版本。卸载取消 UI 查询并撤条目；已发出的业务动作不伪称取消。两来源同 ID 拒绝，同标题保留来源区别。不把整段草稿/历史作为查询上下文泄露。

insert-command 只替换当前 / token，保留前后文本，定位已变则拒绝旧插入；plus 入口插入到其捕获的有效光标。add-content 返回经过校验的输入引用交给 Chat 草稿，不能直接写 Chat store；invoke 执行来源自身公开能力，不自动发送消息。目录/文件选择、Skill 引用均走这一分类，不向所有插件开放 beforeSend。

原生命令目录由会话/Harness 公开服务提供，按具体目标取数。无目录时本地插件菜单仍可工作，缺席来源不显示假命令。未知原生文本是否被执行仍由对端裁定。

## 2. Draft 与发送快照

Draft：稳定 draftId、项目/服务身份、可选 Harness 选择、text、inputItems、revision。不得另建后端 session store。InputItem 有稳定 id、来源、display metadata、kind 与服务拥有的不透明内容引用；本地预览 URL 不进入协议。

单附件 UI 状态：selected → preparing → ready，失败到 failed；retry 回 preparing；remove 终止当前 UI 代次。发送快照记录 target、draftId/revision、文本与明确附件 id 集合、submission id。用户后来新增/编辑的内容不属于该快照。

提交结果至少要区分 accepted/refused/unknown；如现有服务只有 Promise<void>，必须在服务适配阶段说明其可证实语义并补可判定结果，不把 Promise resolve 凭空解释成执行完成。unknown 不自动清草稿/重新创建 session/重复上传提交。

## 3. 所需服务面（实现必须复用真实所有者）

| 能力 | 输入/结果语义 | 归属 |
| --- | --- | --- |
| 项目列表/创建/重验证 | 服务身份、项目 id、路径权限与错误；缺接口显式缺席 | 现有 Workspace 业务服务 |
| 原生命令目录 | target→commands/loading/error/capability；条目来自当前对端 | 会话/ACP 投影服务，品牌差异归 Harness |
| 输入能力 | target→支持类型/大小/数量/路径引用能力 | 会话服务汇总对端权威数据 |
| prepare content | target+内容+幂等键→不透明 ref；取消/清理有所有权 | 现有资源传输服务；缺失先设计最小接口 |
| submit | 明确目标+text+refs+submission id→接受结果 | 现有会话服务，适配到 ACP/目标协议 |
| native picker/安全读取 | 用户选择的授权资源，不是任意路径读取 | 现有平台桥；禁止把 Node fs 带进 renderer |

本批不得新增广义资源微内核。若这些能力在当前树缺失，只补公开服务与相应插件适配；品牌实现属于 Harness，UI 不包含品牌 if 分支。涉及平台/后端写入必须按 plan 的范围门先获得明确派发，不暗改宿主。

## 4. 替换组件兼容

Composer key 的完整 v1 应同时覆盖受控文本、内容项、附件操作、建议面板呈现/动作、toolbar 和发送/停止状态；公开前补类型正反例。若既有 key 已发布，按平台版本规则演进，不能原地增加必填 props 破坏提供者。默认 Composer 替换不替换草稿/上传/会话服务所有权。

## 5. 信任与资源约束

文件内容不执行；文件名/路径/Markdown 都按不可信内容渲染；预览不自动拉远程 URL。远程内容上传须通过既有认证传输，不记录凭据/base64 到诊断日志。受控失败含体积超限、权限拒绝、断连、取消准备、旧目标返回、重复响应、接受结果未知。UI provider fallback 不允许悄悄丢待发附件。
