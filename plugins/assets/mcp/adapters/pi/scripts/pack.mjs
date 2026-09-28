/**
 * Minimal packaging piece for the Ordessa managed-lane Pi bridge extension.
 *
 * There is no compilation (Pi loads the .ts source through jiti, same route
 * as the acp-adapter permission gate). What packaging MUST do for an
 * executable extension per docs/design/mcp/harness-adapters.md is give it an
 * independent version + license + digest registration so a loader (C0, see
 * api-requests G9) can pin exactly what was reviewed. This script emits
 * dist/manifest.json with those fields; `trustApproval` stays "pending"
 * until a human approval is recorded - packing is never approval.
 */
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const pkg = JSON.parse(readFileSync(path.join(root, "package.json"), "utf8"));
const files = [pkg.piManifest.extensionSource, "package.json"];

const digest = (text) => createHash("sha256").update(text, "utf8").digest("hex");

const manifest = {
	name: pkg.name,
	version: pkg.version,
	license: pkg.license,
	generatedBy: "scripts/pack.mjs",
	trustApproval: "pending",
	artifacts: files.map((rel) => ({
		path: rel,
		sha256: digest(readFileSync(path.join(root, rel), "utf8")),
	})),
};

const outDir = path.join(root, "dist");
mkdirSync(outDir, { recursive: true });
const outPath = path.join(outDir, "manifest.json");
writeFileSync(outPath, `${JSON.stringify(manifest, null, "\t")}\n`, "utf8");
process.stdout.write(`wrote ${path.relative(root, outPath)} (version ${manifest.version})\n`);
for (const artifact of manifest.artifacts) {
	process.stdout.write(`${artifact.sha256}  ${artifact.path}\n`);
}
