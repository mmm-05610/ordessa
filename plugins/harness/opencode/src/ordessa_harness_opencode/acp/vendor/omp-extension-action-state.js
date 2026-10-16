import { execFile } from "node:child_process"
import { createHash } from "node:crypto"
import { readFile, stat } from "node:fs/promises"
import { homedir } from "node:os"
import path from "node:path"
import { promisify } from "node:util"

const execFileAsync = promisify(execFile)
const ACTION_IDS = new Set(["undo", "redo"])
const MAX_STATE_BYTES = 64 * 1024
const RUNTIME_MARKER_PROTOCOL = "omp-undo-redo/runtime"
const ACTION_STATE_PROTOCOL = "omp-undo-redo/action-state"

function sessionHash(sessionID) {
  return createHash("sha256").update(sessionID).digest("hex")
}

async function readBoundedJSON(file) {
  const metadata = await stat(file)
  if (!metadata.isFile() || metadata.size <= 0 || metadata.size > MAX_STATE_BYTES) return undefined
  const source = await readFile(file, "utf8")
  if (Buffer.byteLength(source, "utf8") > MAX_STATE_BYTES) return undefined
  return JSON.parse(source)
}

function normalizeProtocolState(value) {
  if (!value || typeof value !== "object" || !Array.isArray(value.actions)) return undefined
  if (typeof value.sessionRevision !== "string" || !value.sessionRevision) return undefined
  if (value.activeSessionLeaf !== null && typeof value.activeSessionLeaf !== "string") return undefined
  const actions = value.actions.flatMap((action) => (
    ACTION_IDS.has(action?.id) && typeof action.enabled === "boolean"
      ? [{ id: action.id, enabled: action.enabled }]
      : []
  ))
  if (actions.length !== ACTION_IDS.size || new Set(actions.map((action) => action.id)).size !== ACTION_IDS.size) {
    return undefined
  }
  const actionResult = value.actionResult &&
    ACTION_IDS.has(value.actionResult.id) &&
    typeof value.actionResult.applied === "boolean" &&
    typeof value.actionResult.token === "string" &&
    value.actionResult.token
    ? { id: value.actionResult.id, applied: value.actionResult.applied, token: value.actionResult.token }
    : undefined
  return {
    actions,
    sessionRevision: value.sessionRevision,
    activeSessionLeaf: value.activeSessionLeaf,
    actionResult
  }
}

function normalizeLegacyHistory(value, expectedHash) {
  if (value?.schemaVersion !== 1 || value.sessionHash !== expectedHash || !Array.isArray(value.checkpoints)) return undefined
  const currentIndex = value.currentIndex
  if (!Number.isInteger(currentIndex) || currentIndex < -1 || currentIndex >= value.checkpoints.length) return undefined
  if (value.checkpoints.length === 0) return undefined
  const activeSessionLeaf = currentIndex >= 0
    ? value.checkpoints[currentIndex]?.leafId
    : value.checkpoints[0]?.parentLeafId
  if (activeSessionLeaf !== null && typeof activeSessionLeaf !== "string") return undefined
  return {
    actions: [
      { id: "undo", enabled: currentIndex >= 0 },
      { id: "redo", enabled: currentIndex < value.checkpoints.length - 1 }
    ],
    sessionRevision: `${currentIndex}:${activeSessionLeaf ?? "root"}`,
    activeSessionLeaf
  }
}

function normalizeRuntimeMarker(value, processID) {
  if (
    value?.schemaVersion !== 1 ||
    value.protocol !== RUNTIME_MARKER_PROTOCOL ||
    value.pid !== processID ||
    typeof value.runtimeId !== "string" ||
    !value.runtimeId
  ) return undefined
  return { pid: value.pid, runtimeId: value.runtimeId }
}

function normalizeRuntimeState(value, marker, expectedHash) {
  if (
    value?.schemaVersion !== 2 ||
    value.protocol !== ACTION_STATE_PROTOCOL ||
    value.sessionHash !== expectedHash ||
    value.pid !== marker.pid ||
    value.runtimeId !== marker.runtimeId
  ) return undefined
  return normalizeProtocolState(value)
}

/** Reads authoritative live state first, then falls back to durable Git schema 1. */
export function createOmpUndoRedoActionStateLoader({
  runGit = execFileAsync,
  runtimeRoot = process.env.OMP_UNDO_REDO_RUNTIME_DIR ?? path.join(homedir(), ".omp", "omp-undo-redo", "runtime")
} = {}) {
  const commonDirectories = new Map()

  async function resolveCommonDirectory(directory) {
    let loading = commonDirectories.get(directory)
    if (!loading) {
      loading = runGit("git", ["rev-parse", "--path-format=absolute", "--git-common-dir"], {
        cwd: directory,
        encoding: "utf8",
        windowsHide: true,
        maxBuffer: 64 * 1024
      }).then(({ stdout }) => stdout.trim())
      commonDirectories.set(directory, loading)
    }
    try {
      const commonDirectory = await loading
      if (!commonDirectory) commonDirectories.delete(directory)
      return commonDirectory
    } catch (error) {
      commonDirectories.delete(directory)
      throw error
    }
  }

  async function loadRuntimeState(expectedHash, processID) {
    if (!Number.isInteger(processID) || processID <= 0) return undefined
    try {
      const runtimeDirectory = path.join(runtimeRoot, String(processID))
      const marker = normalizeRuntimeMarker(
        await readBoundedJSON(path.join(runtimeDirectory, "runtime.json")),
        processID
      )
      if (!marker) return undefined
      const value = await readBoundedJSON(path.join(runtimeDirectory, "sessions", `${expectedHash}.json`))
      return normalizeRuntimeState(value, marker, expectedHash)
    } catch {
      return undefined
    }
  }

  async function loadGitState(expectedHash, directory) {
    if (!directory) return undefined
    try {
      const commonDirectory = await resolveCommonDirectory(directory)
      if (!commonDirectory) return undefined
      const statePath = path.join(commonDirectory, "omp-undo-redo", "history", `${expectedHash}.json`)
      const value = await readBoundedJSON(statePath)
      return normalizeProtocolState(value) ?? normalizeLegacyHistory(value, expectedHash)
    } catch {
      return undefined
    }
  }

  return async function loadOmpUndoRedoActionState({ sessionID, directory, processID }) {
    if (!sessionID) return undefined
    const expectedHash = sessionHash(sessionID)
    return await loadRuntimeState(expectedHash, processID) ?? await loadGitState(expectedHash, directory)
  }
}
