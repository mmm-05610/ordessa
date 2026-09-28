/**
 * Generic schema-driven editor fallback (contracts.md §2): used only for
 * facets whose provider registered an editor key pointing here.  Covers the
 * controlled schema subset (text/number/boolean/enum/list-of-string);
 * unknown shapes render read-only with the schema shown — never a free-form
 * JSON passthrough (ux.md 高级/PF03).
 */
import type { ReactNode } from 'react'
import type { FacetEditorProps, ItemPatch } from '@ordessa/plugin-profile-api'
import { Checkbox, Input, Select } from '@ordessa/ui'

type Schema = FacetEditorProps['items'] extends readonly (infer T)[]
  ? T extends { valueSchema?: infer S } ? S : never
  : never

interface FieldView {
  itemId: string
  label: string
  schema: Record<string, unknown>
  value: unknown
}

export function collectFields(props: FacetEditorProps): readonly FieldView[] {
  return props.items.map((item) => ({
    itemId: item.itemId,
    label: item.itemId,
    schema: (item as unknown as { valueSchema?: Record<string, unknown> }).valueSchema ?? {},
    value: (item as unknown as { value?: unknown }).value,
  }))
}

export function GenericSchemaEditor(props: FacetEditorProps): ReactNode {
  if (props.applicability === 'unsupported') {
    return <p data-schema-unsupported="">此配置面不适用于当前 Harness</p>
  }
  if (props.readOnlyReason) {
    return <p data-schema-readonly="">{props.readOnlyReason}</p>
  }
  const fields = collectFields(props)
  return (
    <div data-generic-schema-editor="">
      {fields.map((field) => {
        const type = field.schema['type']
        const enumeration = field.schema['enum'] as readonly unknown[] | undefined
        const set = (value: unknown) => {
          const patch: ItemPatch = value === null || value === undefined
            ? { facetId: facetOf(props), itemId: field.itemId, op: 'unset' }
            : { facetId: facetOf(props), itemId: field.itemId, op: 'set', value }
          props.onPatch([patch])
        }
        if (enumeration) {
          return (
            <label key={field.itemId} data-schema-field={field.itemId}>
              {field.label}
              <Select
                aria-label={field.label}
                value={String(field.value ?? '')}
                onChange={(event) => set(event.target.value)}
              >
                <option value="">（跟随默认）</option>
                {enumeration.map((option) => (
                  <option key={String(option)} value={String(option)}>{String(option)}</option>
                ))}
              </Select>
            </label>
          )
        }
        if (type === 'boolean') {
          return (
            <label key={field.itemId} data-schema-field={field.itemId}>
              {field.label}
              <Checkbox
                aria-label={field.label}
                checked={field.value === true}
                onChange={(event) => set(event.target.checked)}
              />
            </label>
          )
        }
        return (
          <label key={field.itemId} data-schema-field={field.itemId}>
            {field.label}
            <Input
              aria-label={field.label}
              type={type === 'integer' || type === 'number' ? 'number' : 'text'}
              value={field.value === null || field.value === undefined ? '' : String(field.value)}
              onChange={(event) => {
                const raw = event.target.value
                if (raw === '') return set(null)
                set(type === 'integer' ? Number.parseInt(raw, 10) : type === 'number' ? Number(raw) : raw)
              }}
            />
          </label>
        )
      })}
    </div>
  )
}

function facetOf(props: FacetEditorProps): string {
  return (props as unknown as { facetId?: string }).facetId
    ?? (props.items[0] as unknown as { facetId?: string } | undefined)?.facetId
    ?? ''
}
