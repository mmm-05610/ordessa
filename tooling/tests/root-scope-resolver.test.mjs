import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,symlink,rm} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolveNodeExecutionScopes,nodeTestEntryArguments} from '../checks/node-execution-scopes.mjs';
test('Root actual argv expansion and missing duplicate symlink rejection',async()=>{
 const d=await mkdtemp(path.join(path.dirname(fileURLToPath(import.meta.url)),'owned-scope-'));
 try {
  await mkdir(path.join(d,'tests')); await writeFile(path.join(d,'tests/a.test.mjs'),''); await writeFile(path.join(d,'tests/b.test.mjs'),'');
  assert.deepEqual(nodeTestEntryArguments(['node','--test','--test-concurrency=1','tests/*.test.mjs']),['tests/*.test.mjs']);
  assert.deepEqual((await resolveNodeExecutionScopes(['tests/*.test.mjs'],d)).sort(),['a','b'].map(n=>path.join(d,'tests',n+'.test.mjs')));
  assert.deepEqual(await resolveNodeExecutionScopes(['tests/'],d),[path.join(d,'tests')]);
  await assert.rejects(resolveNodeExecutionScopes(['none/*.mjs'],d),/matched nothing/);
  await assert.rejects(resolveNodeExecutionScopes(['tests/a.test.mjs','tests/*.test.mjs'],d),/duplicate/);
  await assert.rejects(resolveNodeExecutionScopes([],d),/required/);
  await symlink(path.join(d,'tests/a.test.mjs'),path.join(d,'link.test.mjs'));
  await assert.rejects(resolveNodeExecutionScopes(['link.test.mjs'],d),/unsupported/);
 } finally {await rm(d,{recursive:true,force:true});}
});
