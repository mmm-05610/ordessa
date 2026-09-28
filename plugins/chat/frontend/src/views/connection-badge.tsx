// Chat default provider's connection badge — a chat-owned toolbar widget that
// exercises the contribution path with a real component.
export function ConnectionBadge({ status }: { status: string }) {
  return <span className="chat-connection-badge" data-status={status} data-testid="chat-connection-badge">{status}</span>
}
