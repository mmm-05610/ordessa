/**
 * 宿主 UI：故障屏、设置页、关于面板、命令面板、Harness 可用性面板。
 * 纪律（C-05 §2 / C-06 / C-07 / C-08）：
 *   · 颜色只来自 C-05 的 CSS 变量，本文件**不写死色值**；
 *   · 故障零空白：每条都有 reason / remedy / logRef / 导出诊断入口；
 *   · `unknown` 一律显示为"状态未知"，绝不显示成可用或绿色；
 *   · 键盘可达：面板可用 Tab / ↑↓ / Enter / Esc 走完，不需要鼠标。
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { CommandOutcome, DiagnosticFragment, Fault, HarnessReport, SettingsSection } from '@extensions/ordessa.contracts/contract.js'

// --- PA-12 故障屏 -----------------------------------------------------------

export interface FaultScreenProps {
  faults: readonly Fault[]
  onExportDiagnostics?: () => void
  onOpenLogs?: () => void
  onRetry?: () => void
  titleOf?: (fault: Fault) => string
}

/** 无故障时返回 null（正常路径不渲染任何东西）；有故障时绝不出现空白区域。 */
export function FaultScreen({ faults, onExportDiagnostics, onOpenLogs, onRetry, titleOf = defaultTitle }: FaultScreenProps) {
  if (!faults.length) return null
  return (
    <section className="od-fault" role="alert" data-testid="fault-screen" aria-label="启动故障">
      <h1 className="od-fault-title">Ordessa 无法继续</h1>
      {faults.map((fault, index) => (
        <article className="od-fault-card" key={`${fault.kind}/${fault.logRef}/${index}`} data-testid="fault" data-fault-kind={fault.kind}>
          <h2>{titleOf(fault)}</h2>
          <p className="od-fault-reason" data-testid="fault-reason">原因：{fault.reason}</p>
          <p className="od-fault-remedy" data-testid="fault-remedy">你可以：{fault.remedy}</p>
          <p className="od-fault-log" data-testid="fault-logref">日志：<code>{fault.logRef}</code></p>
        </article>
      ))}
      <div className="od-fault-actions">
        {onRetry ? <button type="button" onClick={onRetry}>重试</button> : null}
        {onOpenLogs ? <button type="button" onClick={onOpenLogs}>查看日志</button> : null}
        {onExportDiagnostics ? <button type="button" onClick={onExportDiagnostics}>导出诊断</button> : null}
      </div>
    </section>
  )
}

const TITLES: Record<string, string> = {
  'data-root-missing': '数据目录不可用',
  'data-root-locked': '数据目录已被占用',
  'runtime-missing': '随包运行时缺失',
  'port-conflict': '端口冲突',
  'server-launch-failed': 'Server 启动失败',
  'update-source-unreachable': '更新源不可达',
}
function defaultTitle(fault: Fault): string { return TITLES[fault.kind] ?? '启动故障' }

// --- PA-13 设置页 -----------------------------------------------------------

export type SettingsSectionId = 'general' | 'data' | 'logs' | 'update' | 'about'

export interface HostSettingsProps {
  dataRoot: string
  logLevel: string
  logHealth?: { dropped: number; writable: boolean }
  updateState: { state: string; version?: string; current?: string; reason?: string; received?: number; total?: number }
  updateError?: string
  fragments?: readonly { id: string; state: 'known' | 'unknown' }[]
  onLogLevel: (level: string) => void
  onOpenLogs: () => void
  onExportDiagnostics: () => void
  onCheckUpdate: () => void
  onDownloadUpdate: () => void
  onApplyUpdate: () => void
  /** 插件登记的分区（PA-14）：卸载后这里不再出现，但配置保留在主进程。 */
  contributed?: readonly SettingsSection[]
  onClose: () => void
}

const HOST_SECTIONS: { id: SettingsSectionId; title: string; order: number }[] = [
  { id: 'general', title: '通用', order: 10 },
  { id: 'data', title: '数据', order: 20 },
  { id: 'logs', title: '日志', order: 30 },
  { id: 'update', title: '更新', order: 40 },
  { id: 'about', title: '关于', order: 50 },
]

export function SettingsPage(props: HostSettingsProps) {
  const [active, setActive] = useState<SettingsSectionId>('general')
  const contributed = [...(props.contributed ?? [])].sort((a, b) => (a.order ?? 100) - (b.order ?? 100) || a.title.localeCompare(b.title))
  const unknown = (props.fragments ?? []).filter(fragment => fragment.state === 'unknown')
  return (
    <section className="od-settings" role="region" aria-label="设置" data-testid="settings">
      <nav aria-label="设置分区">
        <ul>
          {HOST_SECTIONS.map(section => (
            <li key={section.id}>
              <button type="button" aria-pressed={active === section.id} onClick={() => setActive(section.id)}>{section.title}</button>
            </li>
          ))}
          {contributed.map(section => (
            <li key={section.id}><span data-testid="contributed-section">{section.title}</span></li>
          ))}
        </ul>
      </nav>
      <div className="od-settings-body">
        {active === 'general' ? <section aria-label="通用">
          <h2>通用</h2>
          <p>语言：简体中文（本期不交付翻译）</p>
        </section> : null}
        {active === 'data' ? <section aria-label="数据">
          <h2>数据</h2>
          {/* 数据根**只读**展示：路径不可在界面改写，只提供打开目录。 */}
          <p>数据根：<output data-testid="data-root">{props.dataRoot}</output>（只读）</p>
          <button type="button" onClick={props.onOpenLogs}>打开数据目录</button>
        </section> : null}
        {active === 'logs' ? <section aria-label="日志">
          <h2>日志</h2>
          <label htmlFor="od-log-level">级别</label>
          <select id="od-log-level" value={props.logLevel} onChange={event => props.onLogLevel(event.target.value)}>
            {['debug', 'info', 'warn', 'error'].map(level => <option key={level} value={level}>{level}</option>)}
          </select>
          {props.logHealth && !props.logHealth.writable
            ? <p role="status" data-testid="log-unwritable">日志不可写：已丢弃 {props.logHealth.dropped} 条</p>
            : null}
          <button type="button" onClick={props.onOpenLogs}>打开日志目录</button>
          <button type="button" onClick={props.onExportDiagnostics}>导出诊断</button>
        </section> : null}
        {active === 'update' ? <section aria-label="更新">
          <h2>更新</h2>
          <p data-testid="update-state">当前状态：{props.updateState.state}{props.updateState.version ? `（${props.updateState.version}）` : ''}</p>
          {props.updateState.state === 'downloading'
            ? <progress data-testid="update-progress" max={props.updateState.total ?? 1} value={props.updateState.received ?? 0} />
            : null}
          {props.updateState.reason ? <p role="alert" data-testid="update-reason">{props.updateState.reason}</p> : null}
          {props.updateError ? <p role="alert" data-testid="update-error">{props.updateError}</p> : null}
          <button type="button" onClick={props.onCheckUpdate}>检查更新</button>
          <button type="button" onClick={props.onDownloadUpdate}>下载</button>
          <button type="button" onClick={props.onApplyUpdate}>安装并重启</button>
        </section> : null}
        {active === 'about' ? <section aria-label="关于"><h2>关于</h2><AboutSlot /></section> : null}
        {unknown.length ? <section aria-label="未知配置" data-testid="unknown-fragments">
          <h2>保留的配置</h2>
          <p>以下配置属于当前未启用的提供者，已保留但不下发：</p>
          <ul>{unknown.map(fragment => <li key={fragment.id} data-testid="unknown-fragment">{fragment.id}</li>)}</ul>
        </section> : null}
      </div>
      <button type="button" onClick={props.onClose} aria-label="关闭设置">关闭</button>
    </section>
  )
}

function AboutSlot({ children }: { children?: ReactNode }) { return <>{children}</> }

// --- PA-04 关于面板 ---------------------------------------------------------

export interface AboutInfo {
  app: { productName: string; version: string; build: string; description: string; author: string; license: string; homepage: string; repository: string }
  plugins: readonly { id: string; version: string }[]
  licenses: readonly { name: string; version: string; license: string }[]
}

export function AboutPanel({ about, onOpenLicense }: { about: AboutInfo; onOpenLicense: () => void }) {
  return (
    <section className="od-about" role="region" aria-label="关于" data-testid="about">
      <h1>{about.app.productName}</h1>
      <p>{about.app.description}</p>
      <dl>
        <dt>版本</dt><dd data-testid="about-version">{about.app.version}</dd>
        <dt>构建号</dt><dd data-testid="about-build">{about.app.build}</dd>
        <dt>作者</dt><dd>{about.app.author}</dd>
        <dt>许可证</dt><dd data-testid="about-license">{about.app.license}</dd>
        <dt>主页</dt><dd>{about.app.homepage}</dd>
        <dt>仓库</dt><dd>{about.app.repository}</dd>
      </dl>
      <h2>插件版本</h2>
      <ul data-testid="about-plugins">
        {about.plugins.map(plugin => <li key={plugin.id}>{plugin.id} · {plugin.version}</li>)}
      </ul>
      <h2>第三方许可证</h2>
      <ul data-testid="about-licenses">
        {about.licenses.map(entry => <li key={entry.name}>{entry.name}@{entry.version} · {entry.license}</li>)}
      </ul>
      <button type="button" onClick={onOpenLicense}>打开许可证全文</button>
    </section>
  )
}

// --- PA-19/20 命令面板 ------------------------------------------------------

export interface PaletteEntryView { id: string; title: string; category?: string; key?: string; available: boolean }

export interface CommandPaletteProps {
  open: boolean
  entries: readonly PaletteEntryView[]
  onRun: (id: string) => void | Promise<unknown>
  onClose: () => void
  /** 执行失败的呈现（C-07 §4：UI 报错 + 应用继续可用）。 */
  outcome?: CommandOutcome | null
}

/** 键盘全流程：↓/↑ 选择、Enter 执行、Esc 关闭；打开时焦点落在搜索框。 */
export function CommandPalette({ open, entries, onRun, onClose, outcome }: CommandPaletteProps) {
  const [query, setQuery] = useState('')
  const [cursor, setCursor] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return entries.filter(entry => entry.available && (!needle || entry.title.toLowerCase().includes(needle) || entry.id.toLowerCase().includes(needle)))
  }, [entries, query])
  useEffect(() => { if (open) { setQuery(''); setCursor(0); inputRef.current?.focus() } }, [open])
  if (!open) return null
  return (
    <div className="od-palette-backdrop" role="presentation" onClick={onClose}>
      <section className="od-palette" role="dialog" aria-modal="true" aria-label="命令面板" data-testid="command-palette"
        onClick={event => event.stopPropagation()}
        onKeyDown={event => {
          if (event.key === 'Escape') { event.stopPropagation(); onClose() }
          else if (event.key === 'ArrowDown') { event.preventDefault(); setCursor(index => Math.min(index + 1, visible.length - 1)) }
          else if (event.key === 'ArrowUp') { event.preventDefault(); setCursor(index => Math.max(index - 1, 0)) }
          else if (event.key === 'Enter') { event.preventDefault(); const entry = visible[cursor]; if (entry) void onRun(entry.id) }
        }}>
        <input ref={inputRef} aria-label="搜索命令" value={query} data-testid="palette-search"
          onChange={event => { setQuery(event.target.value); setCursor(0) }} />
        <ul role="listbox" aria-label="命令">
          {visible.map((entry, index) => (
            <li key={entry.id} role="option" aria-selected={index === cursor}>
              <button type="button" data-testid="palette-item" onClick={() => void onRun(entry.id)}>
                <span>{entry.title}</span>
                {entry.category ? <small>{entry.category}</small> : null}
                {entry.key ? <kbd>{entry.key}</kbd> : null}
              </button>
            </li>
          ))}
          {visible.length === 0 ? <li data-testid="palette-empty">没有匹配的命令</li> : null}
        </ul>
        {outcome && outcome.kind !== 'Accepted'
          ? <p role="alert" data-testid="palette-error">{outcome.kind === 'Refused' ? `命令不可用：${outcome.reason}` : `命令状态未知：${outcome.reason}`}</p>
          : null}
      </section>
    </div>
  )
}

// --- C-08 Harness 可用性渲染 ------------------------------------------------

/**
 * `reports === undefined` 表示**没有 Harness 插件**（C-08 §4）：显示"未提供信息"，
 * 绝不显示成"没有 Harness"或"全部可用"。
 */
export function HarnessAvailabilityPanel({ reports }: { reports?: readonly HarnessReport[] }) {
  if (reports === undefined) {
    return <section aria-label="Harness 可用性" data-testid="harness-absent"><h2>Harness</h2><p>未提供 Harness 可用性信息</p></section>
  }
  // C-08 §3：空列表**不得**冒充"没有 Harness"——显示"状态未知"。
  if (reports.length === 0) {
    return <section aria-label="Harness 可用性" data-testid="harness-unknown"><h2>Harness</h2><p>状态未知：未获得任何可用性观测</p></section>
  }
  return (
    <section aria-label="Harness 可用性" data-testid="harness-list">
      <h2>Harness</h2>
      <ul>
        {reports.map(report => (
          <li key={report.brand} data-testid="harness-item" data-state={report.state}>
            <span>{report.brand}</span>
            <span>{stateLabel(report.state)}</span>
            {report.reason ? <span>{report.reason}</span> : null}
            {report.remedy ? <span>{report.remedy}</span> : null}
            {report.version ? <span>v{report.version}</span> : null}
          </li>
        ))}
      </ul>
    </section>
  )
}

function stateLabel(state: HarnessReport['state']): string {
  return ({
    available: '可用', 'not-installed': '未安装', 'not-logged-in': '未登录',
    unsupported: '不支持', failed: '失败', unknown: '状态未知',
  } as const)[state]
}

/** C-06 §B2 片段结果：unknown 片段要显示出来，不得静默丢弃。 */
export function DiagnosticFragmentList({ fragments }: { fragments: readonly DiagnosticFragment[] }) {
  return (
    <ul data-testid="diagnostic-fragments">
      {fragments.map(fragment => (
        <li key={fragment.id} data-state={fragment.state}>
          {fragment.id} · {fragment.state === 'collected' ? '已收集' : `状态未知（${fragment.state === 'unknown' ? fragment.reason : ''}）`}
        </li>
      ))}
    </ul>
  )
}
