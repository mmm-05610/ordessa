/**
 * The Profile-editor Skill section (T10 / G15, ux.md §Profile 编辑器).
 *
 * Self-contained and mount-ready: it consumes only the injected `ProfileHost`
 * port (the editor's own state) and the profile gateway (the published
 * `skills.*` family). Z1's real editor slot (§G6) is not published yet, so
 * nothing here registers itself — when the slot lands it mounts THIS
 * component and passes its host; until then tests inject a fake. Removing the
 * contribution removes only UI: this component writes nothing on unmount and
 * stored assignments stay with the host (G15 「旧贡献卸载只摘 UI」).
 *
 * Wording discipline: every effect sentence goes through `effect-text.ts`
 * (`effectText` grades with `attest()`), so no state of the projection can
 * render 已装载/已启用 here. The DTOs carry no host path and no secret, so
 * none can be echoed (ux.md §原生发现和错误).
 */
import { useEffect, useRef, useState, useSyncExternalStore, type ChangeEvent, type KeyboardEvent } from 'react'
import type { ProfileSkillsModel, ProfileSkillsSnapshot } from './profileModel'
import { deriveAssetId } from './profileModel'
import type { ProfileSkillRow } from '../../contracts/src/profile'
import { styles, useNarrow } from './styles'
import { decisionText, effectText, originBadge, resultText, scopeText } from './effect-text'

/** Stable id for the future Profile-editor slot (api-requests.md §G6). */
export const PROFILE_SKILLS_SECTION_ID = 'ordessa.skills.profile.section'

export function useProfileSkillsSnapshot(model: ProfileSkillsModel): ProfileSkillsSnapshot {
  return useSyncExternalStore(model.subscribe, model.getSnapshot)
}

export function ProfileSkillSection(props: { model: ProfileSkillsModel }) {
  const snapshot = useProfileSkillsSnapshot(props.model)
  const narrow = useNarrow()
  useEffect(() => { void props.model.refresh() }, [props.model])
  return (
    <section
      className="skills-settings" data-testid="profile-skill-section" data-narrow={narrow ? 'true' : 'false'}
      aria-label="Profile Skill 设置"
    >
      <style>{styles}</style>
      <h3>Skills（Profile：{snapshot.profile?.profileId ?? '未读取'} · 固定 Harness：{snapshot.profile?.harnessId ?? '未读取'}）</h3>
      {snapshot.profile?.archived ? (
        <p role="status" data-testid="profile-archived">此 Profile 已归档：本区只读，分配与内容保留，不会删除任何已导入内容。</p>
      ) : null}
      {snapshot.error === null ? null : <p role="alert" data-testid="profile-error">{snapshot.error}</p>}
      <TwoSourceNote snapshot={snapshot} />
      {snapshot.layerStatus === 'unavailable' ? (
        <p role="status" data-testid="profile-layer-unavailable">
          Profile 层暂不可读（后端 facet 接缝 §G3 未接线）：下表的“继承”是未确定状态，不代表已禁用；最终结果待解析。
        </p>
      ) : null}
      {snapshot.effectiveStatus === 'unavailable' && snapshot.layerStatus !== 'unavailable' ? (
        <p role="status" data-testid="profile-effective-unavailable">有效集合暂不可解析（后端 Profile 层接缝未接线）；本层设置仍可查看，最终结果待解析。</p>
      ) : null}
      <ProfileConflict model={props.model} snapshot={snapshot} />
      <ProfileRows model={props.model} snapshot={snapshot} narrow={narrow} />
      <ProfileActions model={props.model} snapshot={snapshot} />
      <ProfileImportArea model={props.model} snapshot={snapshot} />
    </section>
  )
}

/** 双源说明 (the panel the review asked for): which column reads from where,
 * and which content is whose. */
function TwoSourceNote(props: { snapshot: ProfileSkillsSnapshot }) {
  const privateCount = props.snapshot.rows.filter(row => row.originScope === 'profile').length
  const inheritedCount = props.snapshot.rows.length - privateCount
  return (
    <div data-testid="profile-two-source-note">
      <p>本区两列来源不同：“本层设置”读取 Profile 自己的草稿/已存条目（仅本 Profile 可见，随 Profile 保存）；
        “最终结果”读取 skills.resolve 的有效集合，并给出决定它的范围与固定版本。</p>
      <p>内容两源：Profile 专用 {privateCount} 项（只归本 Profile，公共与项目选择面不出现它们），
        继承内容 {inheritedCount} 项（公共库/项目库，归属标记见行内）。</p>
    </div>
  )
}

function ProfileConflict(props: { model: ProfileSkillsModel; snapshot: ProfileSkillsSnapshot }) {
  if (props.snapshot.conflict === null) return null
  return (
    <div role="alert" data-testid="profile-save-conflict">
      <p>{props.snapshot.conflict.message}（Profile 配置版本 {props.snapshot.conflict.serverConfigRevision}）</p>
      <button type="button" data-testid="profile-conflict-reread" onClick={() => void props.model.reread()}>重新读取</button>
    </div>
  )
}

/** Keyboard row movement, same contract as the settings list: ↑/↓ (+Home/End)
 * move selection and focus together. */
function useRowKeys(rows: readonly ProfileSkillRow[]) {
  const refs = useRef(new Map<string, HTMLButtonElement>())
  const focusRow = (index: number) => {
    const row = rows[Math.min(Math.max(index, 0), rows.length - 1)]
    if (row === undefined) return
    refs.current.get(row.assetId)?.focus()
  }
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    const rowNode = (event.target as HTMLElement).closest('[data-testid^="profile-row-"]')
    const testId = rowNode === null ? null : rowNode.getAttribute('data-testid')
    const current = Math.max(0, rows.findIndex(row => `profile-row-${row.assetId}` === testId))
    if (event.key === 'ArrowDown') { event.preventDefault(); focusRow(current + 1) }
    else if (event.key === 'ArrowUp') { event.preventDefault(); focusRow(current - 1) }
    else if (event.key === 'Home') { event.preventDefault(); focusRow(0) }
    else if (event.key === 'End') { event.preventDefault(); focusRow(rows.length - 1) }
  }
  return { refs, onKeyDown }
}

function ProfileRows(props: { model: ProfileSkillsModel; snapshot: ProfileSkillsSnapshot; narrow: boolean }) {
  const { refs, onKeyDown } = useRowKeys(props.snapshot.rows)
  if (props.snapshot.state === 'loading' && props.snapshot.rows.length === 0) {
    return <p role="status" data-testid="profile-loading">读取 Profile Skill 设置…</p>
  }
  if (props.snapshot.rows.length === 0) {
    return <p data-testid="profile-empty">此 Profile 当前没有可选 Skill；可在下方导入 Profile 专用内容。</p>
  }
  return (
    <table data-testid="profile-assignment-table" onKeyDown={onKeyDown}>
      <thead>
        <tr><th scope="col">Skill</th><th scope="col">本层设置（Profile）</th><th scope="col">最终结果</th></tr>
      </thead>
      <tbody>
        {props.snapshot.rows.map(row => (
          <ProfileRowView key={row.assetId} row={row} model={props.model} snapshot={props.snapshot}
            narrow={props.narrow} setRef={node => {
              if (node) refs.current.set(row.assetId, node)
              else refs.current.delete(row.assetId)
            }}
          />
        ))}
      </tbody>
    </table>
  )
}

function ProfileRowView(props: {
  row: ProfileSkillRow; model: ProfileSkillsModel; snapshot: ProfileSkillsSnapshot
  narrow: boolean; setRef(node: HTMLButtonElement | null): void
}) {
  const { row, model, snapshot } = props
  const readOnly = snapshot.profile?.archived === true || snapshot.layerStatus === 'unavailable'
  const choiceLabel = row.profileChoice === 'undetermined' ? '继承（未确定）' : decisionText(row.profileChoice)
  return (
    <tr data-testid={`profile-row-${row.assetId}`} data-narrow={props.narrow ? 'stack' : undefined}>
      <th scope="row">
        {row.nativeName}
        <span data-testid={`profile-origin-${row.assetId}`}> {row.originScope === null ? '归属未证明' : originBadge(row.originScope)}</span>
        {row.draft === null ? null : <span data-testid={`profile-draft-${row.assetId}`}>未保存</span>}
      </th>
      <td data-testid={`profile-setting-${row.assetId}`}>
        <span role="group" aria-label={`${row.nativeName} Profile 层设置`}>
          {(['enable', 'disable', 'inherit'] as const).map(decision => (
            <button key={decision} type="button" disabled={readOnly} aria-pressed={row.profileChoice === decision}
              ref={decision === 'enable' ? props.setRef : undefined}
              onClick={() => model.edit(row.assetId, decision)}>
              {decisionText(decision)}
            </button>
          ))}
        </span>
        <span data-testid={`profile-choice-${row.assetId}`}>本层：{choiceLabel}</span>
        {row.profileRevision === null ? null : (
          <span data-testid={`profile-pinned-${row.assetId}`}>固定版 r{row.profileRevision}
            <SwitcherButton model={model} snapshot={snapshot} row={row} disabled={readOnly} />
          </span>
        )}
        {row.profileChoice === 'undetermined' ? null : (
          <button type="button" data-testid={`profile-remove-override-${row.assetId}`} disabled={readOnly}
            title="移除覆写 = 恢复继承：只撤销本 Profile 的覆写，不卸载内容，也不是全局禁用"
            onClick={() => model.removeOverride(row.assetId)}>
            移除覆写（恢复继承，不卸载内容、非全局禁用）
          </button>
        )}
      </td>
      <td data-testid={`profile-effective-${row.assetId}`}>
        {resultText(row.effective)}
        {row.effective === null ? null : (
          <>
            <span data-testid={`profile-effective-scope-${row.assetId}`}> · {scopeText(row.effective.selectedBy)}</span>
            {row.effective.excludedBy === null ? null : (
              <span> · 由 {scopeText(row.effective.excludedBy)} 排除</span>
            )}
            <span data-testid={`profile-effect-note-${row.assetId}`}>{effectText(row.effective)}</span>
          </>
        )}
      </td>
      {snapshot.switcher?.assetId === row.assetId ? (
        <td colSpan={2}>
          <SwitcherPanel model={model} snapshot={snapshot} row={row} />
        </td>
      ) : null}
    </tr>
  )
}

/** The trigger keeps focus ownership: opening the panel moves focus into it,
 * closing restores it to the trigger (平台控件焦点恢复, ux.md §原生发现和错误). */
function SwitcherButton(props: {
  model: ProfileSkillsModel; snapshot: ProfileSkillsSnapshot; row: ProfileSkillRow; disabled: boolean
}) {
  const trigger = useRef<HTMLButtonElement | null>(null)
  const open = props.snapshot.switcher?.assetId === props.row.assetId
  const everOpened = useRef(false)
  if (open) everOpened.current = true
  useEffect(() => {
    // Only after the panel has actually been seen does closing pull focus
    // back — a plain mount must not steal it from the editor.
    if (everOpened.current && !open) trigger.current?.focus()
  }, [open])
  return (
    <button
      ref={node => { if (!open) trigger.current = node }}
      type="button" data-testid={`profile-switch-${props.row.assetId}`} disabled={props.disabled}
      onClick={() => void props.model.openSwitcher(props.row.assetId)}
    >
      指定已批准版本
    </button>
  )
}

function SwitcherPanel(props: { model: ProfileSkillsModel; snapshot: ProfileSkillsSnapshot; row: ProfileSkillRow }) {
  const { model, row } = props
  const revisions = props.snapshot.switcher?.revisions ?? null
  const preview = props.snapshot.diffPreview?.assetId === row.assetId ? props.snapshot.diffPreview : null
  const close = () => { model.closeSwitcher() }
  return (
    <div data-testid={`profile-switcher-${row.assetId}`}>
      <p>启用时指定已批准版本（切换前先看差异；批准不移动已有绑定，FR07）：</p>
      {revisions === null ? <p role="status" data-testid="profile-switcher-loading">读取修订…</p> : (
        <ul>
          {revisions.map(option => (
            <li key={option.revision} data-testid={`profile-revision-${row.assetId}-${option.revision}`}>
              r{option.revision} · {option.approved ? `已批准 ${option.approvedAt ?? ''}` : '未批准'}
              {' '}{option.approved ? (
                <button type="button" data-testid={`profile-preview-${row.assetId}-${option.revision}`}
                  disabled={option.revision === row.profileRevision}
                  onClick={() => void model.previewSwitch(row.assetId, option.revision)}>
                  查看差异并切换
                </button>
              ) : (
                <button type="button" data-testid={`profile-approve-repoint-${row.assetId}-${option.revision}`}
                  onClick={() => void model.previewSwitch(row.assetId, option.revision)}>
                  查看差异（批准后需显式确认）
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {preview === null ? null : (
        <div data-testid={`profile-diff-${row.assetId}`}>
          <p>r{preview.fromRevision} → r{preview.toRevision} 差异预览：</p>
          {preview.diff === null ? (
            <p role="status">{preview.error === null ? '加载差异…' : `差异读取失败：${preview.error}`}</p>
          ) : (
            <ul>
              {preview.diff.added.map(path => <li key={`add:${path}`}>新增 {path}</li>)}
              {preview.diff.removed.map(path => <li key={`del:${path}`}>移除 {path}</li>)}
              {preview.diff.changed.map(path => <li key={`chg:${path}`}>变更 {path}</li>)}
            </ul>
          )}
          {preview.diff === null ? null : (
            <button type="button" data-testid={`profile-confirm-repoint-${row.assetId}-${preview.toRevision}`}
              onClick={() => void model.confirmSwitch(row.assetId, preview.toRevision)}>
              批准并按 r{preview.toRevision} 重指（仅此操作会改变绑定）
            </button>
          )}
        </div>
      )}
      <button type="button" data-testid={`profile-switcher-close-${row.assetId}`} onClick={close}>关闭</button>
    </div>
  )
}

function ProfileActions(props: { model: ProfileSkillsModel; snapshot: ProfileSkillsSnapshot }) {
  const dirty = Object.keys(props.snapshot.draft).length > 0 || props.snapshot.importedHere.length > 0
  return (
    <div>
      <button type="button" data-testid="profile-save" disabled={!dirty || props.snapshot.saving || props.snapshot.profile?.archived === true}
        onClick={() => void props.model.save()}>
        保存 Profile 选择（草稿随 Profile 保存）
      </button>
      <button type="button" data-testid="profile-discard" disabled={!dirty}
        onClick={() => props.model.discard()}>
        放弃本区修改
      </button>
      <button type="button" data-testid="profile-cancel-editing"
        onClick={() => void props.model.cancelProfileEditing()}>
        取消 Profile 编辑（仅撤销选择关系，不删除已导入内容）
      </button>
    </div>
  )
}

function ProfileImportArea(props: { model: ProfileSkillsModel; snapshot: ProfileSkillsSnapshot }) {
  const phase = props.snapshot.importPhase
  const readOnly = props.snapshot.profile?.archived === true || props.snapshot.layerStatus === 'unavailable'
  const pick = async (event: ChangeEvent<HTMLInputElement>) => {
    const picked = [...event.currentTarget.files ?? []]
    event.currentTarget.value = ''
    if (picked.length === 0) return
    const files = await Promise.all(picked.map(async file => ({ path: file.name, bytes: new Uint8Array(await file.arrayBuffer()) })))
    await props.model.importPicked(files)
  }
  return (
    <div data-testid="profile-import">
      <h4>Profile 专用 Skill 就地导入</h4>
      <label data-testid="profile-import-pick">
        选择文件导入（内容归本 Profile，选择关系随 Profile 草稿保存；取消 Profile 不删除已导入内容）
        <input type="file" multiple disabled={readOnly} onChange={event => void pick(event)} />
      </label>
      {phase.kind === 'transferring' ? <p aria-live="polite" data-testid="profile-import-progress">传送中 {phase.sent}/{phase.total}</p> : null}
      {phase.kind === 'prepared' ? (
        <div data-testid="profile-import-preview">
          <p>{phase.preview.name} · {phase.preview.description}</p>
          <ul>
            {phase.preview.files.map(file => (
              <li key={file.path}>{file.path}（{file.bytes} 字节）{file.script ? '【脚本——安装与预览均不执行】' : ''}</li>
            ))}
          </ul>
          <p>内容摘要 {phase.preview.treeDigest.slice(0, 18)}…</p>
          {deriveAssetId(phase.preview.name) === null ? (
            <p role="alert" data-testid="profile-import-badname">名称无法形成合法内容 ID，请修正后重导。</p>
          ) : (
            <button type="button" data-testid="profile-import-confirm"
              onClick={() => void props.model.confirmImport(deriveAssetId(phase.preview.name)!)}>
              确认安装（仅保存内容，不改变任何选择）
            </button>
          )}
          <button type="button" data-testid="profile-import-cancel" onClick={() => void props.model.cancelImport()}>取消导入</button>
        </div>
      ) : null}
      {phase.kind === 'committed' ? (
        <p data-testid="profile-import-result">已保存（stored）——内容已入库并标记为本 Profile 专用；这只是存储事实，不代表已装载到任何会话。</p>
      ) : null}
      {phase.kind === 'failed' ? (
        <p role="alert" data-testid="profile-import-failure">导入失败：{phase.message}。旧版本与绑定保持不变。</p>
      ) : null}
    </div>
  )
}
