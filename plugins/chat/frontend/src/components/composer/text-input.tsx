// Composer text input, ported from ZCode
// packages/ui/src/components/ai-elements/prompt-input-textarea.tsx @ 29628c9a
// (derived from vercel/ai-elements, Apache-2.0 — see THIRD-PARTY-NOTICES.md).
// Ported: the isComposing + nativeEvent.isComposing double-guard (Chinese IME
// Enter never submits), Shift+Enter newline, external onKeyDown runs first and
// a defaultPrevented event skips internal handling (the suggestion panel
// consumes Enter/Tab before the input acts), submit-button-disabled check
// before requestSubmit, Backspace-removes-last-attachment on empty input,
// paste-into-attachments conflation. Dropped: the upstream controller and
// attachment store — Chat hands in its own callbacks (chat-api ComposerProps);
// the input stores no draft of its own.
import { useCallback, useState, type ClipboardEvent, type KeyboardEvent } from 'react'

export interface ChatTextInputProps {
  readonly value: string
  readonly editable: boolean
  readonly placeholder: string
  readonly submitDisabled: boolean
  readonly onTextChange: (value: string) => void
  readonly onSubmit: () => void
  /** Suggestion panel is open; the panel decides whether to consume the key. */
  readonly panelConsumeKey?: (event: KeyboardEvent<HTMLTextAreaElement>) => boolean
  readonly onCaretChange?: (caret: number) => void
  readonly removeLastAttachment?: () => void
  readonly addPastedFiles?: (files: readonly File[]) => void
  readonly testid?: string
}

export function ChatTextInput(props: ChatTextInputProps) {
  const [isComposing, setIsComposing] = useState(false)

  const reportCaret = (element: HTMLTextAreaElement) => props.onCaretChange?.(element.selectionStart ?? 0)

  const handleKeyDown = useCallback((event: KeyboardEvent<HTMLTextAreaElement>) => {
    // External handler first; defaultPrevented means the panel consumed it.
    if (props.panelConsumeKey?.(event)) return
    if (event.defaultPrevented) return

    if (event.key === 'Enter') {
      if (isComposing || event.nativeEvent.isComposing) return
      if (event.shiftKey) return
      event.preventDefault()
      if (props.submitDisabled) return
      props.onSubmit()
      return
    }
    if (event.key === 'Backspace' && event.currentTarget.value === '' && props.removeLastAttachment) {
      event.preventDefault()
      props.removeLastAttachment()
    }
  }, [props, isComposing])

  const handlePaste = useCallback((event: ClipboardEvent<HTMLTextAreaElement>) => {
    const items = event.clipboardData?.items
    if (!items || !props.addPastedFiles) return
    const files: File[] = []
    for (const item of items) {
      if (item.kind === 'file') {
        const file = item.getAsFile()
        if (file) files.push(file)
      }
    }
    if (files.length > 0) {
      event.preventDefault()
      props.addPastedFiles(files)
    }
  }, [props])

  return (
    <textarea
      className="chat-input-text"
      data-testid={props.testid}
      aria-label={props.placeholder}
      placeholder={props.placeholder}
      value={props.value}
      disabled={!props.editable}
      onCompositionStart={() => setIsComposing(true)}
      onCompositionEnd={() => setIsComposing(false)}
      onKeyDown={handleKeyDown}
      onPaste={handlePaste}
      onSelect={event => reportCaret(event.currentTarget)}
      onClick={event => reportCaret(event.currentTarget)}
      onKeyUp={event => reportCaret(event.currentTarget)}
      onChange={event => { props.onTextChange(event.currentTarget.value); reportCaret(event.currentTarget) }}
    />
  )
}
