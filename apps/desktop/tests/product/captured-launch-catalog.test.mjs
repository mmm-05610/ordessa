import test from 'node:test'
import assert from 'node:assert/strict'
import { captureDesktopLaunchText } from '../../packaging/product/scripts/captured-launch-catalog.mjs'

test('capture passes exact metadata bytes and explicit installed Python once', () => {
  const text = '{"opaque":"中文","wire":1}\n'
  let calls = 0
  const env = { ORDESSA_BUNDLED_ROOT: '/owned/install', SENTINEL: 'retained' }
  assert.equal(captureDesktopLaunchText({ env, spawnImpl(command, argv, options) {
    calls++
    assert.equal(command, '/owned/install/python/bin/python3.12')
    assert.equal(argv[0], '-c')
    assert.match(argv[1], /capture_selected_harness_catalog/)
    assert.match(argv[1], /launch_descriptor_bytes/)
    assert.equal(options.env, env)
    assert.equal(options.timeout, 10000)
    assert.equal(options.maxBuffer, 1048576)
    assert.deepEqual(options.stdio, ['ignore', 'pipe', 'pipe'])
    return { status: 0, stdout: text }
  } }), text)
  assert.equal(calls, 1)
})

test('invalid explicit Python is refused before any process starts', () => {
  for (const python of ['relative/python', '/bad\0python', 42]) {
    let calls = 0
    assert.throws(() => captureDesktopLaunchText({ python, spawnImpl() { calls++ } }),
      /NATIVE_CATALOG_PYTHON_REQUIRED/)
    assert.equal(calls, 0)
  }
})

test('capture failures refuse without retry or alternate catalog', () => {
  for (const result of [{ error: new Error('timeout'), status: null },
    { status: 1, stdout: 'partial' }, { status: 0, stdout: '' },
    { status: 0, stdout: undefined }]) {
    let calls = 0
    assert.throws(() => captureDesktopLaunchText({ python: '/owned/python',
      spawnImpl() { calls++; return result } }), /NATIVE_CATALOG_CAPTURE_FAILED/)
    assert.equal(calls, 1)
  }
})
