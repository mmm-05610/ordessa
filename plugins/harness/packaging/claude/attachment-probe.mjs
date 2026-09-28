/** First-hand controlled probe of the pinned Claude ACP adapter's attachment pathway.
 *
 * PD-2 (specs/014-plugin-release/dispatch/P-D-claude-attachments.md). Re-probes what the
 * 0.77.0-era negative evidence recorded ("real handshake promptCapabilities is empty")
 * against the pinned `@agentclientprotocol/claude-agent-acp` 0.81.2, under the same
 * controlled rig as provider-routing-smoke.mjs: loopback fake Anthropic APIs, a temporary
 * Claude config dir and a fake token. Zero real model, zero real credential.
 *
 * What it pins, first-hand (every claim is asserted against the wire, not source):
 *   1. initialize transcription: `agentCapabilities.promptCapabilities` verbatim;
 *   2. image round trip: an ACP prompt image block reaches the fake endpoint as an
 *      Anthropic `image.source.base64` block with sha256-equal content;
 *   3. resource_link semantics: an https URI is delivered verbatim as link text; a
 *      file:// URI as a `[@name](uri)` markdown link - never bytes, never an upload;
 *   4. audio behavior: an audio prompt block is silently dropped by the adapter while
 *      the turn's text still delivers - first-hand proof the channel must type-refuse
 *      audio instead of relaying it;
 *   5. output image (reverse direction): recorded as observed, not claimed - an image
 *      content block streamed by the endpoint produces no image session update through
 *      the native CLI chain (see the transcript's `outputImage` note).
 *
 * Writes a JSON transcript (initialize transcription + every round's hashes and exact
 * wire renderings) to `--out` (default: a temp path) and prints one summary line with
 * the transcript's sha256. Any failed assertion exits non-zero.
 */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { createServer } from "node:http";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { deflateSync } from "node:zlib";
import { Readable, Writable } from "node:stream";
import { fileURLToPath } from "node:url";

import { PROTOCOL_VERSION, client, methods, ndJsonStream } from "@agentclientprotocol/sdk";

const sha256 = (text) => createHash("sha256").update(text, "utf8").digest("hex");

const timeout = (work, label) => {
  let timer;
  return Promise.race([
    work,
    new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(`${label} timed out`)), 60_000);
    }),
  ]).finally(() => clearTimeout(timer));
};

/** A deterministic solid-color PNG; deflateSync at a fixed level is stable per runtime,
 * and every hash in the transcript is computed from these same runtime bytes. */
function solidPng(size, r, g, b) {
  const raw = Buffer.from(
    Array.from({ length: size * size }, () => Buffer.from([r, g, b])).flat(),
  );
  const crcTable = [...Array(256).keys()].map((n) => {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    return c >>> 0;
  });
  const chunk = (type, data) => {
    const header = Buffer.alloc(4);
    header.writeUInt32BE(data.length);
    const body = Buffer.concat([Buffer.from(type, "utf8"), data]);
    let c = 0xffffffff;
    for (const byte of body) c = crcTable[(c ^ byte) & 0xff] ^ (c >>> 8);
    const crcBuf = Buffer.alloc(4);
    crcBuf.writeUInt32BE((c ^ 0xffffffff) >>> 0);
    return Buffer.concat([header, body, crcBuf]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 2; // color type: truecolor
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(raw, { level: 6 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

const sentImage = solidPng(8, 0xff, 0x00, 0x00).toString("base64");
const sentImageSha = sha256(sentImage);
const outputImage = solidPng(8, 0x00, 0x00, 0xff).toString("base64");
const outputImageSha = sha256(outputImage);
const audioPayload = Buffer.from("controlled-audio-bytes-not-a-real-codec").toString("base64");

const TITLE_GENERATION = "Write the title in the predominant language";
const MARKERS = ["probe-image", "probe-link-https", "probe-link-file", "probe-output-image", "probe-audio"];

/** The probe turn a request belongs to. Claude Code replays the accumulated history
 * every turn and fires an independent background title generation over the whole
 * session, so: title calls are excluded, and the marker is matched against the
 * request's NEWEST user message (requests end with system-role messages). */
const lastUserMessage = (body) => {
  const messages = body.messages ?? [];
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i]?.role === "user") return messages[i];
  }
  return null;
};
const marker = (body) => {
  if (JSON.stringify(body.messages ?? []).includes(TITLE_GENERATION)) return null;
  const content = lastUserMessage(body)?.content;
  const text = JSON.stringify(content ?? "");
  return MARKERS.find((name) => text.includes(name)) ?? null;
};

const scratch = await mkdtemp(join(tmpdir(), "ordessa-claude-attach-"));
const outArg = process.argv.indexOf("--out");
const outPath = outArg > -1 ? process.argv[outArg + 1] : join(scratch, "transcript.json");
const calls = [];
const updates = [];
const servers = [];
let adapter;

async function fakeApi() {
  const server = createServer(async (request, response) => {
    let raw = "";
    for await (const chunk of request) raw += chunk;
    if (request.url?.startsWith("/v1/messages/count_tokens")) {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ input_tokens: 20 }));
      return;
    }
    if (!request.url?.startsWith("/v1/messages")) {
      response.writeHead(404);
      response.end();
      return;
    }
    const body = JSON.parse(raw);
    calls.push(body);
    const id = `msg_probe_${calls.length}`;
    const send = (type, data) =>
      response.write(`event: ${type}\ndata: ${JSON.stringify(data)}\n\n`);
    response.writeHead(200, { "content-type": "text/event-stream" });
    send("message_start", {
      type: "message_start",
      message: {
        id, type: "message", role: "assistant", model: body.model, content: [],
        stop_reason: null, stop_sequence: null,
        usage: { input_tokens: 20, output_tokens: 0 },
      },
    });
    if (marker(body) === "probe-output-image") {
      send("content_block_start", {
        type: "content_block_start", index: 0, content_block: { type: "text", text: "" },
      });
      send("content_block_delta", {
        type: "content_block_delta", index: 0,
        delta: { type: "text_delta", text: "ack probe-output-image" },
      });
      send("content_block_stop", { type: "content_block_stop", index: 0 });
      send("content_block_start", {
        type: "content_block_start", index: 1,
        content_block: { type: "image", source: { type: "base64", data: outputImage, media_type: "image/png" } },
      });
      send("content_block_stop", { type: "content_block_stop", index: 1 });
    } else {
      send("content_block_start", {
        type: "content_block_start", index: 0, content_block: { type: "text", text: "" },
      });
      send("content_block_delta", {
        type: "content_block_delta", index: 0,
        delta: { type: "text_delta", text: `ack ${marker(body) ?? "turn"}` },
      });
      send("content_block_stop", { type: "content_block_stop", index: 0 });
    }
    send("message_delta", {
      type: "message_delta", delta: { stop_reason: "end_turn", stop_sequence: null },
      usage: { output_tokens: 3 },
    });
    response.end(`event: message_stop\ndata: {"type":"message_stop"}\n\n`);
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  servers.push(server);
  return `http://127.0.0.1:${server.address().port}`;
}

const transcript = {
  probe: "claude-attachments-v1",
  dispatch: "specs/014-plugin-release/dispatch/P-D-claude-attachments.md PD-2",
  adapter: { package: "@agentclientprotocol/claude-agent-acp" },
  failures: [],
};

try {
  transcript.adapter.version = JSON.parse(await readFile(
    fileURLToPath(new URL(
      "./node_modules/@agentclientprotocol/claude-agent-acp/package.json", import.meta.url,
    )), "utf8",
  )).version;
} catch (error) {
  transcript.failures.push(`adapter version: ${String(error)}`);
}

let stderr = "";
try {
  const base = await fakeApi();
  const env = {
    ...process.env,
    CLAUDE_CONFIG_DIR: join(scratch, "claude-config"),
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1",
    DISABLE_TELEMETRY: "1",
  };
  for (const key of Object.keys(env)) {
    if (key.startsWith("ANTHROPIC_") || key.startsWith("CLAUDE_CODE_OAUTH")) delete env[key];
  }
  const entry = fileURLToPath(new URL(
    "./node_modules/@agentclientprotocol/claude-agent-acp/dist/index.js", import.meta.url,
  ));
  adapter = spawn(process.execPath, [entry], { env, stdio: ["pipe", "pipe", "pipe"] });
  adapter.stderr.on("data", (chunk) => { stderr += chunk; });
  const stream = ndJsonStream(
    Writable.toWeb(adapter.stdin), Readable.toWeb(adapter.stdout),
  );
  const connection = client({ name: "ordessa-controlled-attachment-probe" })
    .onNotification(methods.client.session.update,
      (context) => { updates.push(context?.params); })
    .onRequest(methods.client.session.requestPermission,
      () => ({ outcome: { outcome: "cancelled" } }))
    .onRequest(methods.client.fs.readTextFile, () => ({ content: "" }))
    .onRequest(methods.client.fs.writeTextFile, () => ({}))
    .connect(stream);
  const agent = connection.agent;

  const init = await timeout(agent.request(methods.agent.initialize, {
    protocolVersion: PROTOCOL_VERSION,
    clientCapabilities: {
      fs: { readTextFile: true, writeTextFile: true }, terminal: false,
    },
  }), "initialize");
  transcript.protocolVersion = init.protocolVersion;
  transcript.agentCapabilities = init.agentCapabilities;
  const promptCaps = init.agentCapabilities?.promptCapabilities;
  if (promptCaps?.image !== true || promptCaps?.embeddedContext !== true) {
    transcript.failures.push(
      `promptCapabilities mismatch: ${JSON.stringify(promptCaps)}`);
  }

  const session = await timeout(agent.request(methods.agent.session.new, {
    cwd: scratch, mcpServers: [], _meta: { claudeCode: { options: {
      env: {
        ANTHROPIC_BASE_URL: base, ANTHROPIC_AUTH_TOKEN: "controlled-local-token",
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1",
      },
      settings: { env: { ANTHROPIC_BASE_URL: base, ANTHROPIC_AUTH_TOKEN: "controlled-local-token" } },
    } } },
  }), "session/new");
  const sessionId = session.sessionId;
  /** One round trip. `probe.error` records a failed mandatory round as a gate failure;
   * an exploratory round (output image) records its error as an observation instead,
   * because "the reverse direction is tested if present" must not turn a measured
   * negative into a rig failure. */
  const prompt = async (blocks, label, { optional = false } = {}) => {
    try {
      return await timeout(agent.request(methods.agent.session.prompt, {
        sessionId, prompt: blocks,
      }), `prompt ${label}`);
    } catch (error) {
      const entry = `prompt ${label} error: ${String(error?.message ?? error)}`;
      if (optional) {
        (transcript.observations ??= []).push(entry);
      } else {
        transcript.failures.push(entry);
      }
      return null;
    }
  };
  const userTurns = () => calls.filter((body) => marker(body) !== null);
  const turnFor = (name) => userTurns().find((body) => marker(body) === name);
  const newTurnBlocks = (turn) => {
    const content = lastUserMessage(turn)?.content;
    return Array.isArray(content) ? content : [{ type: "text", text: String(content ?? "") }];
  };
  const newTurnTexts = (turn) => newTurnBlocks(turn)
    .filter((b) => b?.type === "text").map((b) => b.text ?? "");

  // 1. Image round trip: the ACP image block must reach the endpoint base64-intact.
  await prompt([
    { type: "image", data: sentImage, mimeType: "image/png" },
    { type: "text", text: "probe-image: describe the attached png" },
  ], "image");
  const imageTurn = turnFor("probe-image");
  const imageBlocks = newTurnBlocks(imageTurn).filter((b) => b?.type === "image");
  const wireData = imageBlocks.map((b) => b?.source?.data ?? "");
  transcript.imageRoundTrip = {
    mimeType: "image/png", sentAs: "ACP prompt image block (data)",
    sentSha256: sentImageSha, wireSha256: wireData.map(sha256),
    wireSourceTypes: imageBlocks.map((b) => b?.source?.type ?? null),
    match: wireData.some((data) => sha256(data) === sentImageSha),
    deliveredAs: "anthropic user content image.source.base64",
  };
  if (!transcript.imageRoundTrip.match) transcript.failures.push("image round trip hash mismatch");

  // 2. resource_link semantics: the URI travels as link TEXT, nothing more.
  await prompt([
    { type: "resource_link", uri: "https://example.org/notes.md", name: "notes.md" },
    { type: "text", text: "probe-link-https: see the reference" },
  ], "link https");
  const httpsTexts = newTurnTexts(turnFor("probe-link-https"));
  transcript.resourceLinkHttps = {
    uri: "https://example.org/notes.md", wireText: httpsTexts,
    deliveredAs: "text (formatUriAsLink: non-file/zed URI passes through verbatim)",
    delivered: httpsTexts.some((t) => t.includes("https://example.org/notes.md")),
  };
  if (!transcript.resourceLinkHttps.delivered) {
    transcript.failures.push("https resource_link was not delivered as link text");
  }

  await prompt([
    { type: "resource_link", uri: "file:///workspace/notes.md", name: "notes.md" },
    { type: "text", text: "probe-link-file: see the reference" },
  ], "link file");
  const fileTexts = newTurnTexts(turnFor("probe-link-file"));
  transcript.resourceLinkFile = {
    uri: "file:///workspace/notes.md", wireText: fileTexts,
    deliveredAs: "text markdown link ([@name](uri))",
    delivered: fileTexts.some((t) => t.includes("[@notes.md](file:///workspace/notes.md)")),
  };
  if (!transcript.resourceLinkFile.delivered) {
    transcript.failures.push("file resource_link was not delivered as a markdown link");
  }

  // 3. Output image (reverse direction): recorded as observed, never claimed.
  await prompt(
    [{ type: "text", text: "probe-output-image: send a png back" }],
    "output image", { optional: true },
  );
  const imageUpdates = updates.flatMap((notification) => {
    const update = notification?.update;
    return update?.sessionUpdate === "agent_message_chunk" && update?.content?.type === "image"
      ? [update.content] : [];
  });
  transcript.outputImage = {
    endpointSent: { as: "anthropic content_block image.source.base64 (after a text block)", sha256: outputImageSha },
    acpImageChunkSha256: imageUpdates.map((content) => sha256(content.data ?? "")),
    delivered: imageUpdates.some((content) => sha256(content.data ?? "") === outputImageSha),
    deliveredAs: "session/update agent_message_chunk content.image (source path acp-agent.js:7682)",
    note: "measured both ways: an image-only assistant response makes the adapter fail " +
      "the turn with an internal error ([ede_diagnostic] result_type=assistant " +
      "last_content_type=image), while a text+image response delivers the image as an " +
      "agent_message_chunk with sha256-equal content. The output direction is real but " +
      "only behind a text block on this chain.",
  };

  // 4. Audio: pinned first-hand as silently dropped - the channel must refuse, not relay.
  await prompt([
    { type: "audio", data: audioPayload, mimeType: "audio/wav" },
    { type: "text", text: "probe-audio: this turn carries an audio block" },
  ], "audio");
  const audioTurn = turnFor("probe-audio");
  const audioWire = JSON.stringify(audioTurn?.messages ?? {});
  transcript.audio = {
    declared: promptCaps?.audio === true,
    promptCapabilities: promptCaps ?? null,
    wireDropped: !audioWire.includes(audioPayload),
    turnStillDelivered: newTurnTexts(audioTurn).some((t) => t.includes("probe-audio")),
    note: "the adapter's default case drops audio blocks silently; the channel must type-refuse audio instead of relaying it",
  };
  if (!transcript.audio.wireDropped || !transcript.audio.turnStillDelivered) {
    transcript.failures.push("audio behavior deviated from the observed silent-drop");
  }

  // Compact wire evidence: every probe turn's newest user message, hashes for image
  // payloads, verbatim (truncated) texts for the rest.
  transcript.wireTurns = userTurns().map((body) => ({
    marker: marker(body),
    newUserBlocks: newTurnBlocks(body).map((b) => {
      if (b?.type === "image") {
        return { type: "image", sourceType: b?.source?.type ?? null,
          mediaType: b?.source?.media_type ?? null, dataSha256: sha256(b?.source?.data ?? "") };
      }
      if (b?.type === "text") return { type: "text", text: (b.text ?? "").slice(0, 300) };
      return { type: String(b?.type ?? "unknown") };
    }),
  }));
  transcript.updatesSeen = updates.reduce((counts, notification) => {
    const kind = notification?.update?.sessionUpdate ?? "unknown";
    counts[kind] = (counts[kind] ?? 0) + 1;
    return counts;
  }, {});

  transcript.result = transcript.failures.length === 0
    ? "GREEN_FAKE_ENDPOINT" : "RED_FAKE_ENDPOINT";
  if (transcript.result !== "GREEN_FAKE_ENDPOINT" && stderr.trim()) {
    transcript.adapterStderrTail = stderr.slice(-2000);
  }
} catch (error) {
  transcript.failures.push(`probe error: ${String(error?.stack ?? error)}`);
  transcript.result = "RED_FAKE_ENDPOINT";
  if (stderr.trim()) transcript.adapterStderrTail = stderr.slice(-2000);
} finally {
  if (adapter) adapter.kill();
  for (const server of servers) server.close();
}

const body = JSON.stringify(transcript, null, 2) + "\n";
try {
  await writeFile(outPath, body);
  console.log(JSON.stringify({
    result: transcript.result, out: outPath, sha256: sha256(body),
    failures: transcript.failures,
  }));
} catch (error) {
  console.log(JSON.stringify({
    result: transcript.result, out: outPath, writeError: String(error),
    failures: transcript.failures,
  }));
  process.exitCode = 1;
}
if (transcript.result !== "GREEN_FAKE_ENDPOINT") process.exitCode = 1;
await rm(scratch, { recursive: true, force: true }).catch(() => {});
