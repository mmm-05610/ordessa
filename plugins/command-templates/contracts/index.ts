/**
 * Command-templates frontend domain contract — TYPES ONLY (pure imports).
 *
 * Mirrors `ordessa_command_templates.api` so a Settings/Chat surface can speak
 * the domain shapes without importing host internals. This module has no
 * runtime: it declares the DTOs the Server `commandTemplates.*` family returns
 * and the argument shape it accepts. It deliberately does NOT declare a Chat
 * `addInputSource` or any draft-insert action — those are an unpublished Chat
 * seam (see specs/011-q2-prompts-commands/command-templates/api-requests.md)
 * and must come from the Chat owner, not be fabricated here (gate G00).
 *
 * Nothing below imports `@ordessa/*` or `@extensions/*`: the frontend depends on
 * the platform only through separately-published contracts, never on this
 * domain's server code.
 */

export type ParameterKind = 'string' | 'enum' | 'integer' | 'project-ref';

export interface ParameterSpec {
  name: string;
  kind: ParameterKind;
  required: boolean;
  default?: string | number | null;
  maxLength?: number;
  minimum?: number;
  maximum?: number;
  choices?: readonly string[];
}

export interface Template {
  id: string;
  ownerPrincipal: string;
  displayName: string;
  slug: string;
  description: string;
  origin: 'user' | 'imported';
  latestRevision: number;
  entityVersion: number;
  createdAt: string;
  archivedAt?: string | null;
}

export interface TemplateRevision {
  templateId: string;
  revision: number;
  /** Body text is only present on an explicit get, never in a list payload. */
  body?: string;
  parameters?: readonly ParameterSpec[];
  contentDigest: string;
  approvedAt?: string | null;
  createdAt: string;
}

export type AssignmentScope =
  | 'user-global' | 'user-harness' | 'project' | 'project-harness' | 'profile';

export interface Assignment {
  scope: AssignmentScope;
  scopeIdentity: string;
  harnessId?: string | null;
  templateId: string;
  state: 'enable' | 'disable';
  pinnedRevision?: number | null;
  entityVersion: number;
  updatedAt: string;
}

export type EffectiveState = 'available' | 'disabled' | 'blocked-policy' | 'unavailable';

export interface EffectiveEntry {
  templateId: string;
  displayName: string;
  slug: string;
  state: EffectiveState;
  source: AssignmentScope | 'org-policy' | null;
  scopeIdentity: string | null;
  pinnedRevision: number | null;
  /** A real absence reason; never hidden behind an empty list (FR-08). */
  reason?: string | null;
}

export interface Resolution {
  available: readonly EffectiveEntry[];
  excluded: readonly EffectiveEntry[];
  /** Slugs claimed by more than one distinct id — surfaced, not auto-resolved. */
  conflicts: readonly string[];
}

/** A render preview: bytes + digest, no side effects, nothing sent. */
export interface RenderPreview {
  text: string;
  renderedBytes: number;
  digest: string;
}

/** The stable refusal codes the UI must render specifically (contracts.md). */
export type CommandTemplateErrorCode =
  | 'IDENTIFIER_INVALID' | 'DOCUMENT_INVALID' | 'UNAUTHORIZED_TARGET'
  | 'CONTENT_MISSING' | 'REVISION_UNAPPROVED' | 'PARAMETER_INVALID'
  | 'PARAMETER_UNKNOWN' | 'PROJECT_REF_UNRESOLVED' | 'OUTPUT_LIMIT'
  | 'NAME_CONFLICT' | 'STALE_PREVIEW' | 'CAS_CONFLICT' | 'IDEMPOTENCY_CONFLICT'
  | 'CONTRIBUTOR_GONE' | 'NATIVE_UNSUPPORTED' | 'CAPABILITY_UNKNOWN'
  | 'PROJECTION_REFUSED';
