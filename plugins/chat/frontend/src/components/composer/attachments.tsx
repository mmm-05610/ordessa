// Attachment strip for the composer (input-spec US7). Cards show phase
// (selected/preparing/ready/failed), a thumbnail for images (local object URL
// only), name/size/type fallback when no preview exists, and remove/retry
// actions. Unready items block the send with a visible reason (the gate lives
// in state/draft.ts). Directory items are references only — never expanded.
import type { ChatInputItem } from '@extensions/ordessa.chat-api/contract.js'

const phaseLabels = { selected: '已选择', preparing: '准备中…', ready: '已就绪', failed: '失败' } as const

export function AttachmentStrip({ items, onRemove, onRetry, onPreview }: {
  items: readonly ChatInputItem[]
  onRemove: (itemId: string) => void
  onRetry: (itemId: string) => void
  onPreview?: (itemId: string) => void
}) {
  if (items.length === 0) return null
  return (
    <div className="chat-attachments" data-testid="chat-attachments">
      {items.map(item => (
        <div key={item.id} className="chat-attachment" data-item-id={item.id} data-kind={item.kind}
          data-phase={item.phase.state}>
          {item.kind === 'image' && item.previewUrl && item.phase.state !== 'failed' ? (
            <button type="button" className="chat-attachment-thumb" aria-label={`预览 ${item.displayName}`}
              onClick={() => onPreview?.(item.id)}>
              <img src={item.previewUrl} alt={item.displayName} />
            </button>
          ) : (
            <span className="chat-attachment-glyph" aria-hidden="true">{item.kind === 'directory-reference' ? '📁' : '📄'}</span>
          )}
          <span className="chat-attachment-meta">
            <span className="chat-attachment-name" title={item.displayName}>{item.displayName}</span>
            <span className="chat-attachment-phase" data-phase={item.phase.state}>
              {phaseLabels[item.phase.state]}
              {item.phase.state === 'failed' && <span className="chat-attachment-reason">：{item.phase.reason}</span>}
            </span>
          </span>
          {item.phase.state === 'failed' && (
            <button type="button" className="chat-ghost-action" data-action="retry-attachment"
              aria-label={`重试 ${item.displayName}`} onClick={() => onRetry(item.id)}>重试</button>
          )}
          <button type="button" className="chat-ghost-action" data-action="remove-attachment"
            aria-label={`移除 ${item.displayName}`} onClick={() => onRemove(item.id)}>移除</button>
        </div>
      ))}
    </div>
  )
}

/** Minimal preview dialog: name/size/type and, when available, the local
 * thumbnail. Content is never executed (input-contracts §5). */
export function AttachmentPreview({ item, onClose }: { item: ChatInputItem; onClose: () => void }) {
  return (
    <div className="chat-preview-backdrop" data-testid="chat-attachment-preview" onClick={onClose}>
      <div className="chat-preview" role="dialog" aria-label={`预览 ${item.displayName}`} onClick={event => event.stopPropagation()}>
        <header className="chat-preview-head">
          <strong>{item.displayName}</strong>
          <button type="button" className="chat-ghost-action" data-action="close-preview" onClick={onClose}>关闭</button>
        </header>
        <div className="chat-preview-body">
          {item.kind === 'image' && item.previewUrl
            ? <img src={item.previewUrl} alt={item.displayName} />
            : <dl>
                <dt>类型</dt><dd>{item.kind === 'directory-reference' ? '目录引用' : item.mimeType ?? '文件'}</dd>
                {item.size !== undefined && <><dt>大小</dt><dd>{item.size} 字节</dd></>}
              </dl>}
        </div>

      </div>
    </div>
  )
}
