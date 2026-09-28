# UX：设置、Profile、会话

设置页“模型与服务”是管理器，不是全局当前模型开关。一级 Harness，二级 ProviderConfig，同一配置详情包含认证方式（使用既有登录或凭据引用）、端点/品牌参数、模型目录、来源证据与“保存 / 手动测试连接 / 手动拉取模型”。对登录来源标“由 Harness 管理”并按能力限定编辑；自建配置标“由 Ordessa 保存”。保存成功仅示“已保存”，探测成功仅示“最近可达”，当前会话资格按实证单独显示。页面载入不请求模型端点；探测按钮需说明会发送一个受控请求，不发送 prompt。密码输入只通凭据设施，不在这个表单里回显明文。

Profile 编辑页用 `assets.model-provider` 的选择器保存默认 `(providerConfigId,modelId)`；该 Profile 属于固定 Harness，选择列表只列对应配置。更新这个 Profile 的模型 item 不强改当前正输出的轮次；会话已有模型 item 覆盖时它仍保持，其他 item 按 Profile 最新修订。无 Profile 时仍能直接选模型，不自动创建隐形 Profile。

Chat composer 底部用紧凑 `Provider › Model` 选择器，**不显示 Harness 下拉**。打开按 ProviderConfig 分组，模型行显示 `可在此会话下轮使用 / 不支持原因 / 未证实`；不可选项可查看解释但不可提交。选择只是队列：若正在输出，它继续；用户下次输入时先应用后发送。用户不必看到常驻“当前/待生效/有修改”三标签。必要时在选择器/失败浮层显示“下轮使用”与“仅此会话”。选择失败保留输入草稿，并给“检查配置/重新核对”操作；Unknown 不给“重发消息”捷径。显式恢复跟随 Profile 等价清此 item 覆盖，受下一轮闸门约束。

设置页及选择器复用 Workbench 设置容器、平台 UI overlay/表单/焦点处理；缺 UI contribution 就隐藏该区、不留破损占位，后端数据仍在。宽屏列表/详情双栏，窄屏列表→详情；键盘搜索、箭头、Enter、Escape 与焦点返回需测试。异步 catalog/providerId/Server 切换时迟到结果不得替换当前面板。无可用 Provider 不显示假默认模型，可允许“使用 Harness 当前默认”路径继续基础对话。
