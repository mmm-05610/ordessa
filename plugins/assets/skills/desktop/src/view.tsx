/** The Skills settings page: 内容库 / 默认启用 / 项目启用 + 原生发现, one entry.
 *
 * Reuses the legacy desktop list/preview content components
 * (`plugins/assets/desktop/src/view.tsx` at 752f148b1b — research-and-reuse.md
 * §桌面列表/预览 keeps the concrete UI content and replaces the registration
 * and the scope views), and the platform Panel/Toolbar/Field/Dialog behaviour
 * through the Workbench seams. No global sidebar and no Assets super-navigation
 * is added (ux.md §Settings).
 */
import { useEffect, useMemo, useRef, useState, useSyncExternalStore, type ChangeEvent, type KeyboardEvent, type MouseEvent } from 'react'
import type { AssignmentViewRow, SkillRecordView } from '../../contracts/src/skills'
import type { LayerKey, SkillsModel, SkillsSnapshot } from './model'
import type { ImportPhase } from './model'
import { styles, useNarrow } from './styles'
import {
  decisionText, effectText, nativeLocationText, nativeMaskText, originBadge, resultText, scopeText,
} from './effect-text'

export const SKILLS_SETTINGS_SECTION_ID = 'ordessa.skills'
export const SKILLS_DETAIL_OVERLAY_ID = 'ordessa.skills.detail'

/** The platform overlay seam (WorkbenchComposition.openOverlay), narrowed to
 * what this page uses. */
export interface OverlayOpener {
  open(id: string, options?: { anchor?: HTMLElement }): { dispose(): void }
}

export function SkillsSection(props: { model: SkillsModel; overlays?: OverlayOpener | null }) {
  const snapshot = useSkillsSnapshot(props.model)
  const narrow = useNarrow()
  useEffect(() => { void props.model.refresh() }, [props.model])
  return (
    <section className="skills-settings" data-testid="skills-settings" data-narrow={narrow ? 'true' : 'false'} aria-label="Skills">
      <style>{styles}</style>
      {snapshot.error === null ? null : <p role="alert" data-testid="skills-error">{snapshot.error}</p>}
      <LibraryArea model={props.model} snapshot={snapshot} overlays={props.overlays} narrow={narrow} />
      <AssignmentArea model={props.model} snapshot={snapshot} layerKey="global" narrow={narrow} />
      <AssignmentArea model={props.model} snapshot={snapshot} layerKey="project" narrow={narrow} />
      <NativeArea snapshot={snapshot} narrow={narrow} />
    </section>
  )
}

export function useSkillsSnapshot(model: SkillsModel): SkillsSnapshot {
  return useSyncExternalStore(model.subscribe, model.getSnapshot)
}

// —————————————————————————————————————— 内容库

function LibraryArea(props: { model: SkillsModel; snapshot: SkillsSnapshot; overlays?: OverlayOpener | null; narrow: boolean }) {
  const { model, snapshot } = props
  const library = snapshot.library
  return (
    <section aria-label="内容库" data-testid="skills-library">
      <h3>内容库</h3>
      {library.state === 'loading' ? <p role="status" data-testid="library-loading">读取内容库…</p> : null}
      {library.state === 'error' ? (
        <p role="alert" data-testid="library-error">
          内容库读取失败：{library.error}
          <button type="button" onClick={() => void model.refresh()}>重试</button>
        </p>
      ) : null}
      {library.items === null || library.items.length === 0 ? (
        <p data-testid="skills-empty">尚无已保存的 Skill。用“导入”选择一个本地目录。</p>
      ) : (
        <SkillsList
          skills={library.items}
          selected={snapshot.selectedAssetId}
          narrow={props.narrow}
          onSelect={assetId => model.selectAsset(assetId)}
        />
      )}
      <SkillDetailCard model={model} snapshot={snapshot} overlays={props.overlays} />
      <ImportWizard model={model} snapshot={snapshot} />
    </section>
  )
}

/** Keyboard list: ↑/↓ (+ Home/End) move selection and focus together, so the
 * cursor never lands on a row the screen reader is not announcing. */
function SkillsList(props: {
  skills: readonly SkillRecordView[]
  selected: string | null
  narrow: boolean
  onSelect: (assetId: string) => void
}) {
  const refs = useRef(new Map<string, HTMLButtonElement>())
  const index = Math.max(0, props.skills.findIndex(skill => skill.assetId === props.selected))
  const move = (delta: number) => {
    const next = props.skills[Math.min(Math.max(index + delta, 0), props.skills.length - 1)]
    if (next === undefined) return
    props.onSelect(next.assetId)
    refs.current.get(next.assetId)?.focus()
  }
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === 'ArrowDown') { event.preventDefault(); move(1) }
    else if (event.key === 'ArrowUp') { event.preventDefault(); move(-1) }
    else if (event.key === 'Home') { event.preventDefault(); const first = props.skills[0]; if (first) { props.onSelect(first.assetId); refs.current.get(first.assetId)?.focus() } }
    else if (event.key === 'End') {
      event.preventDefault()
      const last = props.skills[props.skills.length - 1]
      if (last) { props.onSelect(last.assetId); refs.current.get(last.assetId)?.focus() }
    }
  }
  return (
    <ul data-testid="skills-list" role="listbox" aria-label="已导入 Skill" onKeyDown={onKeyDown}>
      {props.skills.map(skill => (
        <li key={skill.assetId} role="presentation" data-testid={`skill-row-${skill.assetId}`} data-narrow={props.narrow ? 'stack' : undefined}>
          <button
            type="button" role="option" id={`skill-option-${skill.assetId}`} aria-selected={skill.assetId === props.selected}
            ref={node => { if (node) refs.current.set(skill.assetId, node); else refs.current.delete(skill.assetId) }}
            onClick={() => props.onSelect(skill.assetId)}
          >
            {/* Source text and digest only: a desktop path is not in the view
                model, so it cannot be rendered from here either. */}
            {skill.nativeName} · r{skill.latestInstalledRevision} · {skill.source} · {originBadge(skill.originScope)}
            {skill.archived ? ' · 已归档' : ''}
            {skill.updateCandidateRevision === null ? '' : ` · 候选 r${skill.updateCandidateRevision}`}
          </button>
        </li>
      ))}
    </ul>
  )
}

function SkillDetailCard(props: { model: SkillsModel; snapshot: SkillsSnapshot; overlays?: OverlayOpener | null }) {
  const { model, snapshot } = props
  const assetId = snapshot.selectedAssetId
  const detail = snapshot.detail
  const record = useMemo(
    () => (snapshot.library.items ?? []).find(item => item.assetId === assetId) ?? null,
    [snapshot.library.items, assetId],
  )
  // The trigger keeps its focus across the overlay's whole life: the platform
  // owns dismissal, this page owns the return target (ux.md §原生发现和错误).
  const trigger = useRef<HTMLElement | null>(null)
  const [handle, setHandle] = useState<{ dispose(): void } | null>(null)
  useEffect(() => {
    if (handle === null) return
    return () => { handle.dispose(); trigger.current?.focus() }
  }, [handle])
  if (assetId === null || detail === null) return null
  const openOverlay = (event: MouseEvent<HTMLElement>) => {
    if (!props.overlays) return
    trigger.current = event.currentTarget
    setHandle(props.overlays.open(SKILLS_DETAIL_OVERLAY_ID, { anchor: event.currentTarget }))
  }
  return (
    <article data-testid="skill-detail">
      <h4>{record?.nativeName ?? assetId}</h4>
      <p>{record?.description ?? ''}</p>
      <p data-testid="skill-digest">摘要 {(record?.treeDigest ?? '').slice(0, 18)}…</p>
      <p data-testid="skill-origin">归属 {record === null ? '未知' : originBadge(record.originScope)}</p>
      <p data-testid="skill-approved">
        已批准 r{record?.approvedRevision ?? '—'} · 最新已装 r{record?.latestInstalledRevision ?? '—'}
        {record?.archived ? ' · 来源已归档（只读）' : ''}
      </p>
      {detail.state === 'loading' ? <p role="status">读取修订…</p> : null}
      {detail.state === 'error' ? <p role="alert" data-testid="detail-error">{detail.error}</p> : null}
      {detail.diff === null ? null : (
        <div data-testid="update-diff">
          <p>更新候选 r{detail.diff.fromRevision} → r{detail.diff.toRevision}（批准不会移动已有绑定）</p>
          <ul>
            {detail.diff.added.map(path => <li key={`add:${path}`}>新增 {path}</li>)}
            {detail.diff.removed.map(path => <li key={`del:${path}`}>移除 {path}</li>)}
            {detail.diff.changed.map(path => <li key={`chg:${path}`}>变更 {path}</li>)}
          </ul>
          <button type="button" data-testid="approve-revision" onClick={() => void model.approveRevision(assetId, detail.diff!.toRevision)}>
            批准此版本
          </button>
        </div>
      )}
      <button type="button" data-testid="open-detail-overlay" onClick={openOverlay}>查看详情</button>
      <SourceLine model={model} snapshot={snapshot} assetId={assetId} />
      <RevisionRevisions assetId={assetId} detail={detail} />
      <FileManifest record={record} model={model} assetId={assetId} detail={detail} />
    </article>
  )
}

/** The overlay body the Workbench owns the dismissal of: opened from the list
 * trigger, closed by the platform; the page restores focus on leave. */
export function SkillDetailOverlay(props: { model: SkillsModel; close: () => void }) {
  const snapshot = useSkillsSnapshot(props.model)
  return (
    <div className="skills-settings" data-testid="skills-detail-overlay">
      <style>{styles}</style>
      <p>只读预览：正文与脚本清单，不执行任何内容。</p>
      {snapshot.selectedAssetId === null
        ? <p data-testid="detail-empty">未选择 Skill。</p>
        : <SkillDetailCard model={props.model} snapshot={snapshot} overlays={null} />}
      <button type="button" data-testid="detail-close" onClick={props.close}>关闭</button>
    </div>
  )
}

/** 来源 with its fixed reference: a commit pin, never a floating branch, and
 * the candidate an update check produced (ux.md §内容库). */
function SourceLine(props: { model: SkillsModel; snapshot: SkillsSnapshot; assetId: string }) {
  const sources = props.snapshot.sources
  const row = (sources.items ?? []).find(item => item.assetId === props.assetId) ?? null
  return (
    <div data-testid="source-line">
      {sources.state === 'loading' ? <p role="status">读取来源…</p> : null}
      {sources.state === 'error' ? <p role="alert" data-testid="source-error">{sources.error}</p> : null}
      {row === null ? <p>来源：{props.snapshot.library.items?.find(item => item.assetId === props.assetId)?.source ?? '未知来源'}</p> : (
        <p>
          来源 {row.kind === 'git' ? `Git 固定引用 ${row.reference}` : row.reference} ·{' '}
          {row.candidateRevision === null ? '无更新候选' : `候选 r${row.candidateRevision}`} ·{' '}
          {row.archived ? '来源已归档' : '来源在册'} ·{' '}
          {row.lastChecked === null ? '尚未检查' : `最近检查 ${row.lastChecked}`}
          <button type="button" data-testid="check-update" disabled={sources.state === 'loading'}
            onClick={() => void props.model.checkUpdate(props.assetId)}>检查更新</button>
        </p>
      )}
    </div>
  )
}

function RevisionRevisions(props: { assetId: string; detail: NonNullable<SkillsSnapshot['detail']> }) {
  const revisions = props.detail.revisions
  if (revisions === null) return null
  return (
    <ul data-testid="revision-list">
      {revisions.map(revision => (
        <li key={revision.revision}>
          r{revision.revision} · {revision.approved ? '已批准' : '未批准'} · 摘要 {revision.treeDigest.slice(0, 12)}…
          {revision.sourceCommit === null ? '' : ` · 源提交 ${revision.sourceCommit.slice(0, 12)}`}
        </li>
      ))}
    </ul>
  )
}

/** Attachment/script manifest: a script is a row with its size and a refusal,
 * never a code view and never a run affordance (FR02, G02). */
function FileManifest(props: {
  record: SkillRecordView | null; model: SkillsModel; assetId: string; detail: NonNullable<SkillsSnapshot['detail']>
}) {
  const files = props.record?.fileManifest ?? []
  const revision = props.record?.approvedRevision ?? props.record?.latestInstalledRevision ?? 0
  return (
    <div data-testid="file-manifest">
      <p>附件 / 脚本清单</p>
      <ul>
        {files.map(file => (
          <li key={file.path}>
            {file.path}（{file.bytes} 字节）{file.script ? '【脚本——安装与预览均不执行，内容不展示】' : ''}
            {file.script ? null : (
              <button type="button" onClick={() => void props.model.loadPreview(props.assetId, revision, file.path)}>预览</button>
            )}
          </li>
        ))}
      </ul>
      {props.detail.loadingPreview ? <p role="status">加载预览…</p> : null}
      {props.detail.preview === null ? null : (
        // The label is fixed text: a server-supplied path must never be echoed
        // into an attribute either (ux.md §原生发现和错误).
        <pre data-testid="preview-text" aria-label="文件正文">
          {props.detail.preview.script ? '脚本内容不展示' : props.detail.preview.text ?? ''}
          {props.detail.preview.truncated ? '\n（已按上限截断）' : ''}
        </pre>
      )}
    </div>
  )
}

const OWNERSHIP: Record<'public' | 'project' | 'profile', string> = {
  public: '公共库', project: '项目专用', profile: 'Profile 专用',
}

function ImportWizard(props: { model: SkillsModel; snapshot: SkillsSnapshot }) {
  const phase = props.snapshot.importPhase
  const [ownership, setOwnership] = useState<'public' | 'project' | 'profile'>('public')
  const [ownerId, setOwnerId] = useState('')
  const pick = async (event: ChangeEvent<HTMLInputElement>) => {
    const picked = [...event.currentTarget.files ?? []]
    event.currentTarget.value = ''
    if (picked.length === 0) return
    const files = await Promise.all(picked.map(async file => ({ path: file.name, bytes: new Uint8Array(await file.arrayBuffer()) })))
    await props.model.importPicked(files, 'desktop:picker', { originScope: ownership, originOwner: ownership === 'public' ? null : ownerId || null })
  }
  return (
    <div data-testid="import-wizard">
      <label>
        导入归属
        <select value={ownership} onChange={event => setOwnership(event.currentTarget.value as 'public' | 'project' | 'profile')}>
          {Object.entries(OWNERSHIP).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </label>
      {ownership === 'public' ? null : (
        <label>
          归属 ID
          <input value={ownerId} onChange={event => setOwnerId(event.currentTarget.value)} aria-label="归属项目或 Profile ID" />
        </label>
      )}
      <label data-testid="import-pick">
        选择文件导入
        <input type="file" multiple onChange={event => void pick(event)} />
      </label>
      <ImportPhaseView phase={phase} model={props.model} />
    </div>
  )
}

/** The one honest effect sentence, phrased in exactly one place so no view can
 * overclaim: `effectText` grades through `attest()`. */
export function EffectNote(props: { fields: { evidence: string; proofs: readonly string[] } }) {
  return <span data-testid="effect-note">{effectText(props.fields)}</span>
}

function ImportPhaseView(props: { phase: ImportPhase; model: SkillsModel }) {
  const phase = props.phase
  return (
    <>
      {phase.kind === 'idle' || phase.kind === 'committed' || phase.kind === 'failed' ? (
        <p>导入需经有界传送与预览确认，提交后才发布；安装不执行其中的脚本。</p>
      ) : null}
      {phase.kind === 'transferring' ? <p aria-live="polite" data-testid="import-progress">传送中 {phase.sent}/{phase.total}</p> : null}
      {phase.kind === 'prepared' ? (
        <div data-testid="import-preview">
          <h4>预览：{phase.preview.name} · {OWNERSHIP[phase.owner.originScope]}</h4>
          <ul>
            {phase.preview.files.map(file => (
              <li key={file.path}>
                {file.path}（{file.bytes} 字节）{file.script ? '【脚本——安装与预览均不执行】' : ''}
              </li>
            ))}
          </ul>
          <p>内容摘要 {phase.preview.treeDigest.slice(0, 18)}…</p>
          {phase.preview.warnings.map(warning => <p key={warning} role="alert">{warning}</p>)}
          <button type="button" data-testid="import-confirm" onClick={() => void props.model.confirmImport()}>确认安装</button>
          <button type="button" data-testid="import-cancel" onClick={() => void props.model.cancelImport()}>取消</button>
        </div>
      ) : null}
      {phase.kind === 'committed' ? (
        <p data-testid="import-result">已保存（stored）——这只表示内容已入库，不代表已装载到任何会话。</p>
      ) : null}
      {phase.kind === 'failed' ? (
        <p role="alert" data-testid="import-failure">导入失败：{phase.message}。旧版本与绑定保持不变。</p>
      ) : null}
    </>
  )
}

// ————————————————————————————— 默认启用 / 项目启用

function AssignmentArea(props: { model: SkillsModel; snapshot: SkillsSnapshot; layerKey: LayerKey; narrow: boolean }) {
  const { model, snapshot, layerKey } = props
  const state = snapshot[layerKey]
  const isProject = layerKey === 'project'
  const projects = snapshot.projects
  return (
    <section aria-label={isProject ? '项目启用' : '默认启用'} data-testid={isProject ? 'project-assignments' : 'default-assignments'}>
      <h3>{isProject ? '项目启用' : '默认启用'}</h3>
      {isProject ? (
        <label data-testid="project-picker">
          项目
          <select
            aria-label="选择项目" value={state.projectId ?? ''} disabled={projects.state !== 'ready'}
            onChange={event => void model.setProject(event.currentTarget.value === '' ? null : event.currentTarget.value)}
          >
            <option value="">（未选择）</option>
            {(projects.items ?? []).map(project => (
              <option key={project.projectId} value={project.projectId}>
                {project.displayName}{project.state === 'available' ? '' : project.state === 'missing' ? '（已缺失）' : '（未授权）'}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {isProject && projects.state === 'error' ? <p role="alert" data-testid="projects-error">项目列表读取失败：{projects.error}</p> : null}
      <HarnessPicker harnessId={state.harnessId} disabled={!state.editable} onPick={id => void model.setHarness(layerKey, id)} />
      {isProject ? null : (
        <p data-testid="global-scope-note">全局默认仅影响当前用户在本 Server 中的新提交，不改动既有会话。</p>
      )}
      {!state.editable ? <p role="status" data-testid="editing-stopped">{state.stopReason ?? '本层暂不可编辑'}</p> : null}
      {state.error === null ? null : <p role="alert" data-testid={`layer-error-${layerKey}`}>{state.error}</p>}
      {state.conflict === null ? null : (
        <div role="alert" data-testid={`save-conflict-${layerKey}`}>
          <p>{state.conflict.message}（服务端版本 {state.conflict.serverRevision}）</p>
          <button type="button" data-testid={`conflict-reread-${layerKey}`} onClick={() => void model.reRead(layerKey)}>
            重新读取
          </button>
        </div>
      )}
      {state.state === 'loading' ? <p role="status" data-testid={`layer-loading-${layerKey}`}>读取分配…</p> : null}
      {state.rows.length === 0 ? (
        <p data-testid={`layer-empty-${layerKey}`}>此范围暂无可分配的 Skill。</p>
      ) : (
        <table data-testid={`assignment-table-${layerKey}`}>
          <thead>
            <tr><th scope="col">Skill</th><th scope="col">本层设置</th><th scope="col">最终结果</th></tr>
          </thead>
          <tbody>
            {state.rows.map(row => (
              <AssignmentRowView key={row.assetId} row={row} layerKey={layerKey} model={model} disabled={!state.editable} narrow={props.narrow} />
            ))}
          </tbody>
        </table>
      )}
      <div>
        <button type="button" data-testid={`save-${layerKey}`} disabled={state.saving || Object.keys(state.draft).length === 0}
          onClick={() => void model.save(layerKey)}>
          保存本层修改
        </button>
        <button type="button" data-testid={`discard-${layerKey}`} disabled={Object.keys(state.draft).length === 0}
          onClick={() => model.discard(layerKey)}>
          放弃修改
        </button>
        <button type="button" data-testid={`preview-${layerKey}`} disabled={Object.keys(state.draft).length === 0}
          onClick={() => void model.previewDraft(layerKey)}>
          预览有效集合（不写入）
        </button>
      </div>
      {state.preview === null ? null : (
        <div data-testid={`draft-preview-${layerKey}`}>
          <p>草稿预览（未保存，不影响已存记录）</p>
          <ul>
            {state.preview.resolved.map(item => (
              <li key={item.assetId}>{item.nativeName} · {resultText(item)} · {effectText(item)}</li>
            ))}
          </ul>
          {state.preview.refusals.map(refusal => <p key={`${refusal.code}:${refusal.assetId}`} role="alert">拒绝：{refusal.message}</p>)}
        </div>
      )}
    </section>
  )
}

/** 所有 Harness vs one brand (ux.md §默认启用). */
function HarnessPicker(props: { harnessId: string | null; disabled: boolean; onPick: (harnessId: string | null) => void }) {
  return (
    <label data-testid="harness-picker">
      Harness 范围
      <select aria-label="Harness 范围" value={props.harnessId ?? ''} disabled={props.disabled}
        onChange={event => props.onPick(event.currentTarget.value === '' ? null : event.currentTarget.value)}>
        <option value="">所有 Harness</option>
        <option value="pi">Pi</option>
        <option value="codex">Codex</option>
        <option value="claude">Claude</option>
      </select>
    </label>
  )
}

const DECISIONS = ['enable', 'disable', 'inherit'] as const

function AssignmentRowView(props: { row: AssignmentViewRow; layerKey: LayerKey; model: SkillsModel; disabled: boolean; narrow: boolean }) {
  const { row, model, layerKey } = props
  // 本层设置 reads the draft first, then this layer's stored row; absence of
  // both is 继承 — never a hidden default that could be mistaken for a switch.
  const setting = row.draft?.decision ?? row.layerRow?.decision ?? 'inherit'
  const pinned = row.draft?.revision ?? row.layerRow?.revision ?? null
  const inheritedFromAbove = row.effective !== null && row.layerRow === null &&
    row.effective.excludedBy === null && row.effective.selectedBy.layer !== (layerKey === 'global' ? 'user-global' : 'project')
  return (
    <tr data-testid={`assignment-row-${row.assetId}`} data-narrow={props.narrow ? 'stack' : undefined}>
      <th scope="row">
        {row.nativeName}
        <span data-testid={`origin-${row.assetId}`}> {originBadge(row.originScope)}</span>
        {row.archived ? <span data-testid={`archived-${row.assetId}`}> 已归档</span> : null}
      </th>
      <td data-testid={`layer-setting-${row.assetId}`}>
        <span role="group" aria-label={`${row.nativeName} 本层设置`}>
          {DECISIONS.map(decision => (
            <button key={decision} type="button" disabled={props.disabled} aria-pressed={setting === decision}
              onClick={() => model.edit(layerKey, row.assetId, decision)}>
              {decisionText(decision)}
            </button>
          ))}
        </span>
        {row.draft === null ? null : <span data-testid={`draft-flag-${row.assetId}`}>未保存</span>}
        {pinned === null ? null : <span data-testid={`pinned-${row.assetId}`}>固定版 r{pinned}</span>}
      </td>
      <td data-testid={`effective-${row.assetId}`}>
        {resultText(row.effective)}
        {row.effective === null ? null : (
          <>
            <span data-testid={`effective-scope-${row.assetId}`}> · {scopeText(row.effective.selectedBy)}</span>
            {inheritedFromAbove ? (
              <span data-testid={`inherited-${row.assetId}`}>
                {' · '}
                {row.effective!.selectedBy.layer === 'user-global' ? '继承自全局' : '继承自上层'}
                的决定
              </span>
            ) : null}
            {row.effective.excludedBy === null ? null : (
              <span data-testid={`excluded-by-${row.assetId}`}> · 由 {scopeText(row.effective.excludedBy)} 排除</span>
            )}
            <EffectNote fields={row.effective} />
          </>
        )}
      </td>
    </tr>
  )
}

// ———————————————————————————————————— 原生发现

/** Read-only by construction: no switch, no "已禁用", no absolute path (US5,
 * FR10, G11). */
function NativeArea(props: { snapshot: SkillsSnapshot; narrow: boolean }) {
  const native = props.snapshot.native
  return (
    <section aria-label="由 Harness 或项目提供" data-testid="native-discovery">
      <h3>由 Harness 或项目提供</h3>
      <p>这些项由目标 Harness 自行发现，Ordessa 只观察、不改动；需要管理时请在内容库显式导入副本。</p>
      {native.state === 'loading' ? <p role="status">发现中…</p> : null}
      {native.state === 'error' ? <p role="alert" data-testid="native-error">{native.error}</p> : null}
      {native.items === null || native.items.length === 0 ? <p data-testid="native-empty">暂无原生发现记录。</p> : (
        <ul data-testid="native-list">
          {native.items.map(item => (
            <li key={`${item.harnessId}:${item.nativeName}`} data-testid={`native-${item.harnessId}-${item.nativeName}`}
              data-narrow={props.narrow ? 'stack' : undefined}>
              {item.nativeName} · {item.harnessId} {item.runtimeVersion} · {nativeLocationText[item.locationCategory]} ·{' '}
              <span data-testid={`native-mask-${item.nativeName}`}>{nativeMaskText(item.canBeMasked)}</span>
              {item.conflictsWith === null ? '' : ` · 与受管项 ${item.conflictsWith} 重名，装配会先拒绝`}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

