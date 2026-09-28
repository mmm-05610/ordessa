/**
 * Lightweight Prompts DTO contract for the frontend (contracts/ is pure:
 * importing it registers nothing, loads nothing and has no side effects —
 * G01). These types mirror `ordessa_prompts.api.dto` one-for-one; the
 * Python<->TS contract test checks the shared constants live here.
 */

export type PromptKind = 'instruction' | 'persona' | 'system-replacement';
export type PromptScopeKind = 'library' | 'profile';

export const KINDS = ['instruction', 'persona', 'system-replacement'] as const;
export const SCOPES = ['library', 'profile'] as const;

/** Frozen capacity rules — must equal the Python constants (contract test). */
export const PROMPT_LIMITS = {
  titleMaxCodepoints: 160,
  descriptionMaxCodepoints: 2000,
  bodyMaxBytes: 128 * 1024,
  maxInstructionsPerSelection: 32,
  snapshotMaxTotalBodyBytes: 1024 * 1024,
  listDefaultPageSize: 50,
  listMaxPageSize: 100,
} as const;

/** The error family frozen by docs/design/prompts/contracts.md §1. */
export const PROMPT_ERROR_CODES = [
  'NOT_FOUND',
  'REVISION_CONFLICT',
  'INVALID_CONTENT',
  'LIMIT_EXCEEDED',
  'REF_KIND_MISMATCH',
  'SCOPE_REFUSED',
  'ARCHIVED_SELECTION',
  'DEPENDENCY_UNAVAILABLE',
  'NATIVE_SEMANTICS_UNSUPPORTED',
  'IDEMPOTENCY_CONFLICT',
  'INVALID_REQUEST',
] as const;
export type PromptErrorCode = (typeof PROMPT_ERROR_CODES)[number];

export interface PromptScopeDto {
  kind: PromptScopeKind;
  profileId?: string;
}

/** Metadata head as served by prompts.list / prompts.get (never a body
 * in lists; get carries bodyBase64 for the authorised editor). */
export interface PromptRecordDto {
  id: string;
  kind: PromptKind;
  scope: PromptScopeDto;
  title: string;
  description: string | null;
  archived: boolean;
  metadataVersion: number;
  latestRevision: number;
  createdAt: string;
  updatedAt: string;
  bodyBase64?: string;
  sha256?: string;
}

export interface PromptRevisionDto {
  promptId: string;
  revision: number;
  sha256: string;
  createdAt: string;
  byteSize: number;
  bodyBase64?: string;
}

/** First release tracks latest only; no user-facing pin. */
export interface PromptRefDto {
  promptId: string;
  track: 'latest';
}

export interface PromptSelectionDto {
  instructions: PromptRefDto[];
  persona: PromptRefDto | null;
  systemReplacement: PromptRefDto | null;
}

export interface ResolvedPromptDto {
  promptId: string;
  kind: PromptKind;
  revision: number;
  sha256: string;
  title: string;
  byteSize: number;
  bodyBase64?: string;
}

export interface PromptSnapshotDto {
  snapshotId: string;
  serverScope: string;
  compositionVersion: number;
  contentDigest: string;
  profileRevision: number | null;
  overlayRevision: number | null;
  totalBodyBytes: number;
  instructions: string[];
  persona: string | null;
  systemReplacement: string | null;
  resolved: ResolvedPromptDto[];
}

export interface ListResultDto {
  items: PromptRecordDto[];
  limit: number;
  offset: number;
  nextOffset: number | null;
}
