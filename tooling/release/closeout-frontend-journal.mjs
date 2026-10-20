#!/usr/bin/env node
// Retired by work order 006: this real-IndexedDB journal closeout requires the
// removed Agent durable-submission client. Its original kill-window scenarios
// have no replacement recovery evidence; refuse before Electron/Chromium,
// package discovery, browser profile creation, or data access.
process.stderr.write('RETIRED: frontend IndexedDB submission-journal closeout has no current managed-input equivalent; no process or data was opened.\n')
process.exitCode = 1
