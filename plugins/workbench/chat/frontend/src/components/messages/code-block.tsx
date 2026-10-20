// Own thin code-block wrapper over shiki's public token API, ported in
// structure from ZCode packages/ui/src/components/ai-elements/code-block.tsx @
// 29628c9a (Apache-2.0): language/copy/wrap header, theme-aware highlighting.
// The highlighting algorithm is NOT copied — shiki 4.0.2 tokenizes, this file
// only renders the tokens. An async highlight result is applied only when its
// (code, language, theme, wrap) version is still current; unknown languages or
// failures keep the plain text. No HTML execution, no remote requests.
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  createHighlighter, type Highlighter, type BundledLanguage, type BundledTheme, type ThemedToken,
} from 'shiki'
import type { ChatTheme } from './markdown-body'

let highlighterPromise: Promise<Highlighter> | undefined
const loadedLanguages = new Set<string>()

/** One shared highlighter for the whole Chat bundle; languages load lazily and
 * idempotently. Both bundled themes load with the singleton so a theme switch
 * never needs a second highlighter instance. */
async function getHighlighter(): Promise<Highlighter> {
  if (!highlighterPromise) {
    highlighterPromise = createHighlighter({ themes: ['github-light', 'github-dark'], langs: [] })
  }
  return highlighterPromise
}

async function loadLanguage(highlighter: Highlighter, language: string): Promise<boolean> {
  if (language === 'text' || loadedLanguages.has(language)) return true
  try {
    const bundled = language as BundledLanguage
    if (!bundledLanguageNames.has(language)) return false
    await highlighter.loadLanguage(bundled)
    loadedLanguages.add(language)
    return true
  } catch {
    return false
  }
}

// The tiny allowlist keeps the first render cheap; anything else stays plain text.
const bundledLanguageNames = new Set([
  'javascript', 'typescript', 'jsx', 'tsx', 'json', 'python', 'go', 'rust', 'java', 'c', 'cpp',
  'csharp', 'bash', 'shell', 'sql', 'yaml', 'toml', 'html', 'css', 'diff', 'markdown', 'kotlin', 'ruby', 'php',
])

interface TokenLine { readonly tokens: readonly ThemedToken[] }

export function ChatCodeBlock({ code, language, theme, wrap, highlight }: {
  code: string
  language: string
  theme: ChatTheme
  wrap: boolean
  /** Streaming fences re-split constantly; highlighting waits for completion. */
  highlight: boolean
}) {
  const shikiTheme: BundledTheme = theme === 'dark' ? 'github-dark' : 'github-light'
  const [lines, setLines] = useState<readonly TokenLine[]>([])
  const [failed, setFailed] = useState(false)
  // The version this async result belongs to; only the current version applies.
  const version = useMemo(() => `${code}\u0000${language}\u0000${shikiTheme}\u0000${wrap}`, [code, language, shikiTheme, wrap])
  const currentVersion = useRef(version)
  currentVersion.current = version

  useEffect(() => {
    if (!highlight || language === 'text') return
    let cancelled = false
    void (async () => {
      try {
        const highlighter = await getHighlighter()
        if (cancelled || currentVersion.current !== version) return
        if (!(await loadLanguage(highlighter, language))) { setFailed(true); return }
        if (cancelled || currentVersion.current !== version) return
        const result = highlighter.codeToTokens(code, { lang: language as BundledLanguage, theme: shikiTheme })
        if (cancelled || currentVersion.current !== version) return
        setLines(result.tokens.map(tokens => ({ tokens })))
        setFailed(false)
      } catch {
        if (!cancelled) setFailed(true)
      }
    })()
    return () => { cancelled = true }
  }, [version, highlight, language, code, shikiTheme])

  const header = (
    <div className="chat-code-head">
      <span className="chat-code-lang">{language}</span>
      <button type="button" className="chat-code-copy" data-code-copy aria-label={`复制代码 (${language})`}
        onClick={event => {
          void navigator.clipboard?.writeText(code)
          const button = event.currentTarget
          button.dataset.copied = 'true'
          window.setTimeout(() => { delete button.dataset.copied }, 1200)
        }}>复制</button>
    </div>
  )
  const body = lines.length > 0 && !failed
    ? (
      <pre className={`chat-code-body ${wrap ? 'chat-code-wrap' : 'chat-code-scroll'}`}>
        <code>
          {lines.map((line, lineIndex) => (
            <span key={lineIndex} className="chat-code-line">
              {line.tokens.map((token, tokenIndex) => (
                <span key={tokenIndex} style={{ color: token.color }}>{token.content}</span>
              ))}
              {'\n'}
            </span>
          ))}
        </code>
      </pre>
    )
    : (
      // Plain text keeps the original bytes: unknown language, highlight failure
      // and the not-yet-highlighted state all render exactly the source text.
      <pre className={`chat-code-body ${wrap ? 'chat-code-wrap' : 'chat-code-scroll'}`}><code>{code}</code></pre>
    )
  return (
    <div className="chat-code" data-code-lang={language} data-highlighted={lines.length > 0 && !failed ? 'true' : 'false'}>
      {header}
      {body}
    </div>
  )
}

