// Chat default provider's connection badge — a chat-owned toolbar widget that
// exercises the contribution path with a real component.
export function ConnectionBadge({ status }: { status: string }) {
  const label = status === 'connected' ? '已连接' : status === 'connecting' ? '连接中' : status === 'disconnected' ? '连接已断开' : status
  return <span className="chat-connection-badge" data-status={status} data-testid="chat-connection-badge" role="status" aria-label={label} title={label}>
    <span className={status === 'connected' ? 'chat-sr-only' : undefined}>{status}</span>
  </span>
}
