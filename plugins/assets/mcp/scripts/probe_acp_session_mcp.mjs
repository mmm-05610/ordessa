#!/usr/bin/env node
/**
 * Q4 T00/V00 controlled probe: does the pinned `@agentclientprotocol/codex-acp`
 * adapter consume `session/new.mcpServers` and how?
 *
 * WHAT THIS PROVES / DOES NOT PROVE
 * - Proves adapter-side behavior only (standalone vendored tarball under a fake
 *   codex app-server witness). It does NOT prove the real `@openai/codex` CLI
 *   binary loads the injected config (that装载面 remains unverified elsewhere).
 * - Everything runs in an isolated --work dir; user HOME is never read or written
 *   (adapter HOME points into the work dir); no network except 127.0.0.1 loopback
 *   fake MCP server started by this script itself. No npm, no registry.
 *
 * USAGE
 *   node probe_acp_session_mcp.mjs \
 *     --tgz <path to agentclientprotocol-codex-acp-<ver>.tgz> \
 *     [--work <empty dir; default mkdtemp under os.tmpdir>] \
 *     [--keep]            # keep the work dir (default: remove on success)
 *     [--settle <ms>]     # quiet period after last session/new (default 1500)
 *     [--per-rpc-timeout <ms>]  # default 20000
 *
 * Exit codes: 0 all grids observed, 1 assertion failure, 2 usage/infrastructure
 * error. Prints a JSON summary to stdout and writes <work>/summary.json.
 *
 * Witness files (under --work):
 *   witness/appserver.jsonl   every JSON-RPC frame adapter <-> fake codex app-server
 *   witness/mcp-servers.jsonl every request received by the loopback fake MCP server
 *   witness/adapter-stderr.log, logs/app-server.log (adapter internal logger)
 *
 * Design references (first-hand, codex-acp 1.1.14 dist/index.js line cites):
 *   - CODEX_PATH env injection surface: 31645 (startAcpServer), 22068-22076
 *     (startCodexConnection spawns `CODEX_PATH app-server`, stdio newline JSON-RPC).
 *   - session/new -> createSessionConfig -> thread/start config["mcp_servers"]:
 *     26583-26586, 26670-26697, createMcpSeverConfig 26735-26754 (http -> url +
 *     http_headers; stdio -> command/args/env; sse/acp -> invalidRequest).
 *   - ACP-side mcpServers zod parse (dropped-on-invalid): 19543-19583.
 *   - mcpCapabilities advertisement {acp:false, http:true, sse:false}: 28805-28809.
 *   - config dedupe via config/read (DISABLE_MCP_CONFIG_FILTERING=true to skip):
 *     26687-26690, 27060-27063.
 */
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";

// ---------------------------------------------------------------- CLI parsing
const argv = process.argv.slice(2);
function argOf(flag, dflt) {
  const i = argv.indexOf(flag);
  return i >= 0 ? argv[i + 1] : dflt;
}
const tgzPath = argOf("--tgz");
if (!tgzPath) {
  console.error("usage: node probe_acp_session_mcp.mjs --tgz <codex-acp tgz> [--work <dir>] [--keep]");
  process.exit(2);
}
const KEEP = argv.includes("--keep");
const SETTLE_MS = Number(argOf("--settle", 1500));
const RPC_TIMEOUT = Number(argOf("--per-rpc-timeout", 20000));
const work = argOf("--work", fs.mkdtempSync(path.join(os.tmpdir(), "q4-acp-probe-")));
fs.mkdirSync(work, { recursive: true });
for (const sub of ["src", "home", "home/codex-home", "ws", "witness", "bin", "logs"]) {
  fs.mkdirSync(path.join(work, sub), { recursive: true });
}
const witnessApp = path.join(work, "witness", "appserver.jsonl");
const witnessMcp = path.join(work, "witness", "mcp-servers.jsonl");
const fakeCodexPath = path.join(work, "bin", "codex");
fs.writeFileSync(witnessApp, "");
fs.writeFileSync(witnessMcp, "");

const summary = {
  probe: "acp-session-new-mcpServers",
  adapter: null,
  node: process.version,
  work,
  grids: [],
  failures: [],
  startedAt: new Date().toISOString(),
};
function grid(id, verdict, evidence) {
  summary.grids.push({ id, verdict, evidence });
  if (verdict !== "observed" && verdict !== "observed-negative") {
    summary.failures.push(id);
  }
}

// ------------------------------------------------------- 1. extract the tgz
{
  const r = spawnSync("tar", ["-xzf", path.resolve(tgzPath), "-C", path.join(work, "src")], { encoding: "utf8" });
  if (r.status !== 0) {
    console.error("tar extract failed", r.stderr?.toString());
    process.exit(2);
  }
}
const entry = path.join(work, "src", "package", "dist", "index.js");
if (!fs.existsSync(entry)) {
  console.error("adapter entry not found at", entry);
  process.exit(2);
}
const pkgJson = JSON.parse(fs.readFileSync(path.join(work, "src", "package", "package.json"), "utf8"));
summary.adapter = { name: pkgJson.name, version: pkgJson.version, entry };

// ------------------------------------------- 2. static reachability: --version
{
  const r = spawnSync(process.execPath, [entry, "--version"], {
    encoding: "utf8",
    env: isolatedEnv({}),
    timeout: 15000,
  });
  const out = (r.stdout || "").trim();
  if (r.status === 0 && out.includes(pkgJson.version)) {
    grid("S0-static", "observed", { cmd: "node dist/index.js --version", exit: r.status, stdout: out });
  } else {
    grid("S0-static", "failed", { cmd: "node dist/index.js --version", exit: r.status, stdout: out, stderr: (r.stderr || "").slice(0, 400) });
  }
}

// ------------------------------------------------------- 3. fake codex app-server
// Direct absolute-path shebang: the adapter spawns this file as
// `CODEX_PATH app-server` without a shell (dist/index.js:22072).
const FAKE_CODEX = `#!${process.execPath}
// Minimal fake codex app-server: stdio newline JSON-RPC (jsonrpc key optional --
// the real adapter reader backfills "2.0", writer strips it; see dist/index.js
// createJSONRPCReader/Writer 21940-21994). Appends every frame to witness.
// Response shapes cross-checked against the pinned protocol schema definitions
// (plugins/harness/adapters/acp-adapter/internal/codex/schema/
//  codex_app_server_protocol.v2.schemas.json: InitializeResponse, ThreadStartResponse,
//  ModelListResponse/Model, ConfigReadResponse, GetAccountResponse, SkillsListResponse).
const fs = require("node:fs");
const WITNESS = process.env.PROBE_CODEX_WITNESS;
const HOMEFAKE = process.env.PROBE_FAKE_HOME;
let startN = 0;
function witness(dir, frame) {
  fs.appendFileSync(WITNESS, JSON.stringify({ dir, ts: Date.now(), frame }) + "\\n");
}
function respond(id, result) {
  const msg = { jsonrpc: "2.0", id, result };
  witness("out", msg);
  process.stdout.write(JSON.stringify(msg) + "\\n");
}
function respondErr(id, message) {
  const msg = { jsonrpc: "2.0", id, error: { code: -32601, message } };
  witness("out", msg);
  process.stdout.write(JSON.stringify(msg) + "\\n");
}
const MODEL = {
  defaultReasoningEffort: "medium",
  description: "Fake probe model (witness only, no inference)",
  displayName: "Fake Probe",
  hidden: false,
  id: "fake-probe-model",
  isDefault: true,
  model: "fake-probe-model",
  supportedReasoningEfforts: [{ reasoningEffort: "medium", description: "Medium" }],
  inputModalities: ["text"],
};
function handle(msg) {
  witness("in", msg);
  const { id, method, params } = msg;
  if (id === undefined || id === null) return; // notification: no response
  switch (method) {
    case "initialize":
      return respond(id, {
        platformFamily: "unix",
        platformOs: "linux",
        userAgent: "fake-app-server-probe/0.147.0",
        codexHome: HOMEFAKE + "/codex-home",
      });
    case "account/read":
      return respond(id, { account: null, requiresOpenaiAuth: false });
    case "config/read":
      return respond(id, { config: {}, origins: {}, layers: [] });
    case "skills/list":
      return respond(id, { data: [] });
    case "skills/extraRoots/set":
      return respond(id, {});
    case "mcpServerStatus/list":
      return respond(id, { data: [] });
    case "thread/start": {
      startN += 1;
      const threadId = "probe-thread-" + startN;
      fs.appendFileSync(
        WITNESS,
        JSON.stringify({ dir: "thread-start-structured", n: startN, threadId, params }) + "\\n"
      );
      return respond(id, {
        approvalPolicy: "never",
        approvalsReviewer: "user",
        cwd: (params && params.cwd) || HOMEFAKE,
        model: "fake-probe-model",
        modelProvider: (params && params.modelProvider) || "openai",
        reasoningEffort: "medium",
        sandbox: { mode: "dangerFullAccess" },
        serviceTier: null,
        thread: {
          id: threadId,
          cliVersion: "0.147.0-fake",
          createdAt: Math.floor(Date.now() / 1000),
          updatedAt: Math.floor(Date.now() / 1000),
          cwd: (params && params.cwd) || HOMEFAKE,
          ephemeral: true,
          modelProvider: (params && params.modelProvider) || "openai",
          name: null,
          path: null,
          preview: "",
          source: "app-server",
          status: { type: "idle" },
          turns: [],
        },
      });
    }
    case "model/list":
      return respond(id, { data: [MODEL], nextCursor: null });
    default:
      return respond(id, {});
  }
}
let buf = "";
process.stdin.on("data", (c) => {
  buf += c.toString();
  for (;;) {
    const i = buf.indexOf("\\n");
    if (i < 0) break;
    const line = buf.slice(0, i).trim();
    buf = buf.slice(i + 1);
    if (!line) continue;
    let msg;
    try { msg = JSON.parse(line); } catch { continue; }
    handle(msg);
  }
});
`;
fs.writeFileSync(fakeCodexPath, FAKE_CODEX, { mode: 0o755 });

// ---------------------------------------------------- 4. fake loopback MCP server
const mcpHits = { total: 0, byPath: {} };
const mcpServer = http.createServer((req, res) => {
  let body = "";
  req.on("data", (c) => (body += c));
  req.on("end", () => {
    mcpHits.total += 1;
    mcpHits.byPath[req.url] = (mcpHits.byPath[req.url] || 0) + 1;
    fs.appendFileSync(witnessMcp, JSON.stringify({ ts: Date.now(), url: req.url, headers: req.headers, body: body || null }) + "\n");
    res.setHeader("content-type", "application/json");
    let msg = null;
    try { msg = JSON.parse(body); } catch {}
    if (!msg || msg.method === undefined) {
      res.statusCode = 202;
      res.end("");
      return;
    }
    if (msg.method === "initialize") {
      res.end(JSON.stringify({
        jsonrpc: "2.0", id: msg.id,
        result: {
          protocolVersion: msg.params?.protocolVersion ?? "2025-03-26",
          capabilities: { tools: {} },
          serverInfo: { name: "probe-fake-mcp", version: "0" },
        },
      }));
    } else if (msg.method === "tools/list") {
      res.end(JSON.stringify({ jsonrpc: "2.0", id: msg.id, result: { tools: [] } }));
    } else {
      res.end(JSON.stringify({ jsonrpc: "2.0", id: msg.id, result: {} }));
    }
  });
});
await new Promise((resolve) => mcpServer.listen(0, "127.0.0.1", resolve));
const mcpPort = mcpServer.address().port;

// Sanity: our own MCP client handshake works (so "0 hits" later is meaningful).
{
  const url = `http://127.0.0.1:${mcpPort}/mcp-selftest`;
  const r = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json, text/event-stream" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-03-26", clientInfo: { name: "probe-selftest", version: "0" }, capabilities: {} } }),
  });
  const j = await r.json();
  if (j?.result?.serverInfo?.name === "probe-fake-mcp") {
    grid("S1-fakeMcp-selftest", "observed", { url, status: r.status });
  } else {
    grid("S1-fakeMcp-selftest", "failed", { url, status: r.status, body: j });
  }
  fs.appendFileSync(witnessMcp, JSON.stringify({ note: "----- selftest frames above are from the probe itself, not the adapter -----" }) + "\n");
}

// -------------------------------------------------------- 5. spawn adapter + client
function isolatedEnv(extra) {
  return {
    PATH: "/usr/bin:/bin",
    HOME: path.join(work, "home"),
    CODEX_PATH: fakeCodexPath,
    PROBE_CODEX_WITNESS: witnessApp,
    PROBE_FAKE_HOME: path.join(work, "home"),
    APP_SERVER_LOGS: path.join(work, "logs"),
    ...extra,
  };
}
const adapter = spawn(process.execPath, [entry], {
  cwd: path.join(work, "home"),
  env: isolatedEnv({}),
  stdio: ["pipe", "pipe", "pipe"],
  detached: true, // own process group; fake codex child dies with it on killpg
});
const stderrLog = fs.openSync(path.join(work, "witness", "adapter-stderr.log"), "a");
adapter.stderr.on("data", (c) => fs.writeSync(stderrLog, c));
adapter.on("exit", (code, sig) => {
  summary.adapterExit = { code, sig };
});

let rpcId = 0;
const pending = new Map();
const notifications = [];
const agentToClientRequests = [];
adapter.stdout.on("data", (chunk) => {
  for (const line of String(chunk).split("\n")) {
    const t = line.trim();
    if (!t) continue;
    let msg;
    try { msg = JSON.parse(t); } catch { continue; }
    if (msg.id !== undefined && msg.method !== undefined) {
      agentToClientRequests.push(msg);
      adapter.stdin.write(JSON.stringify({ jsonrpc: "2.0", id: msg.id, error: { code: -32601, message: "probe: unhandled agent request" } }) + "\n");
    } else if (msg.id !== undefined) {
      const p = pending.get(msg.id);
      if (p) { pending.delete(msg.id); p.resolve(msg); }
    } else {
      notifications.push(msg);
    }
  }
});
function rpc(method, params, expectOk = true) {
  const id = ++rpcId;
  const promise = new Promise((resolve, reject) => {
    const to = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`timeout waiting for response to ${method} (id ${id})`));
    }, RPC_TIMEOUT);
    pending.set(id, { resolve: (m) => { clearTimeout(to); resolve(m); } });
  });
  adapter.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n");
  return promise.then((m) => {
    if (expectOk && m.error) {
      const e = new Error(`${method} error ${m.error.code}: ${m.error.message}`);
      e.response = m;
      throw e;
    }
    return m;
  });
}

try {
  const init = await rpc("initialize", {
    protocolVersion: 1,
    clientCapabilities: { fs: { readTextFile: false, writeTextFile: false }, terminal: false },
    clientInfo: { name: "q4-acp-probe", version: "0.0.0" },
  });
  const caps = init.result?.agentCapabilities ?? {};
  grid("S2-acp-initialize", "observed", {
    agentInfo: init.result?.agentInfo,
    mcpCapabilities: caps.mcpCapabilities ?? null,
    sessionCapabilities: caps.sessionCapabilities ?? null,
  });

  const ws = path.join(work, "ws");
  const httpServer = (name, p, headers) => ({
    name, type: "http", url: `http://127.0.0.1:${mcpPort}${p}`,
    headers: headers ?? [{ name: "X-Probe-Key", value: `${name}-secret` }],
  });

  // A: one http mcpServer
  const a = await rpc("session/new", { cwd: ws, mcpServers: [httpServer("probe", "/mcp")] });
  const sessionIdA = a.result?.sessionId;
  // B: different name/path (double-session non-crosstalk partner)
  const b = await rpc("session/new", { cwd: ws, mcpServers: [httpServer("probe-b", "/mcpb")] });
  const sessionIdB = b.result?.sessionId;
  // C: negative control. First WITHOUT the field at all (wire-shape evidence:
  // the bundled agent-side parser marks mcpServers as required-on-error-default),
  // then with an explicit empty list which is the real negative control.
  const cOmit = (() => {
    const id = ++rpcId;
    const promise = new Promise((resolve) => {
      const to = setTimeout(() => { pending.delete(id); resolve({ timeout: true }); }, RPC_TIMEOUT);
      pending.set(id, { resolve: (m) => { clearTimeout(to); resolve(m); } });
    });
    adapter.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method: "session/new", params: { cwd: ws } }) + "\n");
    return promise;
  })();
  const cOmitResp = await cOmit;
  grid("G6-wire-required-field", cOmitResp.error ? "observed" : "unknown", {
    attempt: "session/new without mcpServers field",
    response: cOmitResp,
  });
  const c = await rpc("session/new", { cwd: ws, mcpServers: [] });
  const sessionIdC = c.result?.sessionId;
  // D: one valid + one schema-invalid entry (missing headers) -> vecSkipError drops it
  const d = await rpc("session/new", {
    cwd: ws,
    mcpServers: [
      { name: "dropped", type: "http", url: `http://127.0.0.1:${mcpPort}/mcpd` },
      httpServer("probe-d", "/mcpd"),
    ],
  });
  const sessionIdD = d.result?.sessionId;

  await new Promise((r) => setTimeout(r, SETTLE_MS));
  fs.writeSync(stderrLog, "\n----- settle done -----\n");
  const settleMs = SETTLE_MS;

  // ---- evidence extraction from app-server witness -------------------------
  const frames = fs.readFileSync(witnessApp, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
  const starts = frames.filter((f) => f.dir === "thread-start-structured");
  const inFrames = frames.filter((f) => f.dir === "in").map((f) => f.frame);
  const methodsSeen = Array.from(new Set(inFrames.map((f) => f.method).filter(Boolean)));

  const expectedSessions = [
    { tag: "A", sessionId: sessionIdA, wantServers: { probe: { url: `http://127.0.0.1:${mcpPort}/mcp`, http_headers: { "X-Probe-Key": "probe-secret" } } } },
    { tag: "B", sessionId: sessionIdB, wantServers: { "probe-b": { url: `http://127.0.0.1:${mcpPort}/mcpb`, http_headers: { "X-Probe-Key": "probe-b-secret" } } } },
    { tag: "C", sessionId: sessionIdC, wantServers: null },
    { tag: "D", sessionId: sessionIdD, wantServers: { "probe-d": { url: `http://127.0.0.1:${mcpPort}/mcpd`, http_headers: { "X-Probe-Key": "probe-d-secret" } } } },
  ];
  if (starts.length !== expectedSessions.length) {
    grid("G-frames", "failed", { expected: expectedSessions.length, actual: starts.length, methodsSeen });
  }
  const threadIds = new Set(starts.map((s) => s.threadId));

  expectedSessions.forEach((exp, i) => {
    const st = starts[i];
    if (!st) return;
    const gotServers = st.params?.config?.["mcp_servers"];
    if (exp.wantServers === null) {
      const ok = st.params?.cwd === ws && (gotServers === undefined || Object.keys(gotServers).length === 0);
      grid("G3-negative-no-mcpServers", ok ? "observed-negative" : "failed", {
        threadId: st.threadId, hasMcpServersKey: gotServers !== undefined, mcp_servers: gotServers ?? null,
      });
      return;
    }
    const wantNames = Object.keys(exp.wantServers).sort();
    const gotNames = Object.keys(gotServers ?? {}).sort();
    const nameOk = JSON.stringify(wantNames) === JSON.stringify(gotNames);
    const fieldOk = wantNames.every((n) => {
      const w = exp.wantServers[n];
      const g = gotServers?.[n];
      return g && g.url === w.url && JSON.stringify(g.http_headers ?? null) === JSON.stringify(w.http_headers);
    });
    const idOk = exp.sessionId === st.threadId;
    grid(`G1-injection-${exp.tag}`, nameOk && fieldOk && idOk ? "observed" : "failed", {
      sessionIdReturned: exp.sessionId, threadStartThread: st.threadId,
      wantNames, gotNames, fieldsMatch: fieldOk, sessionMatchesThread: idOk,
      mcp_servers: gotServers ?? null,
      fullConfigKeys: Object.keys(st.params?.config ?? {}),
    });
  });

  // G2: adapter must NOT connect to the fake MCP servers itself.
  {
    const adapterSide = { total: mcpHits.total, byPath: mcpHits.byPath };
    const selftestHits = Object.keys(mcpHits.byPath).filter((p) => p === "/mcp-selftest").reduce((s, p) => s + mcpHits.byPath[p], 0);
    const nonSelftest = adapterSide.total - selftestHits;
    grid("G2-adapter-does-not-connect", nonSelftest === 0 ? "observed-negative" : "failed", {
      mcpRequestTotal: adapterSide.total, byPath: adapterSide.byPath, settleMs,
      note: "only the /mcp-selftest hit from the probe itself is present; adapter produced zero MCP HTTP requests",
    });
  }

  // G4: double-session non-crosstalk: thread starts A and B carry disjoint server sets,
  // session ids distinct.
  {
    const aServers = starts[0]?.params?.config?.["mcp_servers"] ?? {};
    const bServers = starts[1]?.params?.config?.["mcp_servers"] ?? {};
    const disjoint = Object.keys(aServers).every((k) => !(k in bServers)) && Object.keys(bServers).every((k) => !(k in aServers));
    grid("G4-two-sessions-disjoint", disjoint && sessionIdA !== sessionIdB && threadIds.size === starts.length ? "observed" : "failed", {
      aServerNames: Object.keys(aServers), bServerNames: Object.keys(bServers),
      sessionIdA, sessionIdB, distinctThreads: threadIds.size,
    });
  }

  // G5: backend frame inventory (what the adapter actually sent per session).
  grid("G5-frame-inventory", "observed", {
    appServerMethods: methodsSeen,
    threadStartCount: starts.length,
    perThreadConfig: starts.map((s) => ({
      threadId: s.threadId,
      configKeys: Object.keys(s.params?.config ?? {}),
      mcp_servers: s.params?.config?.["mcp_servers"] ?? null,
    })),
    dedupeConfigReadUsed: methodsSeen.includes("config/read"),
  });

  summary.sessionIds = { sessionIdA, sessionIdB, sessionIdC, sessionIdD };
} catch (err) {
  grid("RUN", "failed", { error: String(err?.stack || err), response: err?.response ?? null });
} finally {
  // -------------------------------------------------------- 6. teardown (pgid)
  try { process.kill(-adapter.pid, "SIGTERM"); } catch {}
  await new Promise((r) => setTimeout(r, 300));
  try { process.kill(-adapter.pid, "SIGKILL"); } catch {}
  mcpServer.close();
  fs.closeSync(stderrLog);
  summary.finishedAt = new Date().toISOString();
  summary.stdoutNotifications = notifications.length;
  summary.agentToClientRequests = agentToClientRequests.map((m) => m.method);
  const out = JSON.stringify(summary, null, 2);
  if (!summary.failures.length && !KEEP) {
    // snapshot summary before removing work dir
    const persisted = path.join(os.tmpdir(), `q4-acp-probe-summary-${Date.now()}.json`);
    fs.writeFileSync(persisted, out + "\n");
    summary.summarySavedTo = persisted;
    fs.rmSync(work, { recursive: true, force: true });
  } else {
    fs.writeFileSync(path.join(work, "summary.json"), out + "\n");
    summary.summarySavedTo = path.join(work, "summary.json");
  }
  console.log(JSON.stringify(summary, null, 2));
  process.exit(summary.failures.length ? 1 : 0);
}
