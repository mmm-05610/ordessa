#!/usr/bin/env node
// Retired by work order 006: this closeout requires the removed Agent
// configuration/reliable-submission owner. It is not an acceptance result for
// the replacement contract and must fail before package discovery or startup.
process.stderr.write('RETIRED: frontend-product Agent submission closeout has no current managed-input equivalent; no server, browser, package artifact, or user data was opened.\n')
process.exitCode = 1
