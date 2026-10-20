/** Read exact selected launch bytes through the actual Server public capture.
 * No services, models, registry scan, copied catalog or alternate encoding.
 */
import { spawnSync } from 'node:child_process'
import path from 'node:path'
import { layout } from '../../lib/layout.mjs'

export function captureDesktopLaunchText({ env = process.env, python,
  spawnImpl = spawnSync } = {}) {
  const executable = python ?? env.ORDESSA_CATALOG_PYTHON ?? env.ORDESSA_TEST_PYTHON
    ?? path.join(env.ORDESSA_BUNDLED_ROOT ?? layout.prefix,'python/bin/python3.12')
  if (typeof executable !== 'string' || !path.isAbsolute(executable) || executable.includes('\0'))
    throw new Error('NATIVE_CATALOG_PYTHON_REQUIRED')
  const program = 'import sys; from ordessa_server.composition.selected_harness_catalog import capture_selected_harness_catalog; sys.stdout.buffer.write(capture_selected_harness_catalog().launch_descriptor_bytes)'
  const result = spawnImpl(executable,['-c',program],{
    env, encoding:'utf8', maxBuffer:1048576, timeout:10000,
    stdio:['ignore','pipe','pipe'],
  })
  if (result.error || result.status !== 0 || typeof result.stdout !== 'string' || !result.stdout)
    throw new Error('NATIVE_CATALOG_CAPTURE_FAILED')
  return result.stdout
}
