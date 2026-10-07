/**
 * Service token.  Presence of this token in a scope means a real Profile
 * backend is bound; absence means Profile UI must stay absent — consumers
 * never substitute a fake (R07 / contracts.md §4).
 */
import { Token } from '@ordessa/extension-api'
import type { ProfileServiceClient } from './service'

export const ProfileServiceToken = new Token<ProfileServiceClient>('ordessa.profile.service.v1')
