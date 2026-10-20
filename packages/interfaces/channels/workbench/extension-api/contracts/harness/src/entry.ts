// The shared contract carrier is API-only; it registers no provider and has no
// activation side effects.
export default function createPlugin() {
  return { id: 'ordessa.harness-contracts', activate() {} }
}
