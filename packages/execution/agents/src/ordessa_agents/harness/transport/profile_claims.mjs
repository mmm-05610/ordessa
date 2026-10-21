export const NATIVE_CAPABILITY_TO_CANONICAL = Object.freeze({
  prompt: Object.freeze(["start"]),
  streaming: Object.freeze(["stream"]),
  permissions: Object.freeze(["permissions"]),
})

/**
 * 出现在原生声明里、但**故意**不映射到任何 canonical id 的键，附一句话理由。
 * 这张表是给审计用的：它让"我们考虑过这个键并决定不映射"变成可读事实，
 * 而不是一个看不出来的遗漏。
 */
export const UNMAPPED_NATIVE_CAPABILITIES = Object.freeze({
  abort: "cancel 语义，不是 steer；插件没有任何把 abort 当 steer 的代码",
  filesystemBrowser: "宿主机文件浏览，不是附件投递；attach 只能来自真实附件能力",
  sessions: "session 概念的存在性前提，本身不构成任何 canonical 能力",
  models: "模型选择是 control，不是 canonical 能力",
  todos: "canonical 词汇表没有对应项",
  commands: "canonical 词汇表没有对应项",
  actions: "canonical 词汇表没有对应项",
  diff: "canonical 词汇表没有对应项",
  questions: "canonical 词汇表没有对应项",
  sessionRename: "重命名不是 canonical 能力",
  sessionDelete: "删除不是 canonical 能力",
})

export function captureProfileClaims(declarations, document) {
  const REGISTERED = Object.freeze(Object.fromEntries(declarations.map(value => [value.id,value.profile])))
  let ceilings = {}
  if (document?.schemaVersion === 1 && document.harnessTypes && typeof document.harnessTypes === "object" && !Array.isArray(document.harnessTypes)) {
    for (const [id,values] of Object.entries(document.harnessTypes)) {
      if (!Array.isArray(values) || values.some(value=>typeof value!=="string" || !value)) throw new Error("CAPABILITY_DECLARATION_SHAPE_INVALID")
      ceilings[id]=Object.freeze([...values])
    }
  }
  ceilings=Object.freeze(ceilings)
  const capabilityDeclarations=()=>ceilings
  const declaredCapabilityCeiling=(id)=>new Set(ceilings[id]??[])
function assertBooleanClaims(claims, where) {
  for (const [key, value] of Object.entries(claims)) {
    if (typeof value !== "boolean") {
      throw new Error(`CAPABILITY_CLAIM_NOT_BOOLEAN: ${where}.${key} = ${JSON.stringify(value)}`)
    }
  }
  return claims
}

function canonicalCapabilityClaims(profileID, nativeClaims) {
  const profile = REGISTERED[profileID]
  let native
  if (nativeClaims === undefined) {
    if (!profile) throw new Error(`HARNESS_PROFILE_UNREGISTERED: ${profileID}`)
    native = profile.capabilities ?? {}
  } else {
    if (nativeClaims === null || typeof nativeClaims !== "object" || Array.isArray(nativeClaims)) {
      throw new Error(`CAPABILITY_CLAIM_NOT_BOOLEAN: ${profileID} claims must be an object`)
    }
    native = nativeClaims
  }
  assertBooleanClaims(native, profileID)

  const declared = capabilityDeclarations()[profileID]
  if (!Array.isArray(declared)) {
    throw new Error(`HARNESS_CAPABILITY_UNDECLARED: ${profileID}`)
  }
  const allowed = new Set(declared)

  const claimed = new Set()
  for (const [key, value] of Object.entries(native)) {
    if (value !== true) continue
    for (const id of NATIVE_CAPABILITY_TO_CANONICAL[key] ?? []) claimed.add(id)
  }
  return [...claimed].filter((id) => allowed.has(id)).sort()
}

  return Object.freeze({capabilityDeclarations,declaredCapabilityCeiling,canonicalCapabilityClaims,
    registeredHarnessIDs:()=>Object.keys(REGISTERED).sort(),
    resolveHarnessProfile:(id)=>{const profile=REGISTERED[id];if(!profile)throw new Error(`HARNESS_PROFILE_UNREGISTERED: ${id}`);return profile},
  })
}
