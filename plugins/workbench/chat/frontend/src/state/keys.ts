// Chat-internal component keys (the four public display keys live in the
// chat-api contract; these are chat's own default-provider widgets).
import { defineChatComponentKey } from '@extensions/ordessa.chat-api/contract.js'

export const connectionBadgeKey = defineChatComponentKey<{ readonly status: string }>('ordessa.chat.connection-badge', 1)
