import { expect, it } from 'vitest'
import { productServerArgs } from '../src/product-args'

it('passes product argv as immutable opaque strings, never splits shell text', () => {
  expect(productServerArgs({})).toEqual([])
  const args = productServerArgs({ ORDESSA_SERVER_ARGS_JSON: '["--domain-option", "a b;$HOME"]' })
  expect(args).toEqual(['--domain-option', 'a b;$HOME'])
  expect(Object.isFrozen(args)).toBe(true)
})

it.each(['', 'null', '{}', '"--option"', '[1]', '["a\\u0000b"]',
  JSON.stringify(Array(257).fill('a')), JSON.stringify(['a'.repeat(65536)])])(
  'refuses malformed product argv: %s', source => {
    expect(() => productServerArgs({ ORDESSA_SERVER_ARGS_JSON: source })).toThrow('SERVER_PRODUCT_ARGS_INVALID')
  })
