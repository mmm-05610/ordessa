# C7：通用 UI 组件提供与消费 v1

状态：待审的公开契约。代码块是拟定签名，不声称已可导入。

## 1. 归属与入口

包：`packages/desktop-platform/ui-components`。

- `@ordessa/ui-components/api`：key、服务 Token、只读绑定类型；无实现激活副作用。
- `@ordessa/ui-components/react`：`ComponentOutlet`、`useUiBinding`、`guardUiAction`；无领域组件。
- 实现/装配入口：仅产品/宿主装配调用 `createUiComponentsPlugin(selection)`，产生一个普通 Lumino 服务插件。业务插件不调用此入口。
- 服务 ID 建议 `ordessa.ui-components`，服务 Token `UiComponentsToken`；新 ID 无旧标识迁移。

继续使用现有 `provides/requires`、`ResourceScope`、`IDisposable`。这个包维护 UI 贡献集合，不取代 Lumino，也不提供任意业务服务查找。消费者依赖 UiComponentsToken；不硬依赖具体 Agent UI 提供者，所以提供者卸载不会连带卸载 Chat。

## 2. 核心类型

```ts
interface UiComponentKey<P> {
  readonly id: string;                  // 领域拥有，例如 ordessa.agent-ui.composer
  readonly major: number;               // 正整数，破坏性变化升 major
  // 工厂内部保存实例身份和 P 的不变型品牌；调用方不能手工构造
}
declare function defineUiComponent<P>(id: string, major: number): UiComponentKey<P>;

interface UiImplementation<P> {
  readonly key: UiComponentKey<P>;
  readonly providerId: string;          // 当前接口下唯一的实现贡献 ID
  readonly component: React.ComponentType<P>;
}
type UiAvailability =
  | { readonly status: 'ready'; readonly providerId: string; readonly generation: number }
  | { readonly status: 'missing'; readonly reason: 'unselected' | 'provider-unavailable';
      readonly selectedProviderId?: string }
  | { readonly status: 'disposed' };

interface UiBinding<P> extends IDisposable {
  readonly key: UiComponentKey<P>;
  getSnapshot(): UiAvailability;
  subscribe(listener: () => void): () => void;
  // 组件实现保存在私有状态中，不向消费者暴露 Component 以绕过撤销检查
}

interface UiComponents {
  forScope(scope: ResourceScope): {
    register<P>(implementation: UiImplementation<P>): IDisposable;
    registerBatch(items: readonly UiRegistration[]): IDisposable;
    bind<P>(key: UiComponentKey<P>, options: { required: boolean }): UiBinding<P>;
  };
}
// UiRegistration 为不透明句柄，内部擦除泛型，不允许调用方手工构造。
declare function registration<P>(
  key: UiComponentKey<P>, providerId: string, component: React.ComponentType<P>
): UiRegistration;
// 不向调用方暴露 UiImplementation<any>[] 以规避 props 类型检查。
```

`ResourceScope` 是宿主发出的生命周期句柄。注册/绑定自动加入该 scope，提前 dispose 也幂等；内部以 scope 身份记录所有权，不信任调用方提供的 owner 字符串。注册句柄无撤销别人贡献的 API。scope 已关闭时同步拒绝注册与绑定。

key 在领域 API 中只构造一次。平台通过本宿主的 `(id, major) → 对象身份` 表检出同名不同实例，返回 `UI_KEY_IDENTITY_CONFLICT`；不合并它们。key 类型对 P 不变：错误 props 的组件不能冒充正确实现。React、平台 API、领域 API 均须遵循共享模块构建映射。

v1 按 major 精确匹配；同 major 只能做兼容扩展，新增必填 props 必须升 major。已安装但不同 major 的提供者不匹配，也不自动转换数据。单实例身份检查表在宿主销毁时清空，不建跨窗口全局注册表。

## 3. 产品选择与装配

```ts
type UiSelection = readonly {
  readonly componentId: string;
  readonly major: number;
  readonly providerId: string;
}[];
```

产品配置保存选择；宿主只处理通用字符串和版本。装配入口复制并冻结它，校验重复 `(componentId, major)`。默认产品显式选择本批需要且已经实现的组件，用户的完整产品清单覆盖规则保持现状。不能由 provider 调 `setDefault()`，不能通过加载排序抢占。提供者实现仅在所选 Outlet 中挂载，登记本身不得 mount、联网或修改业务配置。

装配工厂同时返回普通服务 plugin 和产品侧的 `inspectRequirements(): readonly UiRequirementDiagnostic[]`；后者只列 required binding 的缺项（componentId、major、selectedProviderId、reason），不暴露实现或业务 props。这是产品侧检查入口，不在 UiComponentsToken 消费面开放。`createUiComponentsPlugin` 的完整返回值为 `{ plugin, inspectRequirements }`。产品把 plugin 放入现有 runtime 的插件数组；激活完成后检查缺项并接到既有 diagnostics。没有必需绑定时返回空数组。初次报告不代替实时快照，随后缺席由对应 Outlet 如实呈现。

UI 服务在领域插件激活前提供。消费者可先 bind，初始 missing；选定提供者登记后变 ready，顺序不影响结果。宿主激活完成后运行通用必需绑定诊断，区分未选择和选定者不可用；失败插件的激活错误由既有宿主报告，不虚构为接口版本问题。使用者所需 major 未找到时也是 provider-unavailable，诊断可附所见 major，不能自动兼容。

注册批：校验所有 key 身份、providerId、重复项与 scope 状态，通过后一次发布；任一项失败，整个新批次零发布。既有注册不受影响。不同 providerId 可以同时登记；同 key/providerId 的第二项一律拒绝，即使旧项未被选中。实现替换必须先撤销旧项再登记新项。

生成代次由宿主单调分配。原句柄 dispose 只撤销自身那代注册，不能删除同 ID 的新实例。全部订阅者看到一致的提交后快照，未变化的 getSnapshot 返回同一对象，兼容 useSyncExternalStore。单个订阅者抛错不得打断提交或阻止其他订阅通知；错误经诊断通路报告。

## 4. 渲染与动作

```ts
interface ComponentOutletProps<P> {
  binding: UiBinding<P>;
  value: P;
  missing?: React.ReactNode;    // required 默认给通用提示，optional 默认 null
}
declare function ComponentOutlet<P>(props: ComponentOutletProps<P>): React.ReactElement | null;

type UiActionResult =
  | { status: 'accepted' }      // 业务接纳操作，不等于操作已完成
  | { status: 'refused'; message: string }
  | { status: 'unavailable' }; // 消费者/提供者/对应代次已失效
type UiAction<I> = (input: I) => Promise<UiActionResult>;
declare function guardUiAction<P, I>(binding: UiBinding<P>, action: UiAction<I>): UiAction<I>;
```

`useUiBinding` 订阅 availability。受保护动作必须在 ready 代次下创建：其闭包固定消费 binding、provider generation；点击时再次检查，两者已失效则返回 unavailable，零业务调用。missing 时创建的动作始终不可用，ready 后消费者重新创建。新 provider 激活不能使旧动作复活。

发送、停止、审批、删除和应用配置等副作用必须通过受保护动作；纯本地展开/折叠可在组件内。同步文本编辑回调由消费者在调用前同样核对 binding/代次，平台应提供同步 guard 变体，拒绝时不调用原回调；其签名为 `guardUiCallback<P, A extends readonly unknown[]>(binding, callback: (...args: A) => void): (...args: A) => void`。这不是权限验证，Server/领域服务仍做自己的权限和状态检查。

动作开始时通过检查后，后续卸载不会取消已接纳工作。异步结果只能更新消费者拥有的业务 store，不得调用已经卸载的组件 setState；消费者组件内的局部状态使用自身卸载/代次保护。组件不能自行把 accepted 渲染为“审批已批准”或“消息已完成”。

Outlet 以 provider generation 作为实现子树 identity：代次变化重新挂载。提供者撤销时注册表同步失效，React 下一个提交移除旧 DOM；这个短窗口内旧回调也已失效。业务 UI 状态需受控以保留草稿；内部折叠/滚动允许重置。组件卸载不调用 channel.close、execution.stop、session.release。

## 5. 错误与可访问性

- required 缺席：可理解的提示与宿主诊断，不白屏；optional 缺席：不占位。是否 required 是 binding 的固定属性。
- 渲染错误：每个 Outlet 独立 ErrorBoundary，显示该位置出错；其他位置继续。同一 provider 可在其他位置正常渲染。新代次自动清除该位置错误；同代次只有显式重试才能重置，禁止无限自动重试。
- ErrorBoundary 不捕获事件/Promise：动作包装器捕获并报告异常，转为通用 refused 文案；诊断保留经清洗的原因。业务自报 refused 的 message 必须已经适合展示。
- 诊断只含组件 ID、provider ID、代次、错误码和清洗后的摘要，不打印 props、聊天内容、附件、完整 URL 或凭据。
- 通用错误码：`UI_SCOPE_CLOSED`、`UI_KEY_IDENTITY_CONFLICT`、`UI_PROVIDER_DUPLICATE`、`UI_SELECTION_DUPLICATE`、`UI_RENDER_FAILED`、`UI_ACTION_FAILED`；ready/missing 是状态，不伪造异常。v1 不暴露修改 selection 的方法；不得通过修改传入数组影响已冻结实例。
- 替换实现必须保留接口规定的键盘与 ARIA 行为。模态、焦点圈和全局浮层继续调用 Workbench/平台，不另建覆盖层。

## 6. 实现限制

不能公开“取得任意组件函数”的全局 API。一个消费绑定是一个可撤销引用，并非执行租约；不与 Pacthold 的运行状态挂钩。提供者为受信任前端扩展，平台不声称阻止恶意组件直接访问浏览器能力。

产品重新装配可选 B；旧宿主先完成正常 UI 清理，再创建新宿主。重建前端不应隐式终止后端工作，需沿用现有连接/会话恢复规则。v1 不提供在线切换 selection 的按钮或管理服务。
