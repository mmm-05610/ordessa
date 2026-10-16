import { createOmpUndoRedoActionStateLoader } from "./omp-extension-action-state.js"

function commandNames(commands) {
  return new Set(commands.map((command) => command.name?.replace(/^\//, "").toLowerCase()).filter(Boolean))
}

export const OMP_EXTENSION_ACTION_PROVIDERS = [{
  id: "omp-undo-redo",
  requiredCommands: ["undo", "redo"],
  resetOnSessionChange: ["redo"],
  loadState: createOmpUndoRedoActionStateLoader(),
  actions: [
    { id: "undo", command: "undo", enabledByDefault: true },
    { id: "redo", command: "redo", enabledByDefault: false }
  ]
}]

function availableProviders(providers, commands) {
  const names = commandNames(commands)
  return providers.filter((provider) => provider.requiredCommands.every((command) => names.has(command)))
}

export function listExtensionActions(providers, commands, state, busy = false, authoritativeState) {
  return availableProviders(providers, commands).flatMap((provider) => {
    if (authoritativeState?.source === provider.id) {
      return provider.actions.map((action) => ({
        id: action.id,
        source: provider.id,
        enabled: !busy && (authoritativeState.actions.find((candidate) => candidate.id === action.id)?.enabled ?? false)
      }))
    }
    // Stateful providers stay hidden until their availability is authoritative.
    if (provider.loadState) return []
    return provider.actions.map((action) => ({
      id: action.id,
      source: provider.id,
      enabled: !busy && (state.get(action.id) ?? action.enabledByDefault)
    }))
  })
}

export async function loadExtensionActionState(providers, commands, context) {
  const candidates = commands ? availableProviders(providers, commands) : providers
  for (const provider of candidates) {
    if (!provider.loadState) continue
    const state = await provider.loadState(context)
    if (state) return { ...state, source: provider.id }
  }
  return undefined
}

export function resolveExtensionAction(providers, commands, actionID) {
  for (const provider of availableProviders(providers, commands)) {
    const action = provider.actions.find((candidate) => candidate.id === actionID)
    if (action) return { provider, action }
  }
  return undefined
}


export function resetExtensionActionState(providers, commands, state) {
  for (const provider of availableProviders(providers, commands)) {
    for (const actionID of provider.resetOnSessionChange ?? []) state.delete(actionID)
  }
}
