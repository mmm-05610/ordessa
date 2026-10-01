import test from 'node:test'
import assert from 'node:assert/strict'
import {claudeProviderAuthToken} from './claude-auth.mjs'

test('private provider key replaces the upstream local-login placeholder', () => {
  for (const name of ['authorization', 'Authorization'])
    assert.equal(claudeProviderAuthToken({[name]: 'Bearer synthetic-key'}), 'synthetic-key')
  assert.equal(claudeProviderAuthToken({}), 'acp-proxy')
})
test('ambiguous or malformed authorization fails without echoing secrets', () => {
  for (const headers of [{authorization:'secret'}, {authorization:'Bearer bad\nkey'},
    {authorization:'Bearer a',Authorization:'Bearer b'}])
    assert.throws(() => claudeProviderAuthToken(headers), {message:'Invalid bounded Claude provider authentication'})
})
