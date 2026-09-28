// A controlled stand-in for the plugin's access entry, speaking only the
// control protocol the Server bridge (`AccessEntryTransport`) uses: it
// answers `connect`, and authors the `close` receipts the retry semantics
// are judged on.  Nothing is spawned - the receipts themselves are the
// subject of the test; every ACP-frame guarantee stays pinned against the
// real entry by test_managed_acp_channel.py.
//
// FAKE_CLOSE_SCRIPT:
//   false-then-true  - first close answers released:false, second released:true
//   delay:<ms>       - the single close answers released:true after <ms>
// FAKE_EVIDENCE: append one JSON line per received close (counting probe).
import fs from "node:fs"
import readline from "node:readline"

const script = process.env.FAKE_CLOSE_SCRIPT || "false-then-true"
const evidence = process.env.FAKE_EVIDENCE
let closes = 0

const send = (message) => process.stdout.write(JSON.stringify(message) + "\n")
const record = (message) => {
  if (evidence) fs.appendFileSync(evidence, JSON.stringify(message) + "\n")
}

const rl = readline.createInterface({ input: process.stdin })
rl.on("line", (line) => {
  let message
  try { message = JSON.parse(line) } catch { return }
  if (message.op === "connect") {
    send({ id: message.id, ok: true,
           result: { connectionId: "fake-connection", harness: "pi" } })
    return
  }
  if (message.op === "close") {
    closes += 1
    record({ op: "close", n: closes })
    if (script.startsWith("delay:")) {
      const ms = Number(script.slice("delay:".length))
      setTimeout(() => send({ id: message.id, ok: true, result: {
        connectionId: "fake-connection", released: true,
        processId: null, signalUsed: false, tree: [],
      } }), ms)
      return
    }
    const released = closes >= 2  // the survivor is gone by the second ask
    send({ id: message.id, ok: true, result: {
      connectionId: "fake-connection", released,
      processId: null, signalUsed: false, tree: [],
    } })
    return
  }
  send({ id: message.id, ok: false, error: {
    code: "FAKE_UNKNOWN_OP", message: `unsupported op ${String(message.op)}` } })
})
rl.on("close", () => process.exit(0))
