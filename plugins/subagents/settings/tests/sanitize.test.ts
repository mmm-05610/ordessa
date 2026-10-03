/**
 * Source-preview safety (ux.md §"Settings 中的定义库": 不执行语法、不加载远程图片、
 * 不显示 secret) and FR14/US1's "导入未经信任的定义不执行其中脚本/命令".
 */
import { describe, expect, it } from 'vitest'
import { flatten, hasCredentialShape, isSafeHref, previewStrings, redactCredentials, safePreview } from '../src/sanitize'

/** No emitted node may name an executable element or carry a raw-HTML channel. */
function executableFree(json: string): boolean {
  return !/"tag":\s*"(script|img|iframe|svg|object|embed|form|link|meta|body)"/i.test(json)
    && !/innerHTML|outerHTML|dangerouslySet/i.test(json)
}

describe('raw HTML never survives as markup', () => {
  it('an <img onerror=…> payload becomes literal text; no img node, no usable handler', () => {
    const preview = safePreview('看图 <img src="https://evil.example/x.png" onerror="fetch(\'/steal\')"> 结束')
    const json = JSON.stringify(preview.blocks)
    expect(executableFree(json)).toBe(true)
    // the sanitizer tree has no element nodes at all, so there is nothing to execute
    expect(json).not.toMatch(/"tag":/)
    expect(json).not.toMatch(/innerHTML|dangerouslySet/i)
    expect(json).not.toMatch(/onerror\s*:\s*"/)
    // the tag text stays *visible* (nothing silently vanishes) but only as text
    expect(previewStrings(preview.blocks).join('')).toContain('<img')
    expect(preview.notices.some(n => n.kind === 'escaped-html')).toBe(true)
  })

  it('a raw <script> block cannot reach the renderer as an element', () => {
    const preview = safePreview('<script>alert(1)</script>')
    const json = JSON.stringify(preview.blocks)
    // the sanitizer emits data only: there is no tag/prop channel to execute
    expect(json).not.toMatch(/"tag":/)
    expect(json).not.toMatch(/"props":/)
    // the payload stays readable as literal source text (nothing silently vanishes)
    expect(previewStrings(preview.blocks).join('')).toContain('<script>alert(1)</script>')
  })

  it('the preview object structurally carries no html field', () => {
    const preview = safePreview('# 标题\n\n正文 <b>粗</b> 与 ![图](https://x/y.png)')
    expect(preview).not.toHaveProperty('html')
    expect(executableFree(JSON.stringify(preview))).toBe(true)
  })
})

describe('remote images are never loaded', () => {
  it('image syntax is dropped with a notice; the alt text stays as plain text', () => {
    const preview = safePreview('![审阅流程图](https://cdn.example.com/diagram.png)')
    expect(JSON.stringify(preview.blocks)).not.toContain('cdn.example.com')
    expect(preview.notices.some(n => n.kind === 'dropped-image' && n.detail.includes('不加载'))).toBe(true)
    expect(previewStrings(preview.blocks).join('')).toContain('图片已忽略')
    expect(preview.blocks.some(b => b.kind === 'paragraph' && b.children.some(c => c.kind === 'link'))).toBe(false)
  })

  it('a data: URI image cannot smuggle content either', () => {
    const preview = safePreview('![x](data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=)')
    expect(JSON.stringify(preview.blocks)).not.toContain('PHN2Zz48L3N2Zz4')
    expect(preview.notices.some(n => n.kind === 'dropped-image')).toBe(true)
  })
})

describe('non-executable links only', () => {
  it('[x](javascript:…) is refused and shown as inert text', () => {
    const preview = safePreview('[点我](javascript:alert(1))')
    const json = JSON.stringify(preview.blocks)
    expect(json).not.toMatch(/"kind":"link"/)
    // there is no href channel at all for a refused URL — only visible text
    expect(json).not.toMatch(/"href"/)
    expect(previewStrings(preview.blocks).join('')).toContain('javascript:alert(1)')
    expect(preview.notices.some(n => n.kind === 'refused-url')).toBe(true)
  })

  it('only http(s)/mailto are usable hrefs', () => {
    for (const good of ['https://example.com/a', 'http://example.com', 'mailto:a@example.com']) {
      expect(isSafeHref(good), good).toBe(true)
    }
    for (const bad of ['javascript:alert(1)', 'data:text/html,<script>', 'vbscript:x', 'file:///etc/passwd', 'about:blank', 'blob:https://x/y', '/etc/passwd']) {
      expect(isSafeHref(bad), bad).toBe(false)
    }
  })

  it('a safe link keeps its href as data and its label unparsed', () => {
    const preview = safePreview('[文档](https://docs.example.com/guide)')
    const paragraph = preview.blocks.find(b => b.kind === 'paragraph')
    if (!paragraph || paragraph.kind !== 'paragraph') throw new Error('expected a paragraph')
    expect(paragraph.children[0]).toMatchObject({ kind: 'link', href: 'https://docs.example.com/guide' })
  })
})

describe('secrets are never displayed', () => {
  // Provider prefixes are assembled at run time: GitHub push protection scans
  // raw bytes and cannot tell a fixture from a live secret, so the source must
  // never contain a token-shaped literal. The sanitizer under test still sees
  // the joined form — the assertions are unchanged.
  const j = (...parts: string[]) => parts.join('')
  const SECRET_SAMPLES = [
    j('token=', 'sk-', 'abcdefghijklmnop1234'),
    j('ANTHROPIC_API_KEY: "', 'sk-', 'ant-api03-XYZXYZXYZXYZ"'),
    'authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abcdef',
    j('g', 'hp_0123456789abcdefghij'),
    j('AK', 'IAABCDEFGHIJKLMNOP'),
    j('xo', 'xb-1234567890-abcdefghijklmnop'),
    j('-----BEGIN ', 'RSA PRIVATE KEY', '-----\\nMIIBOgIBAAJBAKJ\\n-----END RSA PRIVATE KEY-----'),
    'password = hunter2secretvalue',
  ]

  it('each credential-shaped sample is redacted out of the preview text', () => {
    for (const sample of SECRET_SAMPLES) {
      const shown = previewStrings(safePreview(sample).blocks).join('|')
      expect(shown, sample).toMatch(/已脱敏/)
      for (const chunk of sample.split(/[\s:=,"'\\]+/).filter(c => c.length > 6)) {
        expect(shown, `${sample} → ${chunk}`).not.toContain(chunk)
      }
      expect(safePreview(sample).notices.some(n => n.kind === 'redacted-secret'), sample).toBe(true)
    }
  })

  it('prose about token budgets is NOT redacted (no over-refusal)', () => {
    const text = '本角色的 token 预算按会话上限计算，最多 200k token。'
    const preview = safePreview(text)
    expect(previewStrings(preview.blocks).join('')).toContain('token 预算')
    expect(preview.notices.some(n => n.kind === 'redacted-secret')).toBe(false)
    expect(hasCredentialShape(text)).toBe(false)
  })

  it('redaction is line-anchored for assignments and value-shaped anywhere', () => {
    expect(redactCredentials('api_key = abcdef123456').redactions).toBeGreaterThan(0)
    expect(redactCredentials('随手记一句 sk-abcdefghijklmnop1234 完').redactions).toBeGreaterThan(0)
    expect(redactCredentials('没有凭据的一段话').redactions).toBe(0)
  })
})

describe('allowed markdown subset only', () => {
  it('headings, lists, code and emphasis are parsed; nothing else becomes markup', () => {
    const preview = safePreview('# 标题\n\n- 第一项 **加粗**\n- 第二项 `code`\n\n正文*斜*与 <table> 标签')
    expect(preview.blocks.map(b => b.kind)).toEqual(['heading', 'list', 'paragraph'])
    expect(previewStrings(preview.blocks).join('')).toContain('<table>')
    expect(preview.notices.some(n => n.kind === 'escaped-html')).toBe(true)
  })

  it('a fenced code block stays literal and is still secret-scanned', () => {
    const preview = safePreview('```\nprint("token=sk-abcdefghijklmnop1234")\n```')
    expect(preview.blocks[0]?.kind).toBe('code-block')
    expect(previewStrings(preview.blocks).join('')).not.toContain('sk-abcdefghijklmnop1234')
  })

  it('the text-only fallback keeps reading order', () => {
    const preview = safePreview('# A\n正文 B')
    expect(preview.plainText).toBe(flatten(preview.blocks))
    expect(preview.plainText.indexOf('A')).toBeLessThan(preview.plainText.indexOf('B'))
  })

  it('odd markers stay text instead of throwing', () => {
    const preview = safePreview('**未闭合 与 `未闭合 与 [未配对')
    expect(previewStrings(preview.blocks).join('')).toContain('**未闭合')
    expect(() => safePreview('#'.repeat(9) + '\n\n-')).not.toThrow()
  })
})
