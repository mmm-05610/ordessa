/**
 * C-02 — the launch seam: the bundled runtime, the handshake, the state
 * machine, and "only ever kill what I spawned".
 *
 * The lifecycle tests drive a REAL child process (`node -e ...`) rather than
 * a hand-written fake, because the properties under test are about process
 * identity: which pid exists, which group it is in, and what happens to an
 * unrelated process. A fake child would agree with any implementation.
 */
import { spawn, type ChildProcess } from 'node:child_process'
import { chmodSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { DATA_ROOT_ENV } from '../src/data-root.js'
import { BundledRuntimeMissing, LaunchError, ServerStartTimeout } from '../src/errors.js'
import { ServerBridge, parseHandshake, serverInstanceId } from '../src/lifecycle.js'
import { resolveBundledRuntime, serverCommand } from '../src/runtime.js'

let scratch: string

beforeEach(() => {
  scratch = mkdtempSync(path.join(tmpdir(), 'sb-lifecycle-'))
})

afterEach(() => {
  rmSync(scratch, { recursive: true, force: true })
})

/** A bundled root that passes the completeness check, with a runnable `python`. */
function bundledRoot(withBridge = true): string {
  const root = path.join(scratch, 'bundle')
  mkdirSync(path.join(root, 'python'), { recursive: true })
  mkdirSync(path.join(root, 'bin'), { recursive: true })
  mkdirSync(path.join(root, 'harnesses'), { recursive: true })
  // The bridge is a real executable file, because the check is `isFile`.
  const bridge = path.join(root, 'bin', 'acp')
  if (withBridge) {
    writeFileSync(bridge, '#!/bin/sh\nexit 0\n')
    chmodSync(bridge, 0o755)
  }
  return root
}

function envFor(root: string): Record<string, string> {
  return { [DATA_ROOT_ENV]: path.join(scratch, 'data-root'), ORDESSA_BUNDLED_ROOT: root }
}

describe('C-02 §6 — the bundled runtime is checked before anything is spawned', () => {
  it('resolves the three directories and the bridge from a complete root', () => {
    const resolved = resolveBundledRuntime(envFor(bundledRoot()))
    expect(path.basename(resolved.python)).toBe('python')
    expect(path.basename(resolved.bin)).toBe('bin')
    expect(path.basename(resolved.harnesses)).toBe('harnesses')
    expect(path.basename(resolved.acpBridge)).toBe('acp')
    expect(serverCommand(resolved)[1]).toBe('-m')
  })

  it('refuses a missing bin/acp BY NAME, and never reaches "half-usable"', () => {
    let thrown: BundledRuntimeMissing | null = null
    try {
      resolveBundledRuntime(envFor(bundledRoot(false)))
    } catch (error) {
      thrown = error as BundledRuntimeMissing
    }
    expect(thrown?.code).toBe('BUNDLED_RUNTIME_MISSING')
    expect(thrown?.missing).toContain('bin/acp')
    // A refusal that quoted the install path would leak the layout into a UI.
    expect(thrown?.message).not.toContain(scratch)
  })

  it('refuses a missing harnesses/ directory too', () => {
    const root = bundledRoot()
    rmSync(path.join(root, 'harnesses'), { recursive: true, force: true })
    expect(() => resolveBundledRuntime(envFor(root))).toThrow(BundledRuntimeMissing)
  })

  it('refuses at START, before any process exists', async () => {
    const bridge = new ServerBridge({
      env: envFor(bundledRoot(false)),
      dataRoot: path.join(scratch, 'data-root'),
      readyTimeoutMs: 500,
    })
    await expect(bridge.start()).rejects.toBeInstanceOf(BundledRuntimeMissing)
    expect(bridge.state).toBe('idle')
  })
})

describe('C-02 §3.1 — the handshake line is read strictly', () => {
  it('accepts exactly the documented object', () => {
    const line = JSON.stringify({
      event: 'listening',
      origin: 'http://127.0.0.1:41207',
      serverId: 'server_abc',
      pid: 4321,
    })
    expect(parseHandshake(line)).toEqual({
      event: 'listening',
      origin: 'http://127.0.0.1:41207',
      serverId: 'server_abc',
      pid: 4321,
    })
  })

  it('refuses a line with an extra key, a foreign origin or a bad pid', () => {
    const extra = JSON.stringify({
      event: 'listening',
      origin: 'http://127.0.0.1:1',
      serverId: 's',
      pid: 1,
      extra: true,
    })
    const foreign = JSON.stringify({
      event: 'listening',
      origin: 'http://10.0.0.5:1',
      serverId: 's',
      pid: 1,
    })
    const noPath = JSON.stringify({ event: 'listening', origin: 'http://127.0.0.1:1/wire', serverId: 's', pid: 1 })
    const zeroPid = JSON.stringify({ event: 'listening', origin: 'http://127.0.0.1:1', serverId: 's', pid: 0 })
    for (const line of [extra, foreign, noPath, zeroPid, 'not json', '', '[]']) {
      expect(parseHandshake(line)).toBeNull()
    }
  })
})

describe('C-02 §3.2 — the port is not the identity', () => {
  it('scopes by origin AND serverId, and a new origin does not change the id', () => {
    expect(serverInstanceId('http://127.0.0.1:1', 'server_x')).toBe('http://127.0.0.1:1|server_x')
    // Same Server, different port after a restart: the persistent half is the id.
    expect(serverInstanceId('http://127.0.0.1:2', 'server_x').split('|')[1]).toBe(
      serverInstanceId('http://127.0.0.1:1', 'server_x').split('|')[1],
    )
  })
})

/** Spawn a child that behaves the way the test needs, in its own group. */
function fakeServer(behaviour: 'ready' | 'exit-early' | 'silent' | 'garbage'): ChildProcess {
  const scripts: Record<typeof behaviour, string> = {
    ready:
      'process.stdout.write(JSON.stringify({event:"listening",origin:"http://127.0.0.1:45999",serverId:"server_test",pid:process.pid})+"\\n");' +
      'setInterval(()=>{},1000);',
    'exit-early': 'process.exit(3);',
    // A child that binds nothing and says nothing: a start timeout, not a crash.
    silent: 'setInterval(()=>{},1000);',
    garbage: 'process.stdout.write("hello, I am not a handshake\\n");setInterval(()=>{},1000);',
  }
  return spawn(process.execPath, ['-e', scripts[behaviour]], {
    stdio: ['ignore', 'pipe', 'pipe'],
    detached: true,
  })
}

describe('C-02 §5 — the state machine over real processes', () => {
  async function withBridge(child: ChildProcess, timeoutMs: number): Promise<ServerBridge> {
    // The bridge owns the child it spawns, so the test hands the bridge a
    // spawn function that returns THIS process and lets the bridge drive it.
    const bridge = new ServerBridge({
      env: envFor(bundledRoot()),
      dataRoot: path.join(scratch, 'data-root'),
      readyTimeoutMs: timeoutMs,
      probe: async () => true,
      spawnProcess: (() => child) as unknown as typeof spawn,
    })
    return bridge
  }

  it('reaches ready only after the handshake AND the probe succeed', async () => {
    const bridge = await withBridge(fakeServer('ready'), 5000)
    const instance = await bridge.start()
    expect(bridge.state).toBe('ready')
    expect(instance.origin).toBe('http://127.0.0.1:45999')
    expect(instance.scope).toBe('http://127.0.0.1:45999|server_test')
    await bridge.stop(200)
    expect(bridge.state).toBe('stopped')
  })

  it('refuses SERVER_EXITED_EARLY with the exit code, when the child dies first', async () => {
    const bridge = await withBridge(fakeServer('exit-early'), 5000)
    let thrown: LaunchError | null = null
    try {
      await bridge.start()
    } catch (error) {
      thrown = error as LaunchError
    }
    expect(thrown?.code).toBe('SERVER_EXITED_EARLY')
    expect((thrown as unknown as { exitCode: number }).exitCode).toBe(3)
    expect(bridge.state).toBe('failed')
  })

  it('refuses a malformed handshake rather than a timeout, when a line arrives', async () => {
    const bridge = await withBridge(fakeServer('garbage'), 5000)
    await expect(bridge.start()).rejects.toMatchObject({ logTail: 'hello, I am not a handshake' })
  })

  it('refuses SERVER_START_TIMEOUT when the child never speaks', async () => {
    const bridge = await withBridge(fakeServer('silent'), 400)
    let thrown: LaunchError | null = null
    try {
      await bridge.start()
    } catch (error) {
      thrown = error as LaunchError
    }
    expect(thrown).toBeInstanceOf(ServerStartTimeout)
    expect(thrown?.code).toBe('SERVER_START_TIMEOUT')
  })

  it('refuses when the readiness probe says no, even though the handshake was fine', async () => {
    const child = fakeServer('ready')
    const bridge = new ServerBridge({
      env: envFor(bundledRoot()),
      dataRoot: path.join(scratch, 'data-root'),
      readyTimeoutMs: 400,
      probe: async () => false,
      spawnProcess: (() => child) as unknown as typeof spawn,
    })
    await expect(bridge.start()).rejects.toBeInstanceOf(ServerStartTimeout)
    expect(bridge.state).toBe('failed')
  })
})

describe('C-02 §5 — stopping kills only what this host spawned', () => {
  it('leaves an unrelated process on the machine alive', async () => {
    const bystander = spawn(process.execPath, ['-e', 'setInterval(()=>{},1000)'], {
      stdio: 'ignore',
      detached: true,
    })
    const bridge = new ServerBridge({
      env: envFor(bundledRoot()),
      dataRoot: path.join(scratch, 'data-root'),
      readyTimeoutMs: 5000,
      probe: async () => true,
      spawnProcess: (() => fakeServer('ready')) as unknown as typeof spawn,
    })
    await bridge.start()
    await bridge.stop(200)
    // The bystander was never a child of this bridge, so it must survive.
    expect(isAlive(bystander.pid as number)).toBe(true)
    bystander.kill('SIGKILL')
  })

  it('takes down a grandchild with the process group it created', async () => {
    // The Server forks a helper; stopping must not orphan it holding the port.
    const script =
      'const {spawn}=require("node:child_process");' +
      'const child=spawn(process.execPath,["-e","setInterval(()=>{},1000)"],{stdio:"ignore"});' +
      'process.stdout.write(JSON.stringify({event:"listening",origin:"http://127.0.0.1:45998",serverId:"s",pid:process.pid})+"\\n");' +
      'setInterval(()=>{},1000);'
    const parent = spawn(process.execPath, ['-e', script], {
      stdio: ['ignore', 'pipe', 'pipe'],
      detached: true,
    })
    const grandchildPid = await new Promise<number>((resolve) => {
      const timer = setTimeout(() => resolve(-1), 3000)
      const poll = setInterval(async () => {
        try {
          const { execFileSync } = await import('node:child_process')
          const out = execFileSync('pgrep', ['-P', String(parent.pid)], { encoding: 'utf8' })
          const first = out.trim().split('\n')[0]
          if (first) {
            clearInterval(poll)
            clearTimeout(timer)
            resolve(Number(first))
          }
        } catch {
          /* not yet */
        }
      }, 100)
    })
    const bridge = new ServerBridge({
      env: envFor(bundledRoot()),
      dataRoot: path.join(scratch, 'data-root'),
      readyTimeoutMs: 5000,
      probe: async () => true,
      spawnProcess: (() => parent) as unknown as typeof spawn,
    })
    await bridge.start()
    await bridge.stop(500)
    await new Promise((resolve) => setTimeout(resolve, 300))
    if (grandchildPid > 0) expect(isAlive(grandchildPid)).toBe(false)
  })
})

function isAlive(pid: number): boolean {
  try {
    process.kill(pid, 0)
    return true
  } catch {
    return false
  }
}
