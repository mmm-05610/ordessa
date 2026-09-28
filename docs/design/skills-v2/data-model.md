# Data model and resolution

## 内容与版本

```text
SkillRecord: serverScope, assetId, nativeName, description, originScope,
             originOwner, source, latestInstalledRevision, archived
SkillRevision: assetId, revision, treeDigest, fileManifest, declaredMetadata,
               retainedMetadata, scriptManifest, sourceCommit, approvalRecord
SkillAssignment: serverScope, principal, scopeKind, scopeId, harnessId | any,
                 assetId, decision: enable | disable, revision? , rowVersion
ResolvedSkill: assetId, revision, nativeName, treeDigest, originScope,
               selectedBy, excludedBy?, capabilityEvidence
SkillSnapshot: targetSession, runtimeGeneration, projectId, profileRevision,
               assignmentRevisions, resolvedSkills, snapshotDigest
```

`assetId` 是业务唯一身份，不能用相同 nativeName 合并内容。`originScope` 决定谁可选：公共库可用于已授权项目；项目专用仅该 projectId；Profile 专用仅该 Profile。Profile 的 harnessId 固定，不允许跨 Harness 使用 Profile 专用项。

分配引用版本必须为已经安装、校验并批准的 revision。`enable` 记录 revision；`disable` 不要求 revision；未出现的项即 inherit。新版导入只更新 latestInstalledRevision，不改任何 SkillAssignment。历史会话 snapshot 固定每个 digest。更新已启用范围时明确挑选目标修订并写 CAS/操作键；重试不能重复升级。

## 解析顺序

对每个可见 assetId，从低到高读取：

```text
user-global/any → user-global/harness
→ project/any → project/harness
→ profile → session override
```

一层无条目即继承；`enable(revision)` 覆盖之前的状态/修订；`disable` 排除；重复同层同 assetId 拒绝。一份 Skill 在全局启用、项目禁用后，Profile 可再次显式启用，但必须指向获准修订并仍满足管理员政策。Profile 只属于自己的 Harness；会话临时选择下一次提交生效，不能永久回写 Profile。

所谓“全局”是当前 principal 在当前 Server 数据域的默认分配。若将来要组织/机器强制安装，须用单独管理政策层，不纳入这套可覆盖三态。项目身份来自 Workspace 已授权的稳定 ID 和服务器校验的根，不靠任意客户端路径字符串匹配。

解析返回有效项、排除项来源、冲突/缺席诊断和实际修订；前端使用同一只读解析服务预览。单事务读取本域各分配版本，再与 Profile 解析结果组成冻结 snapshot；跨业务 DB 无伪造原子性，应用时校验双方修订/权限。内容安装后的远端更新不进入 snapshot。

## 原生发现项与命名冲突

`NativeDiscovery` 是按目标 runtime/version/cwd 限定的只读观察：nativeName、发现位置类别、来源证据、可否精确屏蔽。它不是 SkillRecord，也不会自动复制其正文到 Ordessa。

受管集合中的 nativeName 重名：不同 assetId 即拒绝装配，不以大小写、目录顺序或“最后覆盖”私自选胜者；比较规则按目标 Harness 的真实名称规则。与原生发现项撞名时同样拒绝或使用已验证的原生命名空间机制；不能只藏起原生项再记为“受管项已装载”。

原生项可能在实例启动后从项目路径再被发现。若不能在私有运行环境中可靠控制发现范围，那么全局/项目/Profile 的 `disable` 只能约束**受管**项；对未管原生项明确显示“无法由 Ordessa 关闭”。如果用户要求确切有效集合且发现路径不受控，则应用拒绝隔离不成立，不能宣称本会话只有所选 Skill。

## 存储升级

现有 `server_assets` 含 skill/mcp/command/plugin 历史 kind；Skills 迁移只获得 skill 行，不改其他 kind 的归属。`server_profile_assets` 现有固定修订绑定保留；把它转成 Profile `enable(revision)` 的迁移必须有字节/ID 样本和回滚验证。`tree_digest` 拼写和内容算法不静默改变。

实体不因取消分配、卸载前端或归档 Profile 而删除。运行实例持有旧 revision 时不清理该目录。远端源的 URL/commit 保存作来源，正文与脚本仍以已批准本地 revision 为准；下载更新只是候选版本。
