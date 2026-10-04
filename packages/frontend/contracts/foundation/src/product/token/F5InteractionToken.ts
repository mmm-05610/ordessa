import { Token } from '@ordessa/extension-api'
import type { InteractionService } from '../../open-environment/f5/types'
import { F5_TOKEN_IDS } from '../../open-environment/f5/tokens'
/** One runtime construction point for the frozen F5 interaction identity. */
export const F5InteractionToken = new Token<InteractionService>(F5_TOKEN_IDS.interactionService)
