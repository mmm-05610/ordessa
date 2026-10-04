from pathlib import Path
import subprocess,json,time,sys
root=Path(__file__).resolve().parents[4]
out=Path(__file__).parent
commands=[['node','specs/026-open-environment-migration/checks/validate-package.mjs'],['.venv/bin/python','-m','pytest','plugins/agent/backend/tests','-q','-p','no:cacheprovider'],['./node_modules/.bin/vitest','run','--root','packages/frontend/ui-components','--exclude','**/closeout*.test.ts','--maxWorkers=1'],['./node_modules/.bin/vitest','run','--root','plugins/profile/integrations/chat','--maxWorkers=1'],['./node_modules/.bin/vitest','run','--root','plugins/model-provider/chat-contribution','--maxWorkers=1']]
records=[]
for i,cmd in enumerate(commands):
 with (out/f'baseline-{i}.log').open('w') as f:
  r=subprocess.run(cmd,cwd=root,stdout=f,stderr=subprocess.STDOUT)
 records.append({'command':cmd,'cwd':str(root),'sourceSha':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),'exitCode':r.returncode,'log':f'baseline-{i}.log'})
 (out/'baseline-results.json').write_text(json.dumps(records,indent=2)+'\n')
 print(i,r.returncode,flush=True)
