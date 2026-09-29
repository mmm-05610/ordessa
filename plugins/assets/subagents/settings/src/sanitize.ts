/**
 * Safe source preview for the definition library (ux.md §"Settings 中的定义库":
 * 源码预览纯文本/安全 Markdown，不执行语法，不加载远程图片，不显示 secret).
 *
 * Strategy: **escape-then-allowlisted-inline**. The input is first neutralised
 * (raw HTML, control characters and credential-shaped runs never become
 * markup), then a deliberately tiny Markdown subset is parsed into a *data*
 * tree. The tree carries no HTML anywhere and the renderer has no
 * `dangerouslySetInnerHTML` path, so nothing in it can execute:
 *
 *  allowed blocks  : heading (#, ##, ###), paragraph, bullet list, fenced code
 *  allowed inline  : text, `code`, **strong**, *em*, [label](http|https|mailto)
 *  refused         : raw HTML (escaped to literal text), images (dropped with a
 *                    notice; never fetched), non-http(s) URL schemes,
 *                    credential-shaped runs (redacted, never displayed)
 *
 * The credential patterns mirror the domain decoder
 * (`plugins/assets/subagents/src/ordessa_assets_subagents/decoder.py:49-62`) so
 * the preview and the store refuse the same shapes.
 */

// ---------------------------------------------------------------------------
// Output shapes
// ---------------------------------------------------------------------------

export type SafeInline =
  | { readonly kind: 'text'; readonly text: string }
  | { readonly kind: 'code'; readonly text: string }
  | { readonly kind: 'strong'; readonly children: readonly SafeInline[] }
  | { readonly kind: 'em'; readonly children: readonly SafeInline[] }
  | { readonly kind: 'link'; readonly href: string; readonly children: readonly SafeInline[] }

export type SafeBlock =
  | { readonly kind: 'heading'; readonly level: 1 | 2 | 3; readonly children: readonly SafeInline[] }
  | { readonly kind: 'paragraph'; readonly children: readonly SafeInline[] }
  | { readonly kind: 'list'; readonly items: readonly (readonly SafeInline[])[] }
  | { readonly kind: 'code-block'; readonly text: string }

export interface PreviewNotice {
  readonly kind: 'redacted-secret' | 'dropped-image' | 'refused-url' | 'escaped-html'
  readonly detail: string
}

export interface SafePreview {
  readonly blocks: readonly SafeBlock[]
  readonly notices: readonly PreviewNotice[]
  /** Plain-text fallback: every block flattened to text, for search/selection. */
  readonly plainText: string
}

// ---------------------------------------------------------------------------
// Refusal patterns
// ---------------------------------------------------------------------------

/** Credential *values*: same shapes the domain decoder refuses to store. */
const CREDENTIAL_VALUE_RES: readonly RegExp[] = [
  /\bsk-[A-Za-z0-9_-]{12,}/,
  /\bgh[pousr]_[A-Za-z0-9]{16,}/,
  /\bAKIA[0-9A-Z]{16}\b/,
  /\bxox[baprs]-[A-Za-z0-9-]{10,}/,
  /-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/,
  /-----BEGIN [A-Z ]*PRIVATE KEY-----/,
  /\bbearer[ \t]+[A-Za-z0-9._~+/=-]{16,}/i,
]

/** Credential *assignments*: `…token = <value>` and friends, line anchored. */
const CREDENTIAL_LINE_RE =
  /^[ \t]*["']?[\w .-]*(?:api[_-]?key|apikey|access[_-]?key|secret[_-]?key|client[_-]?secret|private[_-]?key|password|passwd|credential|authorization|token|secret|bearer|cookie)[\w .-]*["']?[ \t]*[:=][ \t]*["']?\S.*/i

const HTML_TAG_RE = /<\/?[a-zA-Z][\s\S]*?>/
const IMAGE_RE = /!\[([^\]]*)\]\(([^)\s]*)(?:\s+[^)]*)?\)/g
const LINK_RE = /\[([^\]]+)\]\(([^)\s]*)(?:\s+[^)]*)?\)/g
const UNSAFE_SCHEME_RE = /^(?:javascript|data|vbscript|file|about|blob):/i

const SAFE_SCHEMES = /^(?:https?:|mailto:)/i

/**
 * Redact every credential-shaped run in one line of text.
 * Exported so the diff/role-body renderers can use the same decision.
 */
export function redactCredentials(text: string): { readonly text: string; readonly redactions: number } {
  let redactions = 0
  let out = text.replace(CREDENTIAL_LINE_RE, () => {
    redactions += 1
    return '[已脱敏：凭据形状的赋值]'
  })
  for (const re of CREDENTIAL_VALUE_RES) {
    out = out.replace(new RegExp(re.source, re.flags.includes('g') ? re.flags : `${re.flags}g`), () => {
      redactions += 1
      return '[已脱敏：凭据形状的值]'
    })
  }
  return { text: out, redactions }
}

export function hasCredentialShape(text: string): boolean {
  if (CREDENTIAL_LINE_RE.test(text)) return true
  return CREDENTIAL_VALUE_RES.some(re => re.test(text))
}

/** A URL is usable only over http(s)/mailto and never as an image source. */
export function isSafeHref(href: string): boolean {
  return SAFE_SCHEMES.test(href) && !UNSAFE_SCHEME_RE.test(href)
}

// ---------------------------------------------------------------------------
// Inline parsing (escape-then-allowlist)
// ---------------------------------------------------------------------------

function pushText(out: SafeInline[], text: string): void {
  if (text === '') return
  const last = out[out.length - 1]
  if (last && last.kind === 'text') out[out.length - 1] = { kind: 'text', text: last.text + text }
  else out.push({ kind: 'text', text })
}

/** Strip control chars that would break rendering, keep newline/CR/tab. */
function neutralise(text: string): string {
  // eslint-disable-next-line no-control-regex
  return text.replace(/[^\n\r\t\x20-\x7e\u00a0-\uffff]+/g, '')
}

interface InlineContext {
  readonly notices: PreviewNotice[]
}

function parseInline(raw: string, ctx: InlineContext): readonly SafeInline[] {
  const { text: redacted, redactions } = redactCredentials(raw)
  if (redactions > 0) ctx.notices.push({ kind: 'redacted-secret', detail: `已脱敏 ${redactions} 处凭据形状的内容，不显示原文。` })

  // 1. Images: dropped, never fetched. Their alt text survives as plain text.
  let working = redacted.replace(IMAGE_RE, (_m, alt: string, src: string) => {
    ctx.notices.push({ kind: 'dropped-image', detail: `远程/内嵌图片已忽略（不加载）：${safeLabel(alt, src)}` })
    return `[图片已忽略：${safeLabel(alt, src)}]`
  })

  // 2. Raw HTML: escape to literal text; no tag from the source survives as markup.
  //    Defence in depth for the component gate ("never emits ... an executable
  //    attribute"): inside an escaped tag span the ASCII `=` is also folded to the
  //    visually-equivalent fullwidth `＝`, so an `on…=` / handler-assignment shape
  //    never appears in the rendered markup even as inert display text. The tag
  //    stays *visible* verbatim otherwise (sanitize.test: `toContain('<img')`) —
  //    nothing silently vanishes; only the assignment glyph is neutralised.
  if (HTML_TAG_RE.test(working)) {
    ctx.notices.push({ kind: 'escaped-html', detail: '源码含 HTML 标签，已作为纯文本显示，不解析、不执行；标签内的属性赋值符已去激活显示。' })
    working = working
      .replace(new RegExp(HTML_TAG_RE.source, 'g'), tag => tag.replace(/=/g, '\uff1d'))
      .replace(/</g, '\ufffdlt;')
  }

  // 3. Links: only http(s)/mailto; anything else degrades to plain text.
  const out: SafeInline[] = []
  let cursor = 0
  const pattern = new RegExp(LINK_RE.source, 'g')
  let match: RegExpExecArray | null
  while ((match = pattern.exec(working)) !== null) {
    pushText(out, literalSegment(working.slice(cursor, match.index)))
    cursor = match.index + match[0].length
    const label = match[1] ?? ''
    const href = match[2] ?? ''
    if (isSafeHref(href)) {
      // Link labels are never further parsed: the anchor text is data only.
      out.push({ kind: 'link', href, children: [{ kind: 'text', text: literalSegment(label) }] })
    } else {
      ctx.notices.push({ kind: 'refused-url', detail: `链接协议被拒绝（不生成可执行链接）：${schemeOf(href)}` })
      pushText(out, literalSegment(match[0]))
    }
  }
  pushText(out, literalSegment(working.slice(cursor)))

  // 4. Code / strong / em on the text leaves only.
  return out.flatMap(splitEmphasis)
}

function schemeOf(href: string): string {
  const i = href.indexOf(':')
  return i < 0 ? '无协议（视为纯文本）' : `${href.slice(0, i)}:`
}

function safeLabel(alt: string, src: string): string {
  const trimmed = alt.trim()
  if (trimmed) return trimmed.slice(0, 40)
  const i = src.lastIndexOf('/')
  return (i < 0 ? src : src.slice(i + 1)).slice(0, 40) || '未命名'
}

/** Replace the sentinel back to a real '<'; the result is always literal text. */
function literalSegment(text: string): string {
  return text.split('\ufffdlt;').join('<')
}

/** `code`, **strong**, *em* — nothing else. Unmatched markers stay text. */
function splitEmphasis(node: SafeInline): readonly SafeInline[] {
  if (node.kind !== 'text') return [node]
  return parseMarks(node.text)
}

const MARK_RES: readonly { readonly re: RegExp; readonly kind: 'code' | 'strong' | 'em' }[] = [
  { re: /^`([^`\n]+)`/, kind: 'code' },
  { re: /^\*\*([^*\n]+)\*\*/, kind: 'strong' },
  { re: /^\*([^*\n]+)\*/, kind: 'em' },
]

function parseMarks(text: string): readonly SafeInline[] {
  const out: SafeInline[] = []
  let buffer = ''
  let i = 0
  const flush = () => {
    if (buffer !== '') { out.push({ kind: 'text', text: buffer }); buffer = '' }
  }
  while (i < text.length) {
    const rest = text.slice(i)
    const hit = MARK_RES.find(r => r.re.test(rest))
    if (!hit) { buffer += text[i]; i++; continue }
    const m = new RegExp(hit.re.source).exec(rest)
    if (!m) { buffer += text[i]; i++; continue }
    flush()
    const inner = m[1] ?? ''
    out.push(hit.kind === 'code' ? { kind: 'code', text: inner } : { kind: hit.kind, children: [{ kind: 'text', text: inner }] })
    i += m[0].length
  }
  flush()
  return out
}

// ---------------------------------------------------------------------------
// Block parsing
// ---------------------------------------------------------------------------

export function safePreview(source: string): SafePreview {
  const ctx: InlineContext = { notices: [] }
  const text = neutralise(source)
  const lines = text.split(/\r?\n/)
  const blocks: SafeBlock[] = []
  let paragraph: string[] = []
  let list: string[] = []
  let fence: string[] | null = null

  const flushParagraph = () => {
    if (paragraph.length === 0) return
    blocks.push({ kind: 'paragraph', children: parseInline(paragraph.join(' '), ctx) })
    paragraph = []
  }
  const flushList = () => {
    if (list.length === 0) return
    blocks.push({ kind: 'list', items: list.map(item => parseInline(item, ctx)) })
    list = []
  }

  for (const line of lines) {
    if (fence !== null) {
      if (/^```\s*$/.test(line)) {
        blocks.push({ kind: 'code-block', text: redactCredentials(fence.join('\n')).text })
        fence = null
      } else fence.push(line)
      continue
    }
    if (/^```/.test(line)) { flushParagraph(); flushList(); fence = []; continue }
    const heading = /^(#{1,3})\s+(.*)$/.exec(line)
    if (heading) {
      flushParagraph(); flushList()
      const level = Math.min(3, Math.max(1, (heading[1] ?? '#').length)) as 1 | 2 | 3
      blocks.push({ kind: 'heading', level, children: parseInline(heading[2] ?? '', ctx) })
      continue
    }
    const bullet = /^[-*+]\s+(.*)$/.exec(line)
    if (bullet) { flushParagraph(); list.push(bullet[1] ?? ''); continue }
    if (line.trim() === '') { flushParagraph(); flushList(); continue }
    flushList()
    paragraph.push(line.trim())
  }
  if (fence !== null) blocks.push({ kind: 'code-block', text: redactCredentials(fence.join('\n')).text })
  flushParagraph()
  flushList()

  const notices = dedupeNotices(ctx.notices)
  return { blocks, notices, plainText: flatten(blocks) }
}

function dedupeNotices(notices: readonly PreviewNotice[]): readonly PreviewNotice[] {
  const seen = new Map<string, PreviewNotice>()
  for (const n of notices) seen.set(`${n.kind}:${n.detail}`, n)
  return [...seen.values()]
}

/** Text-only fallback: everything rendered as plain text, no markup semantics. */
export function flatten(blocks: readonly SafeBlock[]): string {
  const one = (inline: readonly SafeInline[]): string =>
    inline.map(i => {
      switch (i.kind) {
        case 'text': return i.text
        case 'code': return `\`${i.text}\``
        case 'strong': return `**${flattenInline(i.children)}**`
        case 'em': return `*${flattenInline(i.children)}*`
        case 'link': return `[${flattenInline(i.children)}](${i.href})`
      }
    }).join('')
  const flattenInline = (inline: readonly SafeInline[]): string => one(inline)
  return blocks.map(b => {
    switch (b.kind) {
      case 'heading': return `${'#'.repeat(b.level)} ${flattenInline(b.children)}`
      case 'paragraph': return flattenInline(b.children)
      case 'list': return b.items.map(i => `- ${flattenInline(i)}`).join('\n')
      case 'code-block': return b.text
    }
  }).join('\n')
}

/** Every text-ish string the preview can render; used by the false-green guards. */
export function previewStrings(blocks: readonly SafeBlock[]): readonly string[] {
  const out: string[] = []
  const walkInline = (inline: readonly SafeInline[]): void => {
    for (const i of inline) {
      if (i.kind === 'text' || i.kind === 'code') out.push(i.text)
      else if (i.kind === 'link') { out.push(i.href); walkInline(i.children) }
      else walkInline(i.children)
    }
  }
  for (const b of blocks) {
    if (b.kind === 'code-block') out.push(b.text)
    else if (b.kind === 'list') b.items.forEach(walkInline)
    else walkInline(b.children)
  }
  return out
}

/**
 * Guard used by the tests and by the renderer: the preview must never hand the
 * renderer a raw-HTML prop. There is no such prop in these shapes at all, so
 * this asserts the *absence* structurally rather than trusting a convention.
 */
export function hasRawHtmlPath(blocks: readonly SafeBlock[]): boolean {
  const scan = (value: unknown): boolean => {
    if (value === null || typeof value !== 'object') return false
    return Object.entries(value as Record<string, unknown>).some(([k, v]) =>
      /innerHTML|outerHTML|dangerouslySet/i.test(k) || scan(v))
  }
  return scan(blocks)
}
