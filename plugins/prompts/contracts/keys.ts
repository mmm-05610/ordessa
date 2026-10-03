/**
 * Component keys contributed by the Prompts domain to the platform
 * ui-components registry (docs/design/prompts/contracts.md §3). Pure
 * constants — this file importing must have zero runtime effects (G01).
 */

export const PROMPTS_PLUGIN_ID = 'ordessa.assets.prompts' as const;

/** Workbench Settings page id, inside this domain's namespace. */
export const PROMPTS_SETTINGS_PAGE_ID =
  'ordessa.assets.prompts.settings.library' as const;

/** Profile facet id owned by Prompts (schemaVersion 1, effect instruction). */
export const PROMPTS_PROFILE_FACET_ID = 'assets.prompts' as const;
export const PROMPTS_FACET_SCHEMA_VERSION = 1 as const;

export const PROMPTS_COMPONENT_KEYS = {
  libraryEditor: 'prompts.library-editor.v1',
  profileSelector: 'prompts.profile-selector.v1',
} as const;

/** Harness configuration-adapters contribution facet (T07 surface). */
export const PROMPTS_HARNESS_FACET_ID = 'assets.prompts' as const;

/** The `prompts.*` wire family, one entry per published method. */
export const PROMPTS_METHOD_IDS = [
  'prompts.list',
  'prompts.get',
  'prompts.getRevision',
  'prompts.create',
  'prompts.update',
  'prompts.clone',
  'prompts.archive',
  'prompts.restore',
  'prompts.importText',
  'prompts.exportText',
  'prompts.resolveSnapshot',
  'prompts.preview',
] as const;
export type PromptsMethodId = (typeof PROMPTS_METHOD_IDS)[number];
